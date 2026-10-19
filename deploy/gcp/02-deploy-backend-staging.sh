#!/usr/bin/env bash
# Deploy staging API (natural-path-api-staging) — same source/VPC/secrets as prod, separate DB + flag.
# Usage:
#   export GCP_PROJECT=project-990664b0-1bae-4746-88d
#   export GCP_REGION=us-central1
#   export VPC_NETWORK=naturepath-prod VPC_SUBNET=naturepath-app-us-central1
#   ./02-deploy-backend-staging.sh
# Requires mongo user dbOwner on DB_NAME (default natural_path_staging) — see phase-6 runbook.
set -euo pipefail

: "${GCP_PROJECT:?}"; : "${GCP_REGION:?}"
# Never inherit prod API_SERVICE from config.env — staging must stay on natural-path-api-staging.
export API_SERVICE="natural-path-api-staging"
export DB_NAME="${DB_NAME:-natural_path_staging}"
export APP_ENV_OVERRIDE="${APP_ENV_OVERRIDE:-staging}"
export MULTI_RESOURCE_SCHEDULING="${MULTI_RESOURCE_SCHEDULING:-true}"
export OUTLOOK_DEVICE_CODE_OAUTH_ENABLED="${OUTLOOK_DEVICE_CODE_OAUTH_ENABLED:-true}"
export OUTLOOK_APP_ONLY_SYNC_ENABLED="${OUTLOOK_APP_ONLY_SYNC_ENABLED:-false}"
# Cloud Run mounts Secret Manager mongo-url / redis-url (not *-vm VM-only names).
export MONGO_SECRET_NAME="mongo-url"
export REDIS_SECRET_NAME="redis-url"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${REPO_ROOT}/backend/backend"

STAGING_URL="$(gcloud run services describe "${API_SERVICE}" \
  --project "${GCP_PROJECT}" --region "${GCP_REGION}" \
  --format='value(status.url)' 2>/dev/null || true)"

CORS="${CORS_ALLOWED_ORIGINS:-https://${GCP_PROJECT}.web.app,https://${GCP_PROJECT}.firebaseapp.com,http://localhost:5173,http://127.0.0.1:5173}"

ENV_VARS="^|^APP_ENV=${APP_ENV_OVERRIDE}|DEBUG=false|DB_NAME=${DB_NAME}|MULTI_RESOURCE_SCHEDULING=${MULTI_RESOURCE_SCHEDULING}|OUTLOOK_DEVICE_CODE_OAUTH_ENABLED=${OUTLOOK_DEVICE_CODE_OAUTH_ENABLED}|OUTLOOK_APP_ONLY_SYNC_ENABLED=${OUTLOOK_APP_ONLY_SYNC_ENABLED}|CORS_ALLOWED_ORIGINS=${CORS}|CLINIC_TIMEZONE=${CLINIC_TIMEZONE:-America/Chicago}|REVEL_API_URL=https://api.revelup.com|REVEL_SUBDOMAIN=${REVEL_SUBDOMAIN:-thenaturalpathla}|REVEL_ESTABLISHMENT_ID=${REVEL_ESTABLISHMENT_ID:-1}|PUBLIC_APP_URL=${PUBLIC_APP_URL:-https://thenaturalpathla.com}"

# Preserve app-only / device-code readiness (revision 00006+). --set-env-vars replaces all.
if [[ -n "${MICROSOFT_CLIENT_ID:-}" ]]; then
  ENV_VARS="${ENV_VARS}|MICROSOFT_CLIENT_ID=${MICROSOFT_CLIENT_ID}|MICROSOFT_TENANT_ID=${MICROSOFT_TENANT_ID:-common}"
fi

if [[ -n "${STAGING_URL}" ]]; then
  ENV_VARS="${ENV_VARS}|MICROSOFT_REDIRECT_URI=${STAGING_URL}/api/practitioners/outlook/callback|MICROSOFT_GRAPH_WEBHOOK_URL=${STAGING_URL}/api/practitioners/outlook/webhook"
fi

# Reuse secret wiring from 02-deploy-backend.sh when config.env is sourced.
SECRET_FLAGS=()
require_secret() {
  gcloud secrets describe "$2" --project "${GCP_PROJECT}" >/dev/null
  SECRET_FLAGS+=("$1=$2:latest")
}
require_secret MONGO_URL "${MONGO_SECRET_NAME:-mongo-url}"
require_secret REDIS_URL "${REDIS_SECRET_NAME:-redis-url}"
require_secret JWT_SECRET_KEY jwt-secret
require_secret REVEL_API_KEY revel-api-key
require_secret REVEL_API_SECRET revel-api-secret
require_secret SMTP_PASSWORD smtp-password
require_secret MICROSOFT_CLIENT_SECRET microsoft-client-secret
SECRETS_ARG="$(IFS=,; echo "${SECRET_FLAGS[*]}")"

NETWORK_FLAGS=(--network "${VPC_NETWORK:-naturepath-prod}" --subnet "${VPC_SUBNET:-naturepath-app-us-central1}" --vpc-egress private-ranges-only)

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_route_traffic_to_latest.sh"

echo ">> Deploying staging ${API_SERVICE} (DB_NAME=${DB_NAME}, MULTI_RESOURCE_SCHEDULING=${MULTI_RESOURCE_SCHEDULING})"
# Do not pass --no-traffic: we always want the new ready revision to serve after deploy.
# If traffic was previously pinned to a revisionName, update-traffic --to-latest below
# restores latestRevision=true so future deploys also receive traffic automatically.
gcloud run deploy "${API_SERVICE}" \
  --project "${GCP_PROJECT}" \
  --region "${GCP_REGION}" \
  --source "${SRC}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 1 --memory 1Gi \
  --min-instances 0 --max-instances 2 \
  --timeout 600 \
  "${NETWORK_FLAGS[@]}" \
  --set-env-vars "${ENV_VARS}" \
  --set-secrets "${SECRETS_ARG}"

route_traffic_to_latest "${API_SERVICE}"

URL="$(gcloud run services describe "${API_SERVICE}" --project "${GCP_PROJECT}" --region "${GCP_REGION}" --format='value(status.url)')"
echo ">> Staging API: ${URL}"
echo "   Health: ${URL}/api/health"
echo "   After first deploy, re-run once to set MICROSOFT_* URLs to ${URL} if they were placeholders."
