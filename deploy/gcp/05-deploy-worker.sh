#!/usr/bin/env bash
# Deploy Celery worker + beat to Cloud Run worker pools (DEPLOYMENT_GCP.md §6 Option A).
# Run AFTER 02-deploy-backend.sh (and 01-setup.sh so Redis/Mongo secrets exist).
#
# Usage:
#   set -a; source config.env; set +a
#   ./05-deploy-worker.sh
#
# Requires REDIS_URL (broker) reachable from the worker (external Redis or VPC connector).
set -euo pipefail

: "${GCP_PROJECT:?}"; : "${GCP_REGION:?}"
: "${WORKER_SERVICE:=natural-path-worker}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${REPO_ROOT}/backend/backend"

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

ENV_VARS="^|^APP_ENV=production|DEBUG=false|DB_NAME=${DB_NAME:-natural_path_spa}|REVEL_API_URL=https://api.revelup.com|REVEL_SUBDOMAIN=${REVEL_SUBDOMAIN:-thenaturalpathla}|REVEL_ESTABLISHMENT_ID=${REVEL_ESTABLISHMENT_ID:-1}|PUBLIC_APP_URL=${PUBLIC_APP_URL:-https://thenaturalpathla.com}"
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
if [[ -n "${MICROSOFT_CLIENT_ID:-}" ]]; then
  ENV_VARS="${ENV_VARS}|MICROSOFT_CLIENT_ID=${MICROSOFT_CLIENT_ID}|MICROSOFT_TENANT_ID=${MICROSOFT_TENANT_ID:-common}"
  [[ -n "${MICROSOFT_REDIRECT_URI:-}" ]] && ENV_VARS="${ENV_VARS}|MICROSOFT_REDIRECT_URI=${MICROSOFT_REDIRECT_URI}"
  [[ -n "${MICROSOFT_GRAPH_WEBHOOK_URL:-}" ]] && ENV_VARS="${ENV_VARS}|MICROSOFT_GRAPH_WEBHOOK_URL=${MICROSOFT_GRAPH_WEBHOOK_URL}"
fi
if [[ -n "${SENDER_EMAIL:-}" ]]; then
  ENV_VARS="${ENV_VARS}|SENDER_EMAIL=${SENDER_EMAIL}"
fi
if [[ -n "${SMTP_HOST:-}" ]]; then
  ENV_VARS="${ENV_VARS}|SMTP_HOST=${SMTP_HOST}|SMTP_PORT=${SMTP_PORT:-465}|SMTP_USE_TLS=${SMTP_USE_TLS:-true}"
  [[ -n "${SMTP_USERNAME:-}" ]] && ENV_VARS="${ENV_VARS}|SMTP_USERNAME=${SMTP_USERNAME}"
  [[ -n "${SMTP_SENDER_EMAIL:-}" ]] && ENV_VARS="${ENV_VARS}|SMTP_SENDER_EMAIL=${SMTP_SENDER_EMAIL}"
fi

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

if [[ -z "${REDIS_URL:-}" ]] && ! gcloud secrets describe "${REDIS_SECRET_NAME:-redis-url}" --project "${GCP_PROJECT}" >/dev/null 2>&1; then
  echo "!! REDIS_URL / redis-url secret required for Celery broker" >&2
  exit 1
fi

echo ">> Deploying Celery worker+beat (${WORKER_SERVICE}) from ${SRC}"
echo "   Command: celery -A infrastructure.queue.celery_config worker -B --loglevel=info"

# Prefer worker-pools (non-HTTP). GA path first, then beta; else HTTP Cloud Run fallback.
WORKER_POOLS_CMD=""
if gcloud run worker-pools deploy --help >/dev/null 2>&1; then
  WORKER_POOLS_CMD=(gcloud run worker-pools deploy)
elif gcloud beta run worker-pools deploy --help >/dev/null 2>&1; then
  WORKER_POOLS_CMD=(gcloud beta run worker-pools deploy)
fi

if ((${#WORKER_POOLS_CMD[@]})); then
  echo ">> Using Cloud Run worker-pools (${WORKER_POOLS_CMD[*]})"
  DEPLOY_CMD=("${WORKER_POOLS_CMD[@]}" "${WORKER_SERVICE}"
    --project "${GCP_PROJECT}"
    --region "${GCP_REGION}"
    --source "${SRC}"
    --command celery
    --args=-A,infrastructure.queue.celery_config,worker,-B,--loglevel=info
    --cpu 1 --memory 1Gi
    --set-env-vars "${ENV_VARS}"
  )
  if [[ -n "${SECRETS_ARG}" ]]; then
    DEPLOY_CMD+=(--set-secrets "${SECRETS_ARG}")
  fi
  if ((${#NETWORK_FLAGS[@]})); then
    DEPLOY_CMD+=("${NETWORK_FLAGS[@]}")
  fi
  "${DEPLOY_CMD[@]}"
else
  echo "ERROR: Cloud Run worker-pools are unavailable in this gcloud installation." >&2
  echo "A Celery process cannot be deployed as an HTTP Cloud Run service because it does not listen on PORT." >&2
  exit 1
fi

echo ">> Worker deployed: ${WORKER_SERVICE}"
echo "   After 02-deploy-backend.sh, run: ./05-deploy-worker.sh"
echo "   Confirm Redis connectivity and that beat schedule fires (see DEPLOYMENT_GCP.md §6)."
