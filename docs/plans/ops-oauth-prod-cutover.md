# Multi-resource production cutover — OAuth + flag (ops)

**Canonical workspace copy:** `/Users/mac/naturepath/docs/plans/ops-oauth-prod-cutover.md` (keep in sync when editing).

**GCP project:** `project-990664b0-1bae-4746-88d` only. **Do not change DNS.**

## HARD GATE — Accept package READY TO SEND (2026-10-19)

Engineering blockers for [#9](https://github.com/dagogodboss/naturepath/issues/9) are **cleared** (slices 1–4 + B1 race `8d89d6a`; staging `00007-wds`; synthetic prove green). Graph dry-run still **exit 10** until Entra Accept.

**Package status:** [ops-entra-consent-request.md](./ops-entra-consent-request.md) is **READY TO SEND**. Human ops sends when ready. **Agents must not** email, Slack, or message Jonathan unless an already-approved send path the user previously used is available; must not run Entra poll loops; must not flip prod `MULTI_RESOURCE_SCHEDULING`.

Phase 6 still needs: (1) human Accept + mailbox least-privilege, (2) staging real Outlook prove, (3) Jonathan sign-off before prod flag. See [naturepath#8](https://github.com/dagogodboss/naturepath/issues/8).

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

**Ask (Entra Global Administrator):** Accept **Calendars.Read** (Application) admin consent for app `daf7c7db-7a14-4b8b-8209-58b168d34683` / tenant `bbefcd77-2f78-4240-85f3-41dcf671c9bf`, **and** mailbox least-privilege (below) the same day.

Admin consent URL:

`https://login.microsoftonline.com/bbefcd77-2f78-4240-85f3-41dcf671c9bf/adminconsent?client_id=daf7c7db-7a14-4b8b-8209-58b168d34683`

Outreach draft (human send only): [ops-entra-consent-request.md](./ops-entra-consent-request.md). Tracking: [naturepath#8](https://github.com/dagogodboss/naturepath/issues/8).

**Do not** start 15m/3h poll loops. Re-probe only after admin reports Accept (or optional single dry-run).

## Mailbox least-privilege (REQUIRED before cutover)

App-only `Calendars.Read` must **not** be left as unrestricted tenant-wide calendar access. This is a **hard cutover prerequisite**, not “optional later,” and is **not** already done.

| Requirement | Status |
|-------------|--------|
| Intended mailboxes only: `Clients@thenaturalpathla.com`, `nmoore@thenaturalpathla.com` | **REQUIRED** via Exchange application access policy / application RBAC — see [limit mailbox access](https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access) and [application RBAC](https://learn.microsoft.com/en-us/Exchange/permissions-exo/application-rbac) |
| Verify allowed mailboxes succeed **AND** excluded mailboxes fail Graph `calendarView` | **REQUIRED** before enabling prod flag (and before treating staging sync as cutover-ready) |
| Document retained Graph fields / retention | Done below (§ Graph field retention) |

Permissions are **additive**: adding a scoped RBAC grant does not by itself narrow an existing unscoped grant — remove or replace broad grants deliberately.

### Cutover checklist (mailbox scope)

1. After Accept, confirm JWT `roles` includes `Calendars.Read`.
2. Apply Exchange application access policy / RBAC so the app can reach **only** Clients@ + Nichole.
3. Probe: Clients@ and Nichole `calendarView` → **200**; at least one other tenant mailbox → **403**/denied.
4. Only then run staging `phase6_post_consent_cutover` (full, not dry-run).

## Calendars.Read vs Calendars.ReadBasic

| Permission | Role in this project |
|------------|----------------------|
| **`Calendars.Read` (Application)** | **Requested for cutover** on app `daf7c7db-…` — matches [naturepath#8](https://github.com/dagogodboss/naturepath/issues/8), adminconsent URL, and consent draft. |
| `Calendars.ReadBasic` | Graph documents this as least-privilege for some `calendarView` reads. We **do not** claim it sufficient for our sync until a live staging probe proves Application `Calendars.ReadBasic` returns **`categories`** (required for Salt/Discovery classification) plus our other `$select` fields under mailbox-restricted app-only auth. |

**Why we stay on `Calendars.Read` for the ask:** capacity classification keys off Outlook **category names**. Until ReadBasic is verified end-to-end with our `$select` and Exchange restriction, requesting Basic would risk Accept → sync that cannot classify. Downgrade to ReadBasic is a **post-Accept follow-up**, not a consent-draft change.

Delegated `Calendars.Read` / device-code remains a theoretical fallback only; Clients@ has no usable refresh token and legacy secrets are gone — app-only after Accept is primary.

## Graph field retention / data minimisation (B4)

`MicrosoftGraphClient.list_calendar_view` `$select`:

`id,start,end,showAs,isCancelled,categories,subject`

| Field | Used for | Retained where | Notes |
|-------|----------|----------------|-------|
| `id` | Dedupe / event linkage | `resource_busy_intervals.event_id`, review queue | Required |
| `start` / `end` | Busy intervals | Busy rows only (times) | Required for capacity |
| `showAs` / `isCancelled` | Busy vs free / skip | Busy rows | Required |
| `categories` | Salt vs Discovery vs unmapped | Busy `category_name`; review payload | **Never** use subject for capacity |
| `subject` | Admin review preview only | `review_queue` payload (`subject`) when unmapped/review | **Not** written to busy intervals; **not** used for booking capacity |

**Removed from `$select`:** `lastModifiedDateTime` — Graph `calendarView` docs state `createdDateTime` / `lastModifiedDateTime` **do not support `$select`**; we do not need them for sync. Do not re-add.

**Visibility:** review-queue subject is admin-facing only. Customer booking APIs do not expose Outlook subjects.

**Retention / revocation:** busy intervals are replaced on successful sync generations; review items remain until ops closes/deletes them. On consent revocation or mailbox-policy deny: stop sync, leave prior complete snapshot per Slice 2 rules; purge review payloads / busy rows only under explicit ops wipe (do not auto-delete on flag off).

**Minimisation stance:** do not add `body`, attendees, attachments, or location to `$select`. Subject stays only while review UX needs a human-readable hint for unmapped events; capacity remains category-only.

## One-button cutover (after Accept + mailbox scope)

**Preferred (zero-spam):** after Accept + least-privilege verified, comment on [naturepath#8](https://github.com/dagogodboss/naturepath/issues/8) then run:

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

1. Validate Graph app-only probes for both mailboxes (after least-privilege)  
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
