#!/usr/bin/env bash
# Local / Cloud Shell cutover path via Secret Manager — no IAP SSH required.
#
# Use when compute/IAP is broken on the laptop, or for Graph dry-run probes.
# Full staging cutover (Mongo patch/sync/prove) needs VPC reachability to
# mongo (10.40.0.x). From a VPC-less laptop: --dry-run only. From the data VM
# or any host that can reach Mongo + gcloud: omit --dry-run.
#
# Usage (from naturepath-backend root):
#   ./scripts/phase6_post_consent_cutover_local.sh --dry-run
#   ./scripts/phase6_post_consent_cutover_local.sh              # staging cutover
#
# Prefer GitHub Actions (Workload Identity → IAP → VM) when available:
#   gh workflow run phase6-post-consent-cutover.yml --repo dagogodboss/naturepath-backend
#
# Does NOT enable prod MULTI_RESOURCE_SCHEDULING unless you pass --prod.

set -euo pipefail

PROJECT="${GCP_PROJECT:-project-990664b0-1bae-4746-88d}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

if [[ ! -f scripts/phase6_post_consent_cutover.py ]]; then
  echo "Missing scripts/phase6_post_consent_cutover.py (run from naturepath-backend root)" >&2
  exit 2
fi

echo "Loading secrets from Secret Manager (project=${PROJECT}) ..."
export MICROSOFT_CLIENT_ID="${MICROSOFT_CLIENT_ID:-daf7c7db-7a14-4b8b-8209-58b168d34683}"
export MICROSOFT_TENANT_ID="${MICROSOFT_TENANT_ID:-bbefcd77-2f78-4240-85f3-41dcf671c9bf}"
export MICROSOFT_CLIENT_SECRET="${MICROSOFT_CLIENT_SECRET:-$(gcloud secrets versions access latest --secret=microsoft-client-secret --project="${PROJECT}")}"
export MONGO_URL="${MONGO_URL:-$(gcloud secrets versions access latest --secret=mongo-url --project="${PROJECT}")}"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(gcloud secrets versions access latest --secret=jwt-secret --project="${PROJECT}")}"
export DB_NAME="${DB_NAME:-natural_path_staging}"
export MULTI_RESOURCE_SCHEDULING="${MULTI_RESOURCE_SCHEDULING:-true}"
export GCP_PROJECT="${PROJECT}"

# Prefer in-repo qa/ (naturepath-backend checkout); override with PHASE6_REPORT_DIR.
REPORT_DIR="${PHASE6_REPORT_DIR:-${ROOT}/qa/reports/multi-resource-proof}"
mkdir -p "${REPORT_DIR}"

ARGS=("$@")
# Default report-dir if caller did not pass one
has_report=0
for a in "${ARGS[@]+"${ARGS[@]}"}"; do
  if [[ "${a}" == "--report-dir" || "${a}" == --report-dir=* ]]; then
    has_report=1
    break
  fi
done
if [[ "${has_report}" -eq 0 ]]; then
  ARGS+=(--report-dir "${REPORT_DIR}")
fi

VENV="${ROOT}/.venv"
if [[ -x "${VENV}/bin/python" ]]; then
  PY="${VENV}/bin/python"
elif [[ -x "${ROOT}/../.venv/bin/python" ]]; then
  PY="${ROOT}/../.venv/bin/python"
else
  PY=python3
fi

echo "Running phase6_post_consent_cutover via local Secret Manager path (${PY}) ..."
set +e
PYTHONPATH=backend "${PY}" -m scripts.phase6_post_consent_cutover "${ARGS[@]}"
ec=$?
set -e
echo "phase6_post_consent_cutover exit=${ec}"
exit "${ec}"
