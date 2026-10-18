# Multi-resource production cutover — OAuth + flag (ops)

**Canonical copy:** [`docs/plans/ops-oauth-prod-cutover.md`](../../../docs/plans/ops-oauth-prod-cutover.md) at repo root (keep in sync).

See root file for device-code steps, connection IDs, deploy flags, and prove commands.

**Human outreach:** Ready-to-send admin consent email → [ops-entra-consent-request.md](./ops-entra-consent-request.md) (**please send** to Jonathan / Entra Global Administrator).

**After Entra admin consent:** run `python3 -m scripts.phase6_post_consent_cutover` (see root doc § Application permissions).
