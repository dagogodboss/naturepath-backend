#!/usr/bin/env bash
# Provision blog/vlog media infra: GCS bucket (PAP-safe) and optional Redis e2-small.
# Usage:
#   set -a; source config.env; set +a
#   ./04-content-media.sh
#
# Aligns with docs/GCS_CDN_SETUP.md: Public Access Prevention — do NOT grant allUsers.
# After this, re-run 02-deploy-backend.sh so Cloud Run picks up GCS_BUCKET / CDN_BASE_URL.
set -euo pipefail

: "${GCP_PROJECT:?}"
: "${GCP_REGION:?}"

# Only pin account when explicitly set — exporting empty clears gcloud's active user.
if [[ -n "${CLOUDSDK_CORE_ACCOUNT:-}" ]]; then
  export CLOUDSDK_CORE_ACCOUNT
fi
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

# Default bucket for project-naturalpath (not Emergent-era project-prefixed names).
BUCKET="${GCS_BUCKET:-naturalpath-media}"
ZONE="${GCP_ZONE:-${GCP_REGION}-a}"
REDIS_VM="${CONTENT_REDIS_VM:-natural-path-content-redis}"
# Prefer an explicit CDN/LB base. Never default to storage.googleapis.com (PAP 403).
CDN_BASE_URL="${CDN_BASE_URL:-}"

echo ">> Project: ${GCP_PROJECT}"
echo ">> Bucket:  ${BUCKET}"
echo ">> CDN URL: ${CDN_BASE_URL:-"(unset → signed GET URLs)"}"

gcloud services enable \
  storage.googleapis.com \
  compute.googleapis.com \
  iam.googleapis.com \
  --project "${GCP_PROJECT}"

if gsutil ls -b "gs://${BUCKET}" >/dev/null 2>&1; then
  echo ">> Bucket already exists"
else
  echo ">> Creating bucket"
  gcloud storage buckets create "gs://${BUCKET}" \
    --project "${GCP_PROJECT}" \
    --location "${GCP_REGION}" \
    --uniform-bucket-level-access
fi

# Enforce Public Access Prevention — never grant allUsers:objectViewer.
gcloud storage buckets update "gs://${BUCKET}" --public-access-prevention 2>/dev/null \
  || gsutil pap set enforced "gs://${BUCKET}" 2>/dev/null \
  || echo ">> WARN: could not set PAP (set manually if bucket is new)"

# Allow Cloud Run runtime SA to create objects + IAM-sign blobs (no JSON key).
# generate_signed_url on ADC uses IAM Credentials signBlob; the SA must be able
# to act as itself (TokenCreator on the SA resource, not only project-level).
PROJECT_NUMBER="$(gcloud projects describe "${GCP_PROJECT}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo ">> Granting objectAdmin on gs://${BUCKET} to ${RUNTIME_SA}"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/storage.objectAdmin" \
  --quiet >/dev/null \
  || gsutil iam ch "serviceAccount:${RUNTIME_SA}:objectAdmin" "gs://${BUCKET}"
echo ">> Granting serviceAccountTokenCreator on ${RUNTIME_SA} (self → signBlob)"
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
  --project="${GCP_PROJECT}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --quiet >/dev/null

# Private CDN / backend-bucket fill agent (see docs/GCS_CDN_SETUP.md).
CDN_FILL_SA="service-${PROJECT_NUMBER}@https-lb.iam.gserviceaccount.com"
gsutil iam ch "serviceAccount:${CDN_FILL_SA}:objectViewer" "gs://${BUCKET}" 2>/dev/null \
  || echo ">> Note: CDN fill SA binding skipped (ok until Cloud CDN backend bucket exists)"

# Dedicated Redis for content rate-limit / feed cache (plan default: e2-small).
# Skip with SKIP_CONTENT_REDIS=1 to keep using existing REDIS_URL (Upstash/Memorystore).
if [[ "${SKIP_CONTENT_REDIS:-0}" == "1" ]]; then
  echo ">> Skipping Redis VM (SKIP_CONTENT_REDIS=1)"
else
  if gcloud compute instances describe "${REDIS_VM}" --zone "${ZONE}" --project "${GCP_PROJECT}" >/dev/null 2>&1; then
    echo ">> Redis VM ${REDIS_VM} already exists"
  else
    echo ">> Creating Redis VM ${REDIS_VM} (e2-small) in ${ZONE}"
    gcloud compute instances create "${REDIS_VM}" \
      --project "${GCP_PROJECT}" \
      --zone "${ZONE}" \
      --machine-type e2-small \
      --image-family debian-12 \
      --image-project debian-cloud \
      --tags content-redis \
      --metadata=startup-script='#!/bin/bash
set -e
apt-get update
apt-get install -y redis-server
sed -i "s/^bind .*/bind 0.0.0.0/" /etc/redis/redis.conf
sed -i "s/^protected-mode yes/protected-mode no/" /etc/redis/redis.conf
systemctl enable redis-server
systemctl restart redis-server
'
  fi
  REDIS_IP="$(gcloud compute instances describe "${REDIS_VM}" --zone "${ZONE}" --project "${GCP_PROJECT}" --format='value(networkInterfaces[0].networkIP)')"
  echo ">> Redis internal IP: ${REDIS_IP}"
  echo "   Set REDIS_CONTENT_URL=redis://${REDIS_IP}:6379/0 after wiring a Serverless VPC connector,"
  echo "   or continue using existing REDIS_URL for content cache (already supported)."
fi

echo
echo ">> Add to config.env / Cloud Run env:"
echo "   GCS_BUCKET=${BUCKET}"
if [[ -n "${CDN_BASE_URL}" ]]; then
  echo "   CDN_BASE_URL=${CDN_BASE_URL}"
else
  echo "   CDN_BASE_URL=  # leave unset → API uses signed GET URLs (PAP-safe)"
fi
echo
echo ">> Done. Redeploy API with 02-deploy-backend.sh so signed uploads work."
echo ">> Do not set CDN_BASE_URL until an HTTPS CDN hostname is ready (docs/GCS_CDN_SETUP.md)."
