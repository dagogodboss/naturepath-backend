#!/usr/bin/env bash
# Shared helper: after gcloud run deploy, send 100% traffic to the latest ready revision.
#
# Why: once a service has pinned traffic (specific revisionName, or a prior
# --no-traffic deploy), later `gcloud run deploy` creates a new revision but
# leaves traffic on the old one until an explicit update-traffic. Setting
# latestRevision=true via --to-latest makes subsequent deploys auto-receive traffic.
#
# Usage (from a deploy script that has GCP_PROJECT + GCP_REGION set):
#   # shellcheck source=/dev/null
#   source "$(dirname "${BASH_SOURCE[0]}")/_route_traffic_to_latest.sh"
#   route_traffic_to_latest "${API_SERVICE}"
#
# Optional: CLOUD_RUN_NO_TRAFFIC=1 skips routing (canary / candidate-only deploys).

route_traffic_to_latest() {
  local service="${1:?service name required}"
  : "${GCP_PROJECT:?}"
  : "${GCP_REGION:?}"

  if [[ "${CLOUD_RUN_NO_TRAFFIC:-}" == "1" ]]; then
    echo ">> CLOUD_RUN_NO_TRAFFIC=1 — leaving traffic unchanged (new revision at 0%)"
    return 0
  fi

  echo ">> Routing 100% traffic to latest ready revision of ${service}"
  gcloud run services update-traffic "${service}" \
    --project "${GCP_PROJECT}" \
    --region "${GCP_REGION}" \
    --to-latest

  gcloud run services describe "${service}" \
    --project "${GCP_PROJECT}" \
    --region "${GCP_REGION}" \
    --format='table[box](
      status.latestReadyRevisionName,
      status.traffic.revisionName,
      status.traffic.percent,
      status.traffic.latestRevision
    )'
}
