# Multi-resource production cutover — OAuth + flag (ops)

**Date:** 2026-10-18  
**GCP project:** `project-990664b0-1bae-4746-88d` only  
**Do not change DNS.**  
**Prod API flag today:** `MULTI_RESOURCE_SCHEDULING` **unset** (revision `natural-path-api-00021-hv8`).

## Blockers (human OAuth)

| Mailbox | DB | Connection ID | Refresh token | Sync |
|---------|-----|---------------|---------------|------|
| Nichole (`nmoore@thenaturalpathla.com`) | `natural_path_staging` | `0ae88711-4e79-42b4-831f-141705d6ca9c` | present | **400** on Graph refresh (re-consent) |
| Nichole | `natural_path` (prod) | same | present | **400** after 2026-10-18 sync attempt — see `qa/reports/multi-resource-proof/prod-outlook-sync-20261018g.json` |
| Clients@thenaturalpathla.com | staging | `9fba4c5f-38e7-4a69-888c-3f84627ed3ea` | **none** (`oauth_pending`) | N/A |
| Clients@ | prod | `a5d43af5-0f20-4871-8d79-5af254b1e936` | **none** (`oauth_pending`) | N/A |

Non-interactive device-code / refresh **cannot** complete without a browser sign-in for Nichole re-consent and first-time Clients@ consent.

## Entra app (no secrets here)

- **Application (client) ID:** `daf7c7db-7a14-4b8b-8209-58b168d34683`
- **Directory (tenant) ID:** `bbefcd77-2f78-4240-85f3-41dcf671c9bf`
- **Client secret:** Secret Manager `microsoft-client-secret` (test/prod API mount)

Register **both** redirect URIs in Azure Portal → App registrations → Authentication → Web redirects:

| Environment | Redirect URI |
|-------------|----------------|
| **Staging** | `https://natural-path-api-staging-qxje535rja-uc.a.run.app/api/practitioners/outlook/callback` |
| **Production** | `https://natural-path-api-qxje535rja-uc.a.run.app/api/practitioners/outlook/callback` |

Legacy hostname `natural-path-api-a3idqol5ra-uc.a.run.app` may still appear in old docs; Cloud Run **current** URLs above match live services (2026-10-18).

## OAuth flow (practitioner browser)

1. Sign in to the app as the practitioner who owns the mailbox (Nichole for her calendar; whoever administers **Clients@** for Salt room).
2. Start connect (authenticated practitioner JWT required):

   ```http
   POST {API_BASE}/api/practitioners/outlook/connect
   Authorization: Bearer {practitioner_access_token}
   ```

   Response: `{ "authorization_url": "https://login.microsoftonline.com/..." }` — open in browser, sign in as the **target mailbox**, accept calendar scopes (`Calendars.Read`, offline access).

3. Microsoft redirects to `{API_BASE}/api/practitioners/outlook/callback?code=...&state=...` (handled by API; stores encrypted refresh token on the practitioner’s connection row).

4. **Clients@ prod:** After OAuth, either activate placeholder `a5d43af5-0f20-4871-8d79-5af254b1e936` (set `is_active=true`, clear `oauth_pending`) or merge into the OAuth-created row and remove duplicate. Apply locked category maps:

   ```bash
   # On naturepath-data-1 (VPC), from backend tree:
   DB_NAME=natural_path MULTI_RESOURCE_SCHEDULING=true \
     python -m scripts.apply_locked_outlook_connection_templates --apply \
     --report-json /tmp/outlook-templates-prod.json
   ```

5. **Sync** (after each successful OAuth):

   ```http
   POST {API_BASE}/api/practitioners/outlook/sync
   Authorization: Bearer {practitioner_access_token}
   ```

   Or VM helper: `python3 ~/phase6_vm_staging_ops.py` with `STAGING_API` / `DB_NAME` set appropriately.

6. Confirm Mongo `resource_busy_intervals` counts increase for Nichole resource `5786a4d5-93bd-5ae9-83ba-43db7872cf89` and Salt room resource (see seed docs).

## Staging prove (already green with synthetic busy)

- Synthetic Discovery≠Salt on staging API: `qa/reports/multi-resource-proof/discovery-neq-salt-staging-20261018c.json`
- **2026-10-18 re-run without synthetic:** `discovery-neq-salt-staging-20261018g.json` — **fail** (Nichole Outlook busy not applied; sync 400).

## Enable prod flag (only after checklist)

**Prerequisites:** Staging P1–P8 + Jonathan sign-off; **both** Nichole and Clients@ sync healthy on **prod**; admin `/admin/scheduling` verified on `thenaturalpathla.com`.

```bash
gcloud run services update natural-path-api \
  --project project-990664b0-1bae-4746-88d \
  --region us-central1 \
  --update-env-vars MULTI_RESOURCE_SCHEDULING=true
```

**Rollback** (immediate legacy booking + Outlook path; do **not** delete `resources` / `resource_busy_intervals`):

```bash
gcloud run services update natural-path-api \
  --project project-990664b0-1bae-4746-88d \
  --region us-central1 \
  --remove-env-vars MULTI_RESOURCE_SCHEDULING
```

Redeploying via `deploy/gcp/02-deploy-backend.sh` without adding the var to `ENV_VARS` will **not** set the flag — use `update-env-vars` for cutover.

## Prod Discovery≠Salt prove (after flag on)

From VPC VM or CI with prod `DB_NAME=natural_path` and flag on:

```bash
DB_NAME=natural_path MULTI_RESOURCE_SCHEDULING=true \
  STAGING_API=https://natural-path-api-qxje535rja-uc.a.run.app \
  INJECT_SYNTHETIC_BUSY=0 \
  python3 ~/phase6_vm_staging_ops.py
```

Save stdout JSON under `qa/reports/multi-resource-proof/discovery-neq-salt-prod-*.json`. **Goal complete only when** this passes with real Outlook busy (not only synthetic).

## Firebase deploy default project

Root `.firebaserc` default is **`project-990664b0-1bae-4746-88d`** so `firebase deploy` targets the live hosting project (`thenaturalpathla.com` custom domain on that project).
