#!/usr/bin/env bash
# Build the SPA with the Cloud Run API URL and deploy to Firebase Hosting.
# Usage: set -a; source config.env; set +a; ./06-deploy-firebase-hosting.sh
#
# Requires: firebase CLI, and either `firebase login` or
# GOOGLE_APPLICATION_CREDENTIALS pointing at firebase-hosting-deploy.json.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FE="${REPO_ROOT}/frontend"

: "${GCP_PROJECT:=project-990664b0-1bae-4746-88d}"

if [[ "${GCP_PROJECT}" == "project-naturalpath" ]]; then
  echo "ERROR: refusing to deploy Firebase Hosting to project-naturalpath" >&2
  exit 1
fi

# Prefer explicit API_URL / VITE_*; never fall back to localhost from .env.local.
if [[ -z "${VITE_NATURAL_PATH_API_URL:-}" ]]; then
  if [[ -n "${API_URL:-}" ]]; then
    VITE_NATURAL_PATH_API_URL="${API_URL}"
  else
    VITE_NATURAL_PATH_API_URL="$(gcloud run services describe "${API_SERVICE:-natural-path-api}" \
      --project "${GCP_PROJECT}" \
      --region "${GCP_REGION:-us-central1}" \
      --format='value(status.url)' 2>/dev/null || true)"
  fi
fi
: "${VITE_NATURAL_PATH_API_URL:?Set VITE_NATURAL_PATH_API_URL or API_URL (Cloud Run API), not localhost}"

if [[ "${VITE_NATURAL_PATH_API_URL}" =~ localhost|127\.0\.0\.1|onrender\.com|natural-path-api-a3idqol5ra ]]; then
  echo "ERROR: refusing to bake localhost or the previous API host into production" >&2
  exit 1
fi

OAUTH_CLIENT_ID="${VITE_GOOGLE_OAUTH_CLIENT_ID:-${GOOGLE_OAUTH_CLIENT_ID:-}}"
PLACES_API_KEY="${VITE_GOOGLE_PLACES_API_KEY:-${VITE_GOOGLE_MAPS_API_KEY:-}}"

export VITE_NATURAL_PATH_API_URL
export VITE_GOOGLE_OAUTH_CLIENT_ID="${OAUTH_CLIENT_ID}"
export VITE_GOOGLE_PLACES_API_KEY="${PLACES_API_KEY}"

# The checked-in hosting key belongs to project-naturalpath. Never use it for another project.
SA_KEY="${REPO_ROOT}/deploy/gcp/firebase-hosting-deploy.json"
if [[ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" && "${GCP_PROJECT}" == "project-naturalpath" && -f "${SA_KEY}" ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${SA_KEY}"
fi

echo ">> Building SPA with VITE_NATURAL_PATH_API_URL=${VITE_NATURAL_PATH_API_URL}"
(
  cd "${FE}"
  npm ci --prefer-offline
  # Shell exports beat .env.local; .env.production also documents the prod URL.
  npm run build
)

if rg -q 'localhost:8001|127\.0\.0\.1:8001|onrender\.com|natural-path-api-a3idqol5ra' "${FE}/dist/assets"/*.js; then
  echo "ERROR: built assets still contain localhost, Render, or the previous API host — aborting deploy" >&2
  exit 1
fi

echo ">> Deploying Firebase Hosting (${GCP_PROJECT})"
(
  cd "${REPO_ROOT}"
  firebase deploy --only hosting --project "${GCP_PROJECT}" --non-interactive
)

echo ">> Hosting live: https://${GCP_PROJECT}.web.app"
echo "   Verify: curl -sL https://${GCP_PROJECT}.web.app/assets/index-*.js | rg -o 'https://natural-path-api[^\" ]+'"
