# GCP deployment runbook — Natural Path (Cloud Run)

Deploys the **FastAPI backend**, the **Vite React frontend**, and (optionally) the
**Celery worker/beat** to **Google Cloud Run**. This replaces the AWS path in
[`DEPLOYMENT_AWS.md`](./DEPLOYMENT_AWS.md).

Helper scripts live in `deploy/gcp/` at the repo root.

---

## 0. Architecture on GCP

| Component | GCP service | Notes |
|-----------|-------------|-------|
| Backend API (FastAPI) | **Cloud Run** (`natural-path-api`) | Listens on `$PORT` (8080). WebSockets supported. Scales 0→N. |
| Frontend (Vite SPA) | **Cloud Run** (`natural-path-web`) | nginx image; `VITE_NATURAL_PATH_API_URL` baked in at build time. |
| MongoDB | **MongoDB Atlas** (external) | Cloud Run cannot host Mongo. Use an Atlas SRV string. |
| Redis (cache + Celery broker) | **Memorystore** or external (Upstash/Redis Cloud) | Memorystore needs a Serverless VPC connector. |
| Celery worker + beat | **Cloud Run worker pool** *or* **Cloud Run Job + Cloud Scheduler** | See §6. Needs Redis. |
| Secrets | **Secret Manager** | Mongo/Redis URLs, JWT, Revel keys, Resend key. |
| Image registry | **Artifact Registry** | `cloud-run-source-deploy` repo auto-created by source deploys. |

> The backend **fails to start without a reachable MongoDB** (`Database.connect()`
> raises). Redis is optional for boot (cache degrades), but Celery task dispatch
> from request handlers (`auth`, `booking`) needs a real broker.

---

## 1. Prerequisites

```bash
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud auth list   # confirm active account
```

Required inputs you must supply:
- **MongoDB Atlas** connection string.
- **Redis** URL (Memorystore IP or external managed URL).
- A strong **JWT secret**: `openssl rand -hex 32`.

---

## 2. Configure

```bash
cd deploy/gcp
cp config.env.example config.env
# edit config.env: GCP_PROJECT, GCP_REGION, MONGO_URL, REDIS_URL, JWT_SECRET_KEY, REVEL_*, RESEND_API_KEY
set -a; source config.env; set +a
```

`config.env` holds connection strings — keep it out of git (already covered by
`.gitignore` patterns; verify before committing).

---

## 3. One-time setup (APIs + secrets)

```bash
./01-setup.sh
```

This enables `run`, `cloudbuild`, `artifactregistry`, `secretmanager`, writes the
secrets, and grants the Cloud Run runtime service account
`secretmanager.secretAccessor`.

---

## 4. Deploy the backend

```bash
./02-deploy-backend.sh
```

- Source deploy uses `backend/backend/Dockerfile` (now honors `$PORT`).
- Injects secrets via `--set-secrets` and non-secret config via `--set-env-vars`
  (`APP_ENV=production`, `DEBUG=false`, `DB_NAME`, `CORS_ALLOWED_ORIGINS`, Revel subdomain).
- Prints the service URL; check `…/api/health`.

If using **Memorystore**, set `VPC_CONNECTOR` in `config.env` first (see §6).

---

## 5. Deploy the frontend

```bash
./03-deploy-frontend.sh         # auto-resolves backend URL, or pass API_URL=...
```

Then point the backend's CORS at the web origin (the script prints this command):

```bash
gcloud run services update "$API_SERVICE" --region "$GCP_REGION" \
  --update-env-vars CORS_ALLOWED_ORIGINS=https://natural-path-web-xxxxx.run.app
```

---

## 6. Celery worker + beat (needs Redis)

Cloud Run **request services scale to zero and require an HTTP listener**, which a
Celery worker is not. Two supported patterns:

### Option A — Cloud Run worker pool (recommended)
A worker pool runs a non-HTTP container continuously (manual/min instances), ideal
for `celery worker`. Beat can run embedded with `-B`:

```bash
gcloud run worker-pools deploy "$WORKER_SERVICE" \
  --source backend/backend --region "$GCP_REGION" \
  --command celery \
  --args=-A,infrastructure.queue.celery_config,worker,-B,--loglevel=info \
  --set-secrets MONGO_URL=mongo-url:latest,REDIS_URL=redis-url:latest,JWT_SECRET_KEY=jwt-secret:latest,REVEL_API_KEY=revel-api-key:latest,REVEL_API_SECRET=revel-api-secret:latest,RESEND_API_KEY=resend-api-key:latest \
  --set-env-vars DB_NAME="$DB_NAME",APP_ENV=production \
  ${VPC_CONNECTOR:+--vpc-connector "$VPC_CONNECTOR"} \
  --min-instances 1 --max-instances 1
```

### Option B — Cloud Run Job + Cloud Scheduler (no always-on cost)
Skip beat; deploy a **Job** that runs the periodic tasks once, and trigger it from
**Cloud Scheduler** (e.g. every minute/hour). Good when you want zero idle cost.

### Memorystore Redis + VPC connector (if not using external Redis)
```bash
gcloud redis instances create natural-path-redis --size=1 --region="$GCP_REGION" --tier=basic
gcloud compute networks vpc-access connectors create natural-path-conn \
  --region="$GCP_REGION" --range=10.8.0.0/28
# then set VPC_CONNECTOR=natural-path-conn and REDIS_URL=redis://<instance-ip>:6379/0, re-run setup + deploys
```

---

## 7. Post-deploy checklist

- [ ] `GET https://<api>/api/health` → `{"status":"healthy"}`
- [ ] Frontend loads and calls the API (no CORS errors in console)
- [ ] Login works; JWT secret is not the dev default
- [ ] Booking flow works (needs Redis if Celery dispatch is hit)
- [ ] Revel product sync works against `thenaturalpathla`
- [ ] Worker processes scheduled tasks (if deployed)

---

## 8. CI/CD (follow-up)

Mirror the AWS GitHub Actions with a Cloud Run equivalent: authenticate via
**Workload Identity Federation**, then `gcloud run deploy --source` on push to
`main`. The existing `.github/workflows/deploy-backend-ecs.yml` (AWS) can be
retired once GCP is the target.
