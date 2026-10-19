# Entra admin consent — DEFERRED (do not send)

**Canonical copy:** keep in sync with workspace `/Users/mac/naturepath/docs/plans/ops-entra-consent-request.md`.

**Date:** 2026-10-18 (reconciled 2026-10-19)  
**Status:** Draft — **DO NOT SEND.** Microsoft / Jonathan Accept outreach remains **DEFERRED / UNSENT** until the user explicitly says otherwise. **Automation / agents must not email, Slack, or message Jonathan (or any staff).**  
**Primary unblock for Phase 6 (later):** Application **`Calendars.Read`** admin consent for app `daf7c7db-7a14-4b8b-8209-58b168d34683` ([naturepath#8](https://github.com/dagogodboss/naturepath/issues/8)).

## Engineering status — do not treat as “ready to send”

[naturepath#9](https://github.com/dagogodboss/naturepath/issues/9) slices 1–3 and most of B4 docs/code are in tree, but **B1 concurrent snapshot cleanup** had a follow-up race (overlapping syncs could wipe each other’s busy rows → fresh-but-empty). Engineering is closing that concurrency gate; **do not present cutover or this draft as ready for Jonathan.**

| Slice | Scope | Status |
|-------|--------|--------|
| 1 | A1–A6 booking integrity | Done — backend `8b34fcf` |
| 2 | B1–B3 Outlook / snapshots | Done with B1 race follow-up in progress / fixed on head |
| 3 | C1–C5 admin/customer UI | Done — frontend `307fde3`, backend `c997ea9` |
| 4 | D + B4 least-privilege consent/runbook | B4 docs/select in progress; **Accept stays deferred** |

Until the user explicitly authorises outreach: no Jonathan message, no Entra Accept ask, no Entra polls, no prod `MULTI_RESOURCE_SCHEDULING` flag.

Tracking: [naturepath#8](https://github.com/dagogodboss/naturepath/issues/8). Runbook: [ops-oauth-prod-cutover.md](./ops-oauth-prod-cutover.md).

## Recipient (from repo docs only)

| Contact | Source | Notes |
|---------|--------|-------|
| **Jonathan Moore** | `docs/plans/multi-resource-scheduling.md`, `docs/plans/ops-oauth-prod-cutover.md` (Entra admin / Global Administrator) | Named as clinic owner; **no personal M365 email** listed in repo |
| `nmoore@thenaturalpathla.com` | OAuth / Nichole mailbox tables in `ops-oauth-prod-cutover.md` | Practitioner calendar; not Entra admin, but may know who can Accept |
| `Clients@thenaturalpathla.com` | Phase 0 locked Salt Outlook source | Target **mailbox** for app-only sync — not the consent approver |
| `admin@gcp.thenaturalpathla.com` | GCP / Firebase support email in plan docs | Technical GCP account — use only if that is your usual Jonathan/ops inbox |

**Suggested To (when user authorises send later):** Jonathan Moore (Microsoft 365 **Global Administrator** for The Natural Path LA tenant). If you do not have his direct address, forward from Nichole or your usual clinic IT contact.

---

## Subject

`Action needed (~2 min): Microsoft admin consent for Natural Path scheduling (Salt room calendar)`

---

## Body

Hi Jonathan,

We’re unblocking **Phase 6** multi-resource scheduling for The Natural Path. Staging is ready on our side; the remaining step needs a **Microsoft Entra Global Administrator** to grant **admin consent** for one **application** permission on our scheduling app.

**Why this matters**

- **Salt room** availability must read busy time from **`Clients@thenaturalpathla.com`** only (locked in Phase 0 — not Nichole’s calendar for Salt).
- **Nichole’s mailbox** (`nmoore@thenaturalpathla.com`) remains authoritative for Discovery/consultations. Staff should prefer viewing the **shared Clients@ calendar** alongside Nichole’s so Salt is visible without consuming Nichole’s bookable capacity.
- **Discovery vs Salt** must stay separate in the booking engine; we prove that with **real Outlook busy** after sync (synthetic engine tests alone are not production proof).
- We use **app-only** Microsoft Graph access — Application permission **`Calendars.Read`** on app **`daf7c7db-7a14-4b8b-8209-58b168d34683`** — so both calendars can sync without relying on broken legacy delegated tokens.

**What we need you to do**

1. Open this **admin consent URL** (tenant + our app) and click **Accept**:

   https://login.microsoftonline.com/bbefcd77-2f78-4240-85f3-41dcf671c9bf/adminconsent?client_id=daf7c7db-7a14-4b8b-8209-58b168d34683

2. If the permission is not listed yet, in [Azure Portal](https://portal.azure.com): **Microsoft Entra ID** → **App registrations** → app id **`daf7c7db-7a14-4b8b-8209-58b168d34683`** → **API permissions** → **Add permission** → **Microsoft Graph** → **Application permissions** (not Delegated) → **Calendars.Read** → **Add permissions**, then **Grant admin consent for {tenant}**.

3. **Same day — REQUIRED before any cutover (not optional):** restrict the application so it can only access these two mailboxes — **`Clients@thenaturalpathla.com`** and **`nmoore@thenaturalpathla.com`** — via Exchange **application access policy** / application RBAC ([Microsoft docs](https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access)). Do **not** leave tenant-wide calendar access open. We will verify allowed mailboxes succeed and others are denied before any production flag flip. Details: `docs/plans/ops-oauth-prod-cutover.md` § Mailbox least-privilege.

**What happens after you Accept**

- Our team runs **`phase6_post_consent_cutover`** on **staging** first (probes Graph, flips connections to app-only sync, runs Discovery≠Salt prove against **real Outlook busy**).
- **Production** stays unchanged: **`MULTI_RESOURCE_SCHEDULING` remains off** until staging real prove passes and we have your sign-off.

Reply when done (or if Azure shows an error) and we’ll re-probe immediately (no automatic poll loops).

Thanks,  
[Your name / Nature Path engineering]

---

## Internal reference (do not paste secrets)

- App (client) id: `daf7c7db-7a14-4b8b-8209-58b168d34683`
- Tenant id: `bbefcd77-2f78-4240-85f3-41dcf671c9bf`
- Permission to Accept: **Microsoft Graph → Application → `Calendars.Read`** (app-only). See cutover runbook § Calendars.Read vs ReadBasic — we are **not** requesting `Calendars.ReadBasic` for this cutover.
- Last probe (`2026-10-18`): exit **10** / JWT `roles` empty / 403 on Clients@ `calendarView` — `qa/reports/multi-resource-proof/post-consent-cutover-staging-20261018.json` (also VPC twin `…-vpc.json`)
- Tracking issue: https://github.com/dagogodboss/naturepath/issues/8
- Consistency / integrity follow-ups: https://github.com/dagogodboss/naturepath/issues/9
- Runbook: `docs/plans/ops-oauth-prod-cutover.md`
- **Ask (when user authorises):** Accept **Calendars.Read** (Application) admin consent **and** mailbox least-privilege scope (Clients@ + Nichole only) — then engineering runs one staging cutover command (no DNS)
- **Agent policy:** do not email/Slack/message Jonathan; draft stays **UNSENT** until user says otherwise
