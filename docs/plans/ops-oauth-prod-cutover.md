# Multi-resource production cutover — OAuth + flag (ops)

**Canonical workspace copy:** `/Users/mac/naturepath/docs/plans/ops-oauth-prod-cutover.md` (keep in sync when editing).

**GCP project:** `project-990664b0-1bae-4746-88d` only. **Do not change DNS.**

## Blocker (2026-10-18)

| Check | Result |
|-------|--------|
| Last dry-run | `phase6_post_consent_cutover --dry-run` on **naturepath-data-1** |
| Artifact time | `2026-10-18T18:54:01Z` |
| Exit | **10** (`entra_admin_consent_required`) |
| JWT `roles` | **empty** (no `Calendars.Read`) |
| Clients@ `calendarView` | **403 Forbidden** |
| Staging cutover / prod flag | **not run** |
| Artifact | `qa/reports/multi-resource-proof/post-consent-cutover-staging-20261018.json` (+ `-vpc.json`) |

**Ask (Entra Global Administrator):** Accept **Calendars.Read** (Application) admin consent for app `daf7c7db-7a14-4b8b-8209-58b168d34683` / tenant `bbefcd77-2f78-4240-85f3-41dcf671c9bf`.

Admin consent URL:

`https://login.microsoftonline.com/bbefcd77-2f78-4240-85f3-41dcf671c9bf/adminconsent?client_id=daf7c7db-7a14-4b8b-8209-58b168d34683`

Outreach draft: [ops-entra-consent-request.md](./ops-entra-consent-request.md). Tracking: [naturepath#8](https://github.com/dagogodboss/naturepath/issues/8).

**Do not** start 15m/3h poll loops. Re-probe only after admin reports Accept (or optional single dry-run).

## One-command cutover (after Accept)

From VPC host `naturepath-data-1` (or any host with `MONGO_URL` + Microsoft env from Secret Manager). **No DNS steps.**

```bash
cd ~/naturepath/backend   # or checkout path with backend/ + scripts/
set -a; source backend/.env 2>/dev/null; set +a
export DB_NAME=natural_path_staging
export MULTI_RESOURCE_SCHEDULING=true
export MICROSOFT_CLIENT_SECRET="$(gcloud secrets versions access latest --secret=microsoft-client-secret --project=project-990664b0-1bae-4746-88d)"
# MONGO_URL / JWT_SECRET_KEY / MICROSOFT_CLIENT_ID / MICROSOFT_TENANT_ID already on VM env or .env

# Staging cutover + Discovery≠Salt prove (INJECT_SYNTHETIC_BUSY=0 inside script):
PYTHONPATH=backend python3 -m scripts.phase6_post_consent_cutover \
  --report-dir ../qa/reports/multi-resource-proof
```

Dry-run only (expect exit **10** until consent):

```bash
PYTHONPATH=backend python3 -m scripts.phase6_post_consent_cutover \
  --dry-run --report-dir ../qa/reports/multi-resource-proof
```

**Prod** (optional, only after staging P1–P8 + Jonathan sign-off):

```bash
PYTHONPATH=backend python3 -m scripts.phase6_post_consent_cutover \
  --prod --i-understand-prod \
  --report-dir ../qa/reports/multi-resource-proof
```

**Do not** enable prod `MULTI_RESOURCE_SCHEDULING` until that gate passes.

## Flags today

| Service | `MULTI_RESOURCE_SCHEDULING` | `OUTLOOK_APP_ONLY_SYNC_ENABLED` | Notes |
|---------|----------------------------|----------------------------------|-------|
| `natural-path-api-staging` | **true** | absent / false until cutover | Cutover script sets app-only=true |
| `natural-path-api` (prod traffic) | **unset** on `natural-path-api-00021-hv8` | unset | Keep off |

See root doc for device-code alternate, connection IDs, and rollback.
