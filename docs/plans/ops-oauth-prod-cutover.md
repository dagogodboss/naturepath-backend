# Multi-resource production cutover — OAuth + flag (ops)

**Canonical workspace copy:** `/Users/mac/naturepath/docs/plans/ops-oauth-prod-cutover.md` (keep in sync when editing).

**GCP project:** `project-990664b0-1bae-4746-88d` only. **Do not change DNS.**

## Blocker (2026-10-18) — no silent unblock path

| Check | Result |
|-------|--------|
| Fresh inventory | `2026-10-18T23:07:30Z` on **naturepath-data-1** |
| App-only JWT `roles` | **empty** (no `Calendars.Read`) — `client_credentials` OK for `daf7c7db…` |
| Clients@ `calendarView` | **403** `ErrorAccessDenied` |
| Clients@ refresh token | **none** (staging + prod `oauth_pending`) |
| Nichole refresh token | present but bound to **legacy app** `c6ad9756…`; redeem with current secret → **401** `AADSTS7000215` |
| Legacy app secret | **not** in Secret Manager — cannot revive delegated tokens |
| Entra CLI / admin consent grant | **az not installed**; this GCP account cannot Grant admin consent |
| Staging cutover / prod flag | **not run** |
| Artifact | `qa/reports/multi-resource-proof/graph-unblock-investigation-20261018T2307Z.json` |

**Verdict:** There is **no** path to working Outlook→resource busy sync without a human Accept (Entra Application **Calendars.Read** admin consent, or mailbox device-code/browser consent). Category sync already supports delegated `/me` tokens; Clients@ still needs app-only or a fresh Clients@ (or shared) token we do not have.

**Ask (Entra Global Administrator):** Accept **Calendars.Read** (Application) admin consent for app `daf7c7db-7a14-4b8b-8209-58b168d34683` / tenant `bbefcd77-2f78-4240-85f3-41dcf671c9bf`.

Admin consent URL:

`https://login.microsoftonline.com/bbefcd77-2f78-4240-85f3-41dcf671c9bf/adminconsent?client_id=daf7c7db-7a14-4b8b-8209-58b168d34683`

Outreach draft: [ops-entra-consent-request.md](./ops-entra-consent-request.md). Tracking: [naturepath#8](https://github.com/dagogodboss/naturepath/issues/8).

**Do not** start 15m/3h poll loops. Re-probe only after admin reports Accept (or optional single dry-run).

## One-button cutover (after Accept)

**Preferred (zero-spam):** after Accept, comment on [naturepath#8](https://github.com/dagogodboss/naturepath/issues/8) then run:

```bash
# GitHub Actions (needs repo secret GCP_SA_KEY with IAP SSH to naturepath-data-1)
gh workflow run phase6-post-consent-cutover.yml --repo dagogodboss/naturepath-backend
# optional probe-only:
gh workflow run phase6-post-consent-cutover.yml --repo dagogodboss/naturepath-backend -f mode=dry-run
```

**Local / ops laptop** (same IAP path; no GH secret required if your `gcloud` user can SSH):

```bash
cd /path/to/naturepath-backend
./scripts/phase6_post_consent_cutover_remote.sh --sync-code
# or probe only:
./scripts/phase6_post_consent_cutover_remote.sh --dry-run
```

VM checkout path used by the remote runner: `~/np-oauth/backend` on **naturepath-data-1**.

**Prod** (optional, only after staging P1–P8 + Jonathan sign-off — not wired into the workflow button):

```bash
# on naturepath-data-1 inside ~/np-oauth/backend
PYTHONPATH=backend python3 -m scripts.phase6_post_consent_cutover \
  --prod --i-understand-prod \
  --report-dir ../qa/reports/multi-resource-proof
```

**Do not** enable prod `MULTI_RESOURCE_SCHEDULING` until that gate passes.

## Flags today

| Service | `MULTI_RESOURCE_SCHEDULING` | `OUTLOOK_APP_ONLY_SYNC_ENABLED` | Notes |
|---------|----------------------------|----------------------------------|-------|
| `natural-path-api-staging` | **true** | absent / false until cutover | Rev `00006-2kf` has `MICROSOFT_CLIENT_ID`/`TENANT_ID`; cutover sets app-only=true |
| `natural-path-api` (prod traffic) | **unset** on `natural-path-api-00021-hv8` | unset | Keep off |

See root doc for device-code alternate, connection IDs, and rollback.
