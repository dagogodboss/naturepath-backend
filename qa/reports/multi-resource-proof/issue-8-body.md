## Summary

Phase 6 multi-resource scheduling is blocked until a **Microsoft Entra Global Administrator** grants **admin consent** for **Microsoft Graph → Application permission → Calendars.Read** on our scheduling app.

Runbooks: `docs/plans/ops-entra-consent-request.md`, `docs/plans/ops-oauth-prod-cutover.md` (also mirrored under `naturepath-backend` docs).

## Status (2026-10-19)

**READY TO SEND.** Engineering blockers cleared (#9 slices 1–4, B1 race `8d89d6a`, staging `natural-path-api-staging-00007-wds`, synthetic prove green). Graph dry-run still exit **10**. Human sends Accept package when ready. **Agents do not email/Slack Jonathan.** Prod `MULTI_RESOURCE_SCHEDULING` stays off.

## Ask (human — Entra admin)

**Accept Calendars.Read (Application) admin consent** for app `daf7c7db-7a14-4b8b-8209-58b168d34683` in tenant `bbefcd77-2f78-4240-85f3-41dcf671c9bf`, **and** mailbox least-privilege (Clients@ + Nichole only) the same day, then comment here so engineering runs the one-command staging cutover.

Admin consent URL:

https://login.microsoftonline.com/bbefcd77-2f78-4240-85f3-41dcf671c9bf/adminconsent?client_id=daf7c7db-7a14-4b8b-8209-58b168d34683

Copy-paste subject/body: `docs/plans/ops-entra-consent-request.md`.

## Why this is needed

- **Salt room** availability must read busy time from **`Clients@thenaturalpathla.com`** only (Phase 0 lock — not Nichole’s calendar for Salt).
- **Discovery vs Salt** must stay separate in the booking engine; we prove that with real Outlook busy after sync.
- **App-only** Graph access (**Calendars.Read**, application permission) is required so **Clients@** and **Nichole** (`nmoore@thenaturalpathla.com`) calendars can sync without repeated device-code sign-in for the shared mailbox.
- Delegated refresh-token sync is not viable for Clients@ (`oauth_pending`, no refresh token) and Nichole refresh returns **400** until re-consent; app-only is the preferred cutover path once consent lands.

## App registration

| Field | Value |
|-------|--------|
| **Application (client) ID** | `daf7c7db-7a14-4b8b-8209-58b168d34683` |
| **Directory (tenant) ID** | `bbefcd77-2f78-4240-85f3-41dcf671c9bf` |

## Azure Portal steps (Jonathan / Global Administrator)

1. [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID** → **App registrations** → app **`daf7c7db-7a14-4b8b-8209-58b168d34683`**.
2. **API permissions** → **Add a permission** → **Microsoft Graph** → **Application permissions** (not Delegated) → **Calendars.Read** → **Add permissions**.
3. **Grant admin consent for {tenant}** (button on the same blade).
4. **REQUIRED same day (not optional):** [Exchange application access policy](https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access) / application RBAC to restrict the app to `Clients@thenaturalpathla.com` and `nmoore@thenaturalpathla.com` only. Verify allowed mailboxes succeed and others are denied before cutover. See B4 / `ops-oauth-prod-cutover.md`.

## After Accept — staging cutover paths

**Do not wait for polling.** After Accept, prefer in this order:

```bash
# 1) Local Secret Manager (no IAP) — Graph dry-run anytime; full cutover needs VPC Mongo
./scripts/phase6_post_consent_cutover_local.sh --dry-run
# on naturepath-data-1 (or VPC host): omit --dry-run for staging cutover
```

```bash
# 2) GitHub Actions (WIF → IAP → VM; SA keys blocked by org policy)
gh workflow run phase6-post-consent-cutover.yml --repo dagogodboss/naturepath-backend
```

```bash
# 3) Local IAP when compute/TLS works
./scripts/phase6_post_consent_cutover_remote.sh --sync-code
```

VM path: `~/np-oauth/backend` on **naturepath-data-1**. **No DNS / Route53.**

**Do not** enable prod `MULTI_RESOURCE_SCHEDULING` until staging prove passes and ops sign-off. Prod cutover requires explicit `--prod --i-understand-prod` only after staging P1–P8 pass.

## Probe failure evidence (keep open)

| Item | State |
|------|--------|
| Host | `naturepath-data-1` (VPC) |
| Time | **2026-10-19T09:14:16Z** (`generated_at`; fresh single dry-run via nohup) |
| Command | `phase6_post_consent_cutover --dry-run` |
| Exit | **10** (`entra_admin_consent_required`) |
| JWT `roles` | **empty** (no `Calendars.Read`) |
| Clients@ `calendarView` | **403** |
| Token acquire | OK — `client_id`/`appid` `daf7c7db…`, tenant `bbefcd77…` |
| Artifact | `qa/reports/multi-resource-proof/post-consent-cutover-staging-20261019.json` (+ `…T0914Z-vpc.json`) |
| Staging cutover | **not run** |
| Prod `MULTI_RESOURCE_SCHEDULING` | **unset** — **do not enable** |
| Monitoring | **No** poll loops — wait for admin Accept, then one cutover command |

## Pre-consent checklist (engineering)

| Item | Status |
|------|--------|
| Staging `MULTI_RESOURCE_SCHEDULING=true` | Done (`natural-path-api-staging-00007-wds`) |
| Staging Discovery≠Salt (synthetic / booking dual-write) | Green |
| B1 overlapping-sync race | Fixed (`8d89d6a`) |
| #9 slices 1–4 | Done |
| Cutover script ready | Done (`scripts/phase6_post_consent_cutover`) |
| App-only Graph / real Outlook busy prove | **Blocked on Entra** |

## Human outreach

**READY TO SEND** email draft: `docs/plans/ops-entra-consent-request.md`.

**Assignee / action:** Ops human sends to Entra Global Administrator — click **Accept** on admin consent URL (or grant consent in portal) + mailbox least-privilege, then comment here so engineering re-runs cutover.
