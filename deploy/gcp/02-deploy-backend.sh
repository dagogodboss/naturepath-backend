#!/usr/bin/env bash
# Build & deploy the FastAPI backend to Cloud Run (source deploy uses backend/backend/Dockerfile).
# Usage: set -a; source config.env; set +a; ./02-deploy-backend.sh
#
# CORS: set CORS_ALLOWED_ORIGINS (or WEB_URL) to the live frontend origin(s) before prod traffic.
# After 03-deploy-frontend.sh, update CORS to the printed WEB_URL if needed.
# Next: ./05-deploy-worker.sh for Celery worker+beat.
set -euo pipefail

: "${GCP_PROJECT:?}"; : "${GCP_REGION:?}"; : "${API_SERVICE:?}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${REPO_ROOT}/backend/backend"

# CORS: comma-separated browser origins. Include both Cloud Run URL shapes + local Vite.
# WEB_URL can be a single origin or a comma list; defaults keep prod + localhost safe to re-run.
DEFAULT_CORS="https://thenaturalpathla.com,https://www.thenaturalpathla.com,https://project-naturalpath.web.app,https://project-naturalpath.firebaseapp.com,https://natural-path-web-azk5hyheza-uc.a.run.app,https://natural-path-web-844976016709.us-central1.run.app,http://localhost:5173,http://127.0.0.1:5173"
CORS_ORIGINS="${CORS_ALLOWED_ORIGINS:-${WEB_URL:-$DEFAULT_CORS}}"

# Optional blog/vlog media (see 04-content-media.sh)
GCS_BUCKET="${GCS_BUCKET:-}"
CDN_BASE_URL="${CDN_BASE_URL:-}"
REDIS_CONTENT_URL="${REDIS_CONTENT_URL:-}"
GOOGLE_OAUTH_CLIENT_ID="${GOOGLE_OAUTH_CLIENT_ID:-}"

NETWORK_FLAGS=()
if [[ -n "${VPC_NETWORK:-}" ]]; then
  : "${VPC_SUBNET:?Set VPC_SUBNET when VPC_NETWORK is configured}"
  NETWORK_FLAGS=(--network "${VPC_NETWORK}" --subnet "${VPC_SUBNET}" --vpc-egress private-ranges-only)
elif [[ -n "${VPC_CONNECTOR:-}" ]]; then
  NETWORK_FLAGS=(--vpc-connector "${VPC_CONNECTOR}" --vpc-egress private-ranges-only)
fi

# Use ^|^ delimiter so CORS_ALLOWED_ORIGINS may contain commas.
# Email is opt-in. Leave SENDER_EMAIL, SMTP_*, and RESEND_API_KEY unset for no mail provider.
ENV_VARS="^|^APP_ENV=production|DEBUG=false|DB_NAME=${DB_NAME:-natural_path_spa}|CORS_ALLOWED_ORIGINS=${CORS_ORIGINS}|CLINIC_TIMEZONE=${CLINIC_TIMEZONE:-America/Chicago}|REVEL_API_URL=https://api.revelup.com|REVEL_SUBDOMAIN=${REVEL_SUBDOMAIN:-thenaturalpathla}|REVEL_ESTABLISHMENT_ID=${REVEL_ESTABLISHMENT_ID:-1}|PUBLIC_APP_URL=${PUBLIC_APP_URL:-https://thenaturalpathla.com}"
if [[ -n "${GCS_BUCKET}" ]]; then
  ENV_VARS="${ENV_VARS}|GCS_BUCKET=${GCS_BUCKET}"
fi
if [[ -n "${CDN_BASE_URL}" ]]; then
  ENV_VARS="${ENV_VARS}|CDN_BASE_URL=${CDN_BASE_URL}"
fi
if [[ -n "${REDIS_CONTENT_URL}" ]]; then
  ENV_VARS="${ENV_VARS}|REDIS_CONTENT_URL=${REDIS_CONTENT_URL}"
fi
if [[ -n "${GOOGLE_OAUTH_CLIENT_ID}" ]]; then
  ENV_VARS="${ENV_VARS}|GOOGLE_OAUTH_CLIENT_ID=${GOOGLE_OAUTH_CLIENT_ID}"
fi
[[ -n "${OPS_EMAIL:-}" ]] && ENV_VARS="${ENV_VARS}|OPS_EMAIL=${OPS_EMAIL}"
[[ -n "${REVIEW_ALERT_EMAIL:-}" ]] && ENV_VARS="${ENV_VARS}|REVIEW_ALERT_EMAIL=${REVIEW_ALERT_EMAIL}"
[[ -n "${GOOGLE_BUSINESS_ACCOUNT_ID:-}" ]] && ENV_VARS="${ENV_VARS}|GOOGLE_BUSINESS_ACCOUNT_ID=${GOOGLE_BUSINESS_ACCOUNT_ID}"
[[ -n "${GOOGLE_BUSINESS_LOCATION_ID:-}" ]] && ENV_VARS="${ENV_VARS}|GOOGLE_BUSINESS_LOCATION_ID=${GOOGLE_BUSINESS_LOCATION_ID}"
[[ -n "${YELP_BUSINESS_ID:-}" ]] && ENV_VARS="${ENV_VARS}|YELP_BUSINESS_ID=${YELP_BUSINESS_ID}"
if [[ -n "${OUTLOOK_DEVICE_CODE_OAUTH_ENABLED:-}" ]]; then
  ENV_VARS="${ENV_VARS}|OUTLOOK_DEVICE_CODE_OAUTH_ENABLED=${OUTLOOK_DEVICE_CODE_OAUTH_ENABLED}"
fi
if [[ -n "${MULTI_RESOURCE_SCHEDULING:-}" ]]; then
  ENV_VARS="${ENV_VARS}|MULTI_RESOURCE_SCHEDULING=${MULTI_RESOURCE_SCHEDULING}"
fi
if [[ -n "${MICROSOFT_CLIENT_ID:-}" ]]; then
  ENV_VARS="${ENV_VARS}|MICROSOFT_CLIENT_ID=${MICROSOFT_CLIENT_ID}|MICROSOFT_TENANT_ID=${MICROSOFT_TENANT_ID:-common}"
  [[ -n "${MICROSOFT_REDIRECT_URI:-}" ]] && ENV_VARS="${ENV_VARS}|MICROSOFT_REDIRECT_URI=${MICROSOFT_REDIRECT_URI}"
  [[ -n "${MICROSOFT_GRAPH_WEBHOOK_URL:-}" ]] && ENV_VARS="${ENV_VARS}|MICROSOFT_GRAPH_WEBHOOK_URL=${MICROSOFT_GRAPH_WEBHOOK_URL}"
fi
# Mail is opt-in. Leave SENDER_EMAIL and SMTP unset to deploy without a mailbox.
if [[ -n "${SENDER_EMAIL:-}" ]]; then
  ENV_VARS="${ENV_VARS}|SENDER_EMAIL=${SENDER_EMAIL}"
fi
# SMTP (Hostinger). Password goes via Secret Manager; other fields as env.
if [[ -n "${SMTP_HOST:-}" ]]; then
  ENV_VARS="${ENV_VARS}|SMTP_HOST=${SMTP_HOST}|SMTP_PORT=${SMTP_PORT:-465}|SMTP_USE_TLS=${SMTP_USE_TLS:-true}"
  [[ -n "${SMTP_USERNAME:-}" ]] && ENV_VARS="${ENV_VARS}|SMTP_USERNAME=${SMTP_USERNAME}"
  [[ -n "${SMTP_SENDER_EMAIL:-}" ]] && ENV_VARS="${ENV_VARS}|SMTP_SENDER_EMAIL=${SMTP_SENDER_EMAIL}"
fi

# Build secret flags only for secrets that exist (so partial setups still deploy).
SECRET_FLAGS=()
add_secret() { gcloud secrets describe "$2" --project "${GCP_PROJECT}" >/dev/null 2>&1 && SECRET_FLAGS+=("$1=$2:latest") || true; }
require_secret() {
  if ! gcloud secrets describe "$2" --project "${GCP_PROJECT}" >/dev/null 2>&1; then
    echo "!! Refusing to deploy: required secret ${2} for ${1} is not readable." >&2
    exit 1
  fi
  SECRET_FLAGS+=("$1=$2:latest")
}
require_secret MONGO_URL        "${MONGO_SECRET_NAME:-mongo-url}"
require_secret REDIS_URL        "${REDIS_SECRET_NAME:-redis-url}"
require_secret JWT_SECRET_KEY   jwt-secret
require_secret REVEL_API_KEY    revel-api-key
require_secret REVEL_API_SECRET revel-api-secret
# Only bind Resend when explicitly configured (empty → no email provider).
if [[ -n "${RESEND_API_KEY:-}" ]]; then
  add_secret RESEND_API_KEY   resend-api-key
fi
if [[ -n "${SMTP_HOST:-}" ]]; then
  add_secret SMTP_PASSWORD    smtp-password
fi
add_secret MICROSOFT_CLIENT_SECRET microsoft-client-secret
add_secret GOOGLE_BUSINESS_PROFILE_ACCESS_TOKEN google-business-profile-access-token
add_secret YELP_API_KEY yelp-api-key
SECRETS_ARG=""
if ((${#SECRET_FLAGS[@]})); then
  SECRETS_ARG="$(IFS=,; echo "${SECRET_FLAGS[*]}")"
fi

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_route_traffic_to_latest.sh"

echo ">> Deploying ${API_SERVICE} from ${SRC}"
echo "   CORS_ALLOWED_ORIGINS=${CORS_ORIGINS}"
if [[ -z "${GOOGLE_OAUTH_CLIENT_ID}" ]]; then
  echo "   WARN: GOOGLE_OAUTH_CLIENT_ID unset — Google sign-in disabled on API"
fi
# Do not pass --no-traffic on normal deploys. Prior pinned traffic (specific
# revisionName) would otherwise leave the new revision at 0% until a manual
# update-traffic. route_traffic_to_latest restores latestRevision=true.
# Canary-only: CLOUD_RUN_NO_TRAFFIC=1 ./02-deploy-backend.sh
DEPLOY_CMD=(
  gcloud run deploy "${API_SERVICE}"
  --project "${GCP_PROJECT}"
  --region "${GCP_REGION}"
  --source "${SRC}"
  --platform managed
  --allow-unauthenticated
  --port 8080
  --cpu 1 --memory 1Gi
  --min-instances 0 --max-instances 4
  --timeout 600
  --set-env-vars "${ENV_VARS}"
)
if [[ -n "${SECRETS_ARG}" ]]; then
  DEPLOY_CMD+=(--set-secrets "${SECRETS_ARG}")
fi
if ((${#NETWORK_FLAGS[@]})); then
  DEPLOY_CMD+=("${NETWORK_FLAGS[@]}")
fi
"${DEPLOY_CMD[@]}"

route_traffic_to_latest "${API_SERVICE}"

URL="$(gcloud run services describe "${API_SERVICE}" --project "${GCP_PROJECT}" --region "${GCP_REGION}" --format='value(status.url)')"
echo ">> Backend deployed: ${URL}"
echo "   Health: ${URL}/api/health"
echo ">> Next: ./03-deploy-frontend.sh then set CORS_ALLOWED_ORIGINS to the web URL;"
echo "         then ./05-deploy-worker.sh for Celery worker+beat."
