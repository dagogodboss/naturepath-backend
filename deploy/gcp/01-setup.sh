#!/usr/bin/env bash
# Enable required GCP APIs and load secrets into Secret Manager.
# Usage: set -a; source config.env; set +a; ./01-setup.sh
set -euo pipefail

: "${GCP_PROJECT:?set GCP_PROJECT}"
: "${GCP_REGION:?set GCP_REGION}"

echo ">> Setting project to ${GCP_PROJECT}"
gcloud config set project "${GCP_PROJECT}" >/dev/null

echo ">> Enabling APIs (run, build, artifactregistry, secretmanager)"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com

# Create or update a secret from an env var.
put_secret() {
  local name="$1" value="$2"
  if [[ -z "${value}" ]]; then
    echo "   - skip ${name} (empty)"
    return 0
  fi
  if gcloud secrets describe "${name}" >/dev/null 2>&1; then
    printf '%s' "${value}" | gcloud secrets versions add "${name}" --data-file=- >/dev/null
    echo "   - updated ${name}"
  else
    printf '%s' "${value}" | gcloud secrets create "${name}" --data-file=- --replication-policy=automatic >/dev/null
    echo "   - created ${name}"
  fi
}

echo ">> Loading secrets into Secret Manager"
put_secret mongo-url        "${MONGO_URL:-}"
put_secret redis-url        "${REDIS_URL:-}"
put_secret jwt-secret       "${JWT_SECRET_KEY:-}"
put_secret revel-api-key    "${REVEL_API_KEY:-}"
put_secret revel-api-secret "${REVEL_API_SECRET:-}"
# Optional Resend (skipped when empty). Prefer Hostinger SMTP in config.env.
put_secret resend-api-key   "${RESEND_API_KEY:-}"
put_secret smtp-password    "${SMTP_PASSWORD:-}"
put_secret microsoft-client-secret "${MICROSOFT_CLIENT_SECRET:-}"
put_secret google-business-profile-access-token "${GOOGLE_BUSINESS_PROFILE_ACCESS_TOKEN:-}"
put_secret yelp-api-key "${YELP_API_KEY:-}"

# Grant the Cloud Run runtime service account access to read the secrets.
PROJECT_NUMBER="$(gcloud projects describe "${GCP_PROJECT}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo ">> Granting secret access to ${RUNTIME_SA}"
for s in mongo-url redis-url jwt-secret revel-api-key revel-api-secret resend-api-key smtp-password microsoft-client-secret google-business-profile-access-token yelp-api-key; do
  if gcloud secrets describe "${s}" >/dev/null 2>&1; then
    gcloud secrets add-iam-policy-binding "${s}" \
      --member="serviceAccount:${RUNTIME_SA}" \
      --role="roles/secretmanager.secretAccessor" >/dev/null 2>&1 || true
  fi
done

echo ">> Setup complete."
