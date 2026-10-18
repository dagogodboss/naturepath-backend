# Entra admin consent — ready to send (Phase 6 unblock)

**Canonical copy:** [`docs/plans/ops-entra-consent-request.md`](../../../docs/plans/ops-entra-consent-request.md) at workspace root (keep in sync).

**Date:** 2026-10-18  
**Status:** Draft — **please send this** (not auto-sent; no approved Jonathan ops channel in repo).

## Recipient (from repo docs only)

| Contact | Source | Notes |
|---------|--------|--------|
| **Jonathan Moore** | `docs/plans/multi-resource-scheduling.md`, `docs/plans/ops-oauth-prod-cutover.md` (Entra admin / Global Administrator) | Named as clinic owner; **no personal M365 email** listed in repo |
| `nmoore@thenaturalpathla.com` | OAuth / Nichole mailbox tables in `ops-oauth-prod-cutover.md` | Practitioner calendar; not Entra admin, but may know who can Accept |
| `Clients@thenaturalpathla.com` | Phase 0 locked Salt Outlook source | Target **mailbox** for app-only sync — not the consent approver |
| `admin@gcp.thenaturalpathla.com` | GCP / Firebase support email in plan docs | Technical GCP account — use only if that is your usual Jonathan/ops inbox |

**Suggested To:** Jonathan Moore (Microsoft 365 **Global Administrator** for The Natural Path LA tenant). If you do not have his direct address, forward from Nichole or your usual clinic IT contact.

---

## Subject

`Action needed (~2 min): Microsoft admin consent for Natural Path scheduling (Salt room calendar)`

---

## Body

Hi Jonathan,

We’re unblocking **Phase 6** multi-resource scheduling for The Natural Path. Staging is ready on our side; the remaining step needs a **Microsoft Entra Global Administrator** to grant **admin consent** for one application permission.

**Why this matters**

- **Salt room** availability must read busy time from **`Clients@thenaturalpathla.com`** only (locked in Phase 0 — not Nichole’s calendar for Salt).
- **Discovery vs Salt** must stay separate in the booking engine; we prove that with real Outlook busy after sync.
- We use **app-only** Microsoft Graph access (**Calendars.Read**, application permission) so the Salt calendar can sync without repeated device-code sign-in for the shared mailbox.

**What we need you to do**

1. Open this **admin consent URL** (tenant + our app) and click **Accept**:

   https://login.microsoftonline.com/bbefcd77-2f78-4240-85f3-41dcf671c9bf/adminconsent?client_id=daf7c7db-7a14-4b8b-8209-58b168d34683

2. If the permission is not listed yet, in [Azure Portal](https://portal.azure.com): **Microsoft Entra ID** → **App registrations** → app id **`daf7c7db-7a14-4b8b-8209-58b168d34683`** → **API permissions** → **Add permission** → **Microsoft Graph** → **Application permissions** → **Calendars.Read** → **Add permissions**, then **Grant admin consent for {tenant}**.

(Optional later: restrict the app to `Clients@thenaturalpathla.com` and `nmoore@thenaturalpathla.com` via Exchange application access policy — see `docs/plans/ops-oauth-prod-cutover.md`.)

**What happens after you Accept**

- Our team runs **`phase6_post_consent_cutover`** on **staging** first (probes Graph, flips connections to app-only sync, runs Discovery≠Salt prove).
- **Production** stays unchanged: **`MULTI_RESOURCE_SCHEDULING` remains off** until staging prove passes and we have your sign-off.

Reply when done (or if Azure shows an error) and we’ll re-probe immediately.

Thanks,  
[Your name / Nature Path engineering]

---

## Internal reference (do not paste secrets)

- App (client) id: `daf7c7db-7a14-4b8b-8209-58b168d34683`
- Tenant id: `bbefcd77-2f78-4240-85f3-41dcf671c9bf`
- Last probe: exit **10** / 403 on Clients@ `calendarView` — `qa/reports/multi-resource-proof/post-consent-cutover-staging-20261018-vpc.json`
- Runbook: `docs/plans/ops-oauth-prod-cutover.md` § Application permissions
