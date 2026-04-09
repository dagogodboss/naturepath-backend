# AWS deployment runbook — Natural Path (API + workers + data + static frontend)

This document describes how to deploy the **FastAPI backend** (port **8001** in Docker), **Celery workers**, **MongoDB**, **Redis**, and the **Vite React frontend** to AWS.  
Complete **Prerequisites** before running `aws` or `docker` commands (including a valid AWS session: `aws sts get-caller-identity`).

---

## 1. Prerequisites

1. **Re-authenticate**
   - SSO: `aws login` (or your org’s equivalent).
   - Or access keys: `aws configure` with `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
2. **Choose a region** (e.g. `us-east-1`) and set:
   ```bash
   export AWS_REGION=us-east-1
   aws sts get-caller-identity
   ```
3. **Install tools:** AWS CLI v2, Docker CLI, Compose plugin (or `docker-compose`), `jq` (optional).

### Docker on macOS (Colima)

Local image builds and ECR push use the **Docker CLI**. On this project, **Colima** provides the Docker engine (instead of Docker Desktop).

1. Install (Homebrew example): `brew install colima docker docker-compose`
2. Start the Linux VM that runs Docker: `colima start`
3. Verify: `colima status`, then `docker ps` (should connect without “cannot connect to Docker daemon”).
4. If `docker` fails, try `colima stop && colima start` and confirm no other tool is pointing at a stale context (`docker context ls`).

Use the same `docker build` / `docker login` / `docker push` commands in section 3 once Colima is running. For local **API + DB** day-to-day dev, `./run-local.sh` uses Python + Node directly and does not require Colima unless you are exercising Docker.

---

## 2. Architecture options

| Pattern | Best for | Components |
|--------|-----------|------------|
| **A. MVP — EC2 + Docker Compose** | Fastest path, small traffic | One EC2, same layout as `backend/docker-compose.yml`, Nginx reverse proxy, optional Elastic IP |
| **B. Production — ECS Fargate** | HA, no server patching | ECR images, ECS services (API + worker + beat), ALB, Secrets Manager |
| **C. Hybrid** | Managed DB/cache | **MongoDB Atlas** + **ElastiCache Redis** + ECS or EC2 for app |

**Recommendation:** Start with **A** or **C** (Atlas + ElastiCache) if you want production-grade data without running Mongo on EC2.

---

## 3. Container images (ECR)

Backend Dockerfile: `backend/backend/Dockerfile` — exposes **8001**.

From the **monorepo root** (`naturepath/`, parent of `backend/` and `frontend/`):

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=${AWS_REGION:-us-east-1}
aws ecr create-repository --repository-name natural-path-api --region $AWS_REGION 2>/dev/null || true

# macOS + Colima: ensure `colima start` completed so `docker` can reach the daemon
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker build -t natural-path-api:latest -f backend/backend/Dockerfile backend/backend
docker tag natural-path-api:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/natural-path-api:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/natural-path-api:latest
```

Use the **same image** for Celery worker and beat with **different commands**:

- API: `uvicorn server:app --host 0.0.0.0 --port 8001`
- Worker: `celery -A infrastructure.queue.celery_config worker --loglevel=info`
- Beat: `celery -A infrastructure.queue.celery_config beat --loglevel=info`

---

## 4. Environment variables (production)

Map from `backend/backend/core/config.py` (Pydantic reads env vars in **UPPER_SNAKE** for many settings — confirm with your `.env` naming; common pattern is `MONGO_URL`, `REDIS_URL`, `JWT_SECRET_KEY`).

| Variable | Purpose |
|----------|---------|
| `MONGO_URL` | Mongo connection string (Atlas or DocumentDB) |
| `DB_NAME` | Database name |
| `REDIS_URL` | Celery broker + cache (`rediss://` if TLS) |
| `JWT_SECRET_KEY` | **Rotate** — use Secrets Manager, not the dev default |
| `APP_ENV` | `production` |
| `DEBUG` | `false` |
| `RESEND_API_KEY` / Twilio vars | Optional notifications |
| `CORS` | Set in `server.py` — restrict to your CloudFront / app domain |

**Frontend:** build with:

```bash
cd frontend
echo "VITE_NATURAL_PATH_API_URL=https://api.yourdomain.com" > .env.production
npm run build
```

**Important:** Default local API is `http://localhost:8000` in some docs, but **Docker exposes 8001** — production URL must match whatever the ALB/Nginx targets (typically **443 → 8001**).

---

## 5. Option A — Single EC2 (Docker Compose)

1. Launch **Amazon Linux 2023** or **Ubuntu** (t3.medium+), security group:
   - **22** (SSH, restrict to your IP)
   - **80/443** (HTTP/HTTPS from internet or ALB only)
2. Install Docker + Compose plugin.
3. Copy `backend/docker-compose.yml` — **remove dev volume mounts** for production; use built images from ECR or build on instance.
4. Set `.env` on the host or use `environment:` in compose (prefer SSM Parameter Store / Secrets Manager injected at boot).
5. Put **Nginx** or **Caddy** in front for TLS (Let’s Encrypt) and proxy `/` → API and WebSocket upgrade headers for `/ws/`.

**TLS:** ACM certificate on an **Application Load Balancer** in front of EC2 is often simpler than cert management on the box.

---

## 6. Option B — ECS Fargate (outline)

1. Create **VPC** (or use default), **private subnets** for tasks, **public subnets** for ALB.
2. **ALB** → target group → port **8001** (container port).
3. **ECS cluster** → **task definition**:
   - Image from ECR
   - CPU/memory per service
   - Secrets from **Secrets Manager** (`secrets` in task def)
4. Separate **ECS services** for: API (desired count ≥ 2), Celery worker, Celery beat (count 1).
5. **Security groups:** ALB → tasks **8001** only; tasks → Mongo/Redis on private SGs.

WebSockets: enable **sticky sessions** on the target group or use a single API task until you add a shared connection layer.

---

## 7. MongoDB

- **Atlas:** Create M10+ cluster, allowlist ECS/EC2 egress IPs or use VPC peering.
- **DocumentDB:** Compatible with Mongo driver; note TLS and connection string format.

Seed data: run your existing seed path (see `server.py` startup / scripts in repo) once against production DB (protected behind VPN or one-off task).

---

## 8. Redis

- **ElastiCache Redis** in the same VPC as ECS/EC2.
- Use `rediss://` if encryption in transit is required; update Celery broker URL accordingly.

---

## 9. Static frontend (S3 + CloudFront)

```bash
aws s3 mb s3://natural-path-frontend-prod --region $AWS_REGION
aws s3 sync frontend/dist s3://natural-path-frontend-prod --delete
# Create CloudFront distribution with OAI/OAC; set default root object index.html
# Add custom error response 403/404 → /index.html for SPA routing
```

Set **CORS** on the API to allow the CloudFront domain.

---

## 10. Post-deploy checklist

- [ ] `GET https://api.../health` (or your health route) returns OK
- [ ] Login works; JWT secret is not the dev default
- [ ] Booking flow end-to-end against production API
- [ ] Celery worker processes tasks (check CloudWatch logs / `docker logs`)
- [ ] WebSocket path works through load balancer (if used)
- [ ] Frontend `VITE_NATURAL_PATH_API_URL` points to production API

---

## 11. What this runbook does *not* automate

- IAM roles/policies (least privilege per service)
- WAF, GuardDuty, backup policies
- **Backend** CI/CD is partially covered by `.github/workflows/deploy-backend-ecs.yml` (you still supply AWS secrets / IAM).

For **Infrastructure as Code**, add Terraform or AWS CDK in a follow-up and mirror the same topology.

### CI — deploy on `git push` (implemented in-repo)

Git has **`pre-push`** (runs before the remote accepts the object) but **no `post-push` hook**, so a “deploy after push without blocking my laptop” flow should live on the **remote**:

- This repo includes **`.github/workflows/deploy-backend-ecs.yml`**, which builds the API image on **GitHub-hosted runners** (no Colima needed), pushes to **ECR**, and runs **`ecs update-service --force-new-deployment`** when you push to **`main`** / **`master`** and `backend/backend/**` changes.

**Repository secrets** (GitHub → **Settings → Secrets and variables → Actions**):

| Secret | Purpose |
|--------|---------|
| `AWS_ACCESS_KEY_ID` | IAM user or key allowed to push to ECR and update the ECS service |
| `AWS_SECRET_ACCESS_KEY` | Matching secret key |

Optional: replace long-lived keys with **OIDC** + an IAM role (`aws-actions/configure-aws-credentials` with `role-to-assume`).

**Husky** at the repo root (see root `package.json` and `.husky/pre-push`) is only for **optional local checks**. It does **not** run AWS deploy (avoids tying push success to your network, Colima, and AWS CLI). After a fresh clone, run `npm install` at the repo root so `husky` can set `core.hooksPath` (requires a `.git` directory). Uncomment lint in `.husky/pre-push` if you want pushes blocked on failing `npm run lint` in `frontend/`.

---

## 12. Related docs

- Ecommerce / Revel product roadmap: [`ECOMMERCE_REVEL_PLAN.md`](./ECOMMERCE_REVEL_PLAN.md)
- Product backlog / integration status: [`../memory/PRD.md`](../memory/PRD.md)
