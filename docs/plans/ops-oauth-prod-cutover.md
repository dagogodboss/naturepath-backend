# Multi-resource production cutover — OAuth + flag (ops)

**Canonical workspace copy:** `/Users/mac/naturepath/docs/plans/ops-oauth-prod-cutover.md` (keep in sync when editing).

**GCP project:** `project-990664b0-1bae-4746-88d` only. **Do not change DNS.**

## HARD GATE — Jonathan / Entra Accept deferred (2026-10-19)

**Do not send the adminconsent link to Jonathan (or any staff) until [naturepath#9](https://github.com/dagogodboss/naturepath/issues/9) slices 1–4 are complete** (A1–A6 done on `8b34fcf`; B1–B3 in progress; C1–C5 UI; D hardened on `5f2c512`; B4 consent/runbook). Entra Accept / Jonathan auth ask is **DEFERRED**. Cutover workflow must **not** be presented as “ready for Jonathan” yet. No Entra polls, no prod flag flip while this gate is open. See also [ops-entra-consent-request.md](./ops-entra-consent-request.md).

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

**Verdict:** There is **no** path to working Outlook→resource busy sync without a human Accept (Entra Application **Calendars.Read** admin consent). Delegated `/me` remains a theoretical alternate; Clients@ has **no** usable delegated token and legacy secrets are gone — **app-only after Entra Accept is the primary unblock** ([#8](https://github.com/dagogodboss/naturepath/issues/8)).

**Ask (Entra Global Administrator):** Accept **Calendars.Read** (Application) admin consent for app `daf7c7db-7a14-4b8b-8209-58b168d34683` / tenant `bbefcd77-2f78-4240-85f3-41dcf671c9bf`.

Admin consent URL:

`https://login.microsoftonline.com/bbefcd77-2f78-4240-85f3-41dcf671c9bf/adminconsent?client_id=daf7c7db-7a14-4b8b-8209-58b168d34683`

Outreach draft: [ops-entra-consent-request.md](./ops-entra-consent-request.md). Tracking: [naturepath#8](https://github.com/dagogodboss/naturepath/issues/8).

**Do not** start 15m/3h poll loops. Re-probe only after admin reports Accept (or optional single dry-run).

## Mailbox least-privilege (required before cutover)

App-only `Calendars.Read` must **not** be left as unrestricted tenant-wide calendar access.

| Requirement | Status |
|-------------|--------|
| Intended mailboxes only: `Clients@thenaturalpathla.com`, `nmoore@thenaturalpathla.com` | **Required** via Exchange application access policy / application RBAC — see [Microsoft docs](https://learn.microsoft.com/en-us/Exchange/permissions-exo/application-rbac) |
| Verify allowed mailboxes succeed AND excluded mailboxes fail Graph `calendarView` | **Required** before enabling prod flag |
| Document retained Graph fields / retention | Required (subjects currently selected — minimise per [#9](https://github.com/dagogodboss/naturepath/issues/9) B4) |

This is **not** “optional later” and is **not** already done. Adding a scoped RBAC grant does not by itself narrow an existing unscoped grant — remove or replace broad grants deliberately.

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

Dry-run still exits **10** when Entra consent is missing (Graph 403 / empty `roles`).

### Staging cutover order (script)

1. Validate Graph app-only probes for both mailboxes  
2. Ensure staging env (`MULTI_RESOURCE_SCHEDULING`, `OUTLOOK_APP_ONLY_SYNC_ENABLED`)  
3. Patch connections → `auth_mode=application`  
4. Sync both calendars  
5. Assert non-empty / real Outlook busy (or explicit `--allow-empty-busy`)  
6. Discovery≠Salt prove with **`--real-busy-only`** (no synthetic inject)

### Prod cutover order (script — after staging real prove + Jonathan sign-off)

**Never** enable the flag first. Order in `run_prod_phase`:

1. Validate prod gate flags (`--prod --i-understand-prod`) + connection rows  
2. Patch `auth_mode=application`  
3. Sync both mailboxes  
4. **Real Outlook** Discovery≠Salt prove  
5. Enable `MULTI_RESOURCE_SCHEDULING=true` on `natural-path-api` **last**  
6. On prove/sync failure: **do not** enable the flag; if a later verification fails after enable, roll back with `MULTI_RESOURCE_SCHEDULING=false` (or unset) immediately — **do not** delete `resources` / `resource_busy_intervals`

```bash
# on naturepath-data-1 inside ~/np-oauth/backend — only after staging P1–P8 real prove + sign-off
PYTHONPATH=backend python3 -m scripts.phase6_post_consent_cutover \
  --prod --i-understand-prod \
  --report-dir ../qa/reports/multi-resource-proof
```

**Do not** enable prod `MULTI_RESOURCE_SCHEDULING` until that gate passes. Synthetic staging artifacts are **not** sufficient.

## Phase 0 visibility (B3)

Prefer staff **shared Clients@ calendar** alongside Nichole ([#9 comment](https://github.com/dagogodboss/naturepath/issues/9#issuecomment-6262033979)). Do not duplicate Salt onto Nichole as capacity; mystery busy stays blocked.

## Flags today

| Service | `MULTI_RESOURCE_SCHEDULING` | `OUTLOOK_APP_ONLY_SYNC_ENABLED` | Notes |
|---------|----------------------------|----------------------------------|-------|
| `natural-path-api-staging` | **true** | absent / false until cutover | Rev `00006-2kf` has `MICROSOFT_CLIENT_ID`/`TENANT_ID`; cutover sets app-only=true |
| `natural-path-api` (prod traffic) | **unset** on `natural-path-api-00021-hv8` | unset | Keep off |

## Connection IDs (reference)

| Env | Clients@ | Nichole |
|-----|----------|---------|
| Staging | `9fba4c5f-38e7-4a69-888c-3f84627ed3ea` | `0ae88711-4e79-42b4-831f-141705d6ca9c` |
| Prod | `a5d43af5-0f20-4871-8d79-5af254b1e936` | `0ae88711-4e79-42b4-831f-141705d6ca9c` |

## Rollback

- Staging or prod: set `MULTI_RESOURCE_SCHEDULING=false` (or unset) → legacy booking path.  
- Do **not** delete multi-resource collections on rollback.  
- App-only sync can stay enabled while the booking flag is off.
