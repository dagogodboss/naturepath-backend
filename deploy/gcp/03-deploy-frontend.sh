#!/usr/bin/env bash
# Build & deploy the Vite SPA to Cloud Run. The backend URL is baked in at build time
# via a Docker build-arg (Cloud Build), then the image is deployed to Cloud Run.
# Usage: set -a; source config.env; set +a; ./03-deploy-frontend.sh
#
# Set VITE_GOOGLE_OAUTH_CLIENT_ID (or GOOGLE_OAUTH_CLIENT_ID) in config.env so GIS works.
# Optional: VITE_GOOGLE_PLACES_API_KEY for checkout autocomplete + direction maps.
# After deploy, point API CORS at WEB_URL (script prints the command).
set -euo pipefail

: "${GCP_PROJECT:?}"; : "${GCP_REGION:?}"; : "${WEB_SERVICE:?}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${REPO_ROOT}/frontend"

# Resolve the backend URL: explicit API_URL wins, else look it up from Cloud Run.
if [[ -z "${API_URL:-}" ]]; then
  API_URL="$(gcloud run services describe "${API_SERVICE:-natural-path-api}" \
    --project "${GCP_PROJECT}" \
    --region "${GCP_REGION}" --format='value(status.url)' 2>/dev/null || true)"
fi
: "${API_URL:?Could not resolve backend URL; deploy backend first or pass API_URL=...}"

OAUTH_CLIENT_ID="${VITE_GOOGLE_OAUTH_CLIENT_ID:-${GOOGLE_OAUTH_CLIENT_ID:-}}"
PLACES_API_KEY="${VITE_GOOGLE_PLACES_API_KEY:-${VITE_GOOGLE_MAPS_API_KEY:-}}"

TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/cloud-run-source-deploy/${WEB_SERVICE}:${TAG}"

echo ">> Building ${WEB_SERVICE} image with VITE_NATURAL_PATH_API_URL=${API_URL}"
if [[ -z "${OAUTH_CLIENT_ID}" ]]; then
  echo "   WARN: VITE_GOOGLE_OAUTH_CLIENT_ID unset — Google button disabled in SPA"
fi
if [[ -z "${PLACES_API_KEY}" ]]; then
  echo "   WARN: VITE_GOOGLE_PLACES_API_KEY unset — Places autocomplete + Maps Embed fallback to OSM"
fi
gcloud builds submit "${SRC}" \
  --project "${GCP_PROJECT}" \
  --config "${SRC}/cloudbuild.yaml" \
  --substitutions "_IMAGE=${IMAGE},_API_URL=${API_URL},_GOOGLE_OAUTH_CLIENT_ID=${OAUTH_CLIENT_ID},_GOOGLE_PLACES_API_KEY=${PLACES_API_KEY}"

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_route_traffic_to_latest.sh"

echo ">> Deploying ${WEB_SERVICE}"
# Do not pass --no-traffic; always move 100% to the new ready revision after deploy.
gcloud run deploy "${WEB_SERVICE}" \
  --project "${GCP_PROJECT}" \
  --region "${GCP_REGION}" \
  --image "${IMAGE}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 1 --memory 512Mi \
  --min-instances 0 --max-instances 4

route_traffic_to_latest "${WEB_SERVICE}"

WEB_URL="$(gcloud run services describe "${WEB_SERVICE}" --project "${GCP_PROJECT}" --region "${GCP_REGION}" --format='value(status.url)')"
echo ">> Frontend deployed: ${WEB_URL}"
echo ">> Next: point backend CORS at the web URL (required for production browsers) ->"
echo "   gcloud run services update ${API_SERVICE:-natural-path-api} --region ${GCP_REGION} --update-env-vars CORS_ALLOWED_ORIGINS=${WEB_URL}"
echo "   Or set CORS_ALLOWED_ORIGINS in config.env and re-run ./02-deploy-backend.sh"
echo ">> Then: ./05-deploy-worker.sh for Celery worker+beat"
