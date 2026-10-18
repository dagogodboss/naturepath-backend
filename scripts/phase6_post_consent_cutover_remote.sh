#!/usr/bin/env bash
# One-shot: run phase6_post_consent_cutover on naturepath-data-1 via IAP SSH.
# No poll loops. Does not enable prod MULTI_RESOURCE_SCHEDULING unless you pass --prod.
#
# Usage (gcloud auth for project-990664b0-1bae-4746-88d required):
#   ./scripts/phase6_post_consent_cutover_remote.sh
#   ./scripts/phase6_post_consent_cutover_remote.sh --dry-run
#   ./scripts/phase6_post_consent_cutover_remote.sh --sync-code
#
# After Entra Accept (GitHub one-button):
#   gh workflow run phase6-post-consent-cutover.yml --repo dagogodboss/naturepath-backend

set -euo pipefail

PROJECT="${GCP_PROJECT:-project-990664b0-1bae-4746-88d}"
ZONE="${GCP_ZONE:-us-central1-a}"
INSTANCE="${GCP_INSTANCE:-naturepath-data-1}"
REMOTE_ROOT="${PHASE6_REMOTE_ROOT:-/home/admin_gcp_thenaturalpathla_com/np-oauth/backend}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_BACKEND_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SYNC_CODE=0
REMOTE_ARGS=()
for arg in "$@"; do
  if [[ "${arg}" == "--sync-code" ]]; then
    SYNC_CODE=1
  else
    REMOTE_ARGS+=("${arg}")
  fi
done

if [[ "${SYNC_CODE}" -eq 1 ]]; then
  echo "Syncing local backend + scripts → ${INSTANCE}:${REMOTE_ROOT}/ ..."
  gcloud compute ssh "${INSTANCE}" \
    --project="${PROJECT}" --zone="${ZONE}" --tunnel-through-iap \
    --command="mkdir -p '${REMOTE_ROOT}'"
  gcloud compute scp --recurse \
    --project="${PROJECT}" --zone="${ZONE}" --tunnel-through-iap \
    "${LOCAL_BACKEND_ROOT}/backend" \
    "${LOCAL_BACKEND_ROOT}/scripts" \
    "${INSTANCE}:${REMOTE_ROOT}/"
fi

ARGS_LINE=""
for a in "${REMOTE_ARGS[@]+"${REMOTE_ARGS[@]}"}"; do
  ARGS_LINE+=" $(printf '%q' "${a}")"
done

RUNNER_LOCAL="$(mktemp /tmp/phase6-cutover-runner.XXXXXX.sh)"
cleanup() { rm -f "${RUNNER_LOCAL}"; }
trap cleanup EXIT

cat >"${RUNNER_LOCAL}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
ROOT='${REMOTE_ROOT}'
PROJECT='${PROJECT}'
cd "\${ROOT}"
if [[ ! -f scripts/phase6_post_consent_cutover.py ]]; then
  echo "Missing \${ROOT}/scripts/phase6_post_consent_cutover.py — re-run with --sync-code" >&2
  exit 2
fi
export DB_NAME="\${DB_NAME:-natural_path_staging}"
export MULTI_RESOURCE_SCHEDULING="\${MULTI_RESOURCE_SCHEDULING:-true}"
export MICROSOFT_CLIENT_ID="\${MICROSOFT_CLIENT_ID:-daf7c7db-7a14-4b8b-8209-58b168d34683}"
export MICROSOFT_TENANT_ID="\${MICROSOFT_TENANT_ID:-bbefcd77-2f78-4240-85f3-41dcf671c9bf}"
export MICROSOFT_CLIENT_SECRET="\$(gcloud secrets versions access latest --secret=microsoft-client-secret --project=\${PROJECT})"
export MONGO_URL="\${MONGO_URL:-\$(gcloud secrets versions access latest --secret=mongo-url --project=\${PROJECT})}"
export JWT_SECRET_KEY="\${JWT_SECRET_KEY:-\$(gcloud secrets versions access latest --secret=jwt-secret --project=\${PROJECT})}"
VENV="\${ROOT}/../.venv"
if [[ -x "\${VENV}/bin/python" ]]; then PY="\${VENV}/bin/python"; else PY=python3; fi
mkdir -p "\${ROOT}/../qa/reports/multi-resource-proof"
set +e
PYTHONPATH=backend "\${PY}" -m scripts.phase6_post_consent_cutover \\
  --report-dir ../qa/reports/multi-resource-proof${ARGS_LINE}
ec=\$?
set -e
echo "phase6_post_consent_cutover exit=\${ec}"
exit "\${ec}"
EOF
chmod +x "${RUNNER_LOCAL}"

REMOTE_RUNNER="/tmp/phase6_post_consent_cutover_runner.sh"
gcloud compute scp \
  --project="${PROJECT}" --zone="${ZONE}" --tunnel-through-iap \
  "${RUNNER_LOCAL}" "${INSTANCE}:${REMOTE_RUNNER}"

gcloud compute ssh "${INSTANCE}" \
  --project="${PROJECT}" --zone="${ZONE}" --tunnel-through-iap \
  --command="bash '${REMOTE_RUNNER}'"
