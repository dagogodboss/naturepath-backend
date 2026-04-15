# Agent / continuity memory — Naturepath project

This file is for **future coding sessions** (humans and assistants): what was built, where it lives, and how to run things. The repo has **two git roots**: `backend/` and `frontend/` (parent `naturepath/` is not a single git repo).

---

## Session summary (consolidated)

### Authentication (SDK)

- **Problem:** `useAuth` used local `useState` per component, so logout in one place did not update auth state elsewhere (logout appeared broken).
- **Fix:** Shared **`AuthProvider`** in `@natural-path/sdk` (`sdk/src/providers/AuthProvider.tsx`), wrapped inside `NaturalPathProvider` → `QueryClientProvider`. All `useAuth()` consumers share one state.
- **Logout:** Clears tokens, clears React Query cache, calls **`resetApiClient()`** so Axios is recreated.
- **Exports:** `useAuth`, `useCurrentUser`, `useIsAuthenticated` re-export from provider; `hooks/useAuth.ts` is thin re-export.

### Services API — discovery-first + benefits + reviews

- **`Service` model:** `is_discovery_entry` (bool) marks the discovery offering; legacy detection still uses name contains `"discovery call"` in booking logic.
- **Visibility (public list + detail + reviews):** Optional Bearer via fixed **`get_optional_user`** (async dependency; previous implementation was broken).
  - No auth → only discovery-entry services.
  - Authenticated customer without completed discovery → discovery only.
  - Customer with discovery completed → full catalog.
  - Admin / practitioner → full catalog.
- **Benefits:** On service documents; normalized in `ServiceUseCase`.
- **Reviews:** `service_reviews` collection; included on service detail payload; `GET /api/services/{id}/reviews` gated same as detail.

### Frontend — customer flow

- **Services / ServiceDetails:** Rely on API for gating; discovery eligibility messaging for customers; category tabs when API returns multiple services.
- **Landing:** Hero “Book a Discovery call” routes to **`/sign-up-booking`** (not protected booking-only route without account).

### Seeding

- **`backend/scripts/seed_services.py`:** Upserts catalog from `seeds/service_catalog.py` (benefits, reviews, `is_discovery_entry`). Uses **`MONGO_URL` or `MONGODB_URL`** (not committed).
- **`backend/scripts/seed_owner.py`:** One-time owner bootstrap; owner email aligned to business (`Nmoore@thenaturalpathla.com` in current code); requires **`OWNER_PASSWORD`**.
- **`backend/server.py`:** Sample services include `is_discovery_entry: True` on Discovery Call when DB empty (if still used).

### Local dev runner

- **Canonical script (in repo):** `backend/scripts/run-local.sh`
  - Loads `backend/backend/.env` (KEY=VALUE lines only; does not override existing env).
  - Builds default `MONGO_URL` from `DB_NAME` / host / port if unset.
  - Verifies service seed (counts, benefits, discovery entry); runs `seed_services.py` if incomplete.
  - Verifies admin/owner user presence; runs `seed_owner.py` if missing **and** `OWNER_PASSWORD` is set.
  - Warns if Mongo unreachable (does not always fail hard).
  - Starts **uvicorn** on **8001**, Vite on **5173**; logs under `backend/.backend-dev.log` and `backend/.frontend-dev.log`.
- **Root convenience:** `/Users/mac/naturepath/run-local.sh` — thin wrapper `exec backend/scripts/run-local.sh` (not in `backend` git; convenience only).

### RBAC admin UI (frontend)

- **Route:** `/admin/rbac` — `RbacManagement.jsx`
- **Redesign:** Plain-language roles, search, card layout, elevated-role confirmation, owner-only assignment of **owner** role, cannot edit own role on this screen; Casbin overrides under collapsed “Technical access rules (IT / support)”.

### Commits (reference — verify with `git log`)

| Area | Approx. subject (check SHAs locally) |
|------|--------------------------------------|
| Backend | Discovery gating, shared auth, optional user fix, seeds, run-local |
| Backend | `chore: verify owner account in local runner` (run-local + seed_owner) |
| Frontend | Customer flows, RBAC UX (`feat: friendlier team access UI for role management`) |

---

## Run commands (local)

```bash
# From backend repo — full stack + checks
cd /path/to/naturepath/backend
./scripts/run-local.sh
```

```bash
# Seed services only
cd /path/to/naturepath/backend
export MONGO_URL="mongodb://localhost:27017/natural_path_spa"
PYTHONPATH=. python3 scripts/seed_services.py
```

```bash
# Seed owner (use backend venv so passlib resolves)
cd /path/to/naturepath/backend/backend && . .venv/bin/activate && cd ..
export MONGO_URL="mongodb://localhost:27017/natural_path_spa"
export OWNER_PASSWORD="…"
PYTHONPATH=. python3 scripts/seed_owner.py
```

**MongoDB** must be running locally (or point `MONGO_URL` at Atlas). `connection refused` on `localhost:27017` means the daemon is not listening — not “data deleted.”

---

## Operational notes (from troubleshooting)

- Clearing **`~/Library/Caches`** does not remove Homebrew packages; Colima/Lima disk lives under **`~/.colima`** and **`~/.lima`**.
- **`brew services start mongodb-community@…`** can fail with `launchctl bootstrap` exit 5 — try unload plist, or run **`mongod`** in foreground with config.
- Atlas URI must not use **`/dbname/?`** (slash before `?`) — use **`.../dbname?appName=...`**.

---

## Files to read first when continuing

| Topic | Path |
|-------|------|
| SDK auth | `backend/sdk/src/providers/AuthProvider.tsx`, `NaturalPathProvider.tsx` |
| Service routes | `backend/backend/presentation/api/service_routes.py` |
| Optional auth | `backend/backend/presentation/dependencies/auth.py` (`get_optional_user`) |
| Booking discovery | `backend/backend/application/use_cases/booking_use_case.py` (`_is_discovery_service`) |
| RBAC UI | `frontend/src/pages/admin/RbacManagement.jsx` |
| Local runner | `backend/scripts/run-local.sh` |

---

## How to update this file

After meaningful changes, append a dated **Session note** block below or edit the summary tables. Keep secrets out of this file (no real passwords or connection strings).
