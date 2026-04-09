# The Natural Path Spa Management System - PRD

## Original Problem Statement
Build a production-grade backend for "The Natural Path Spa Management System" with:
- Full FastAPI backend with DDD/Clean Architecture
- MongoDB database
- Mock REVEL POS integration for payments/bookings
- Celery + Redis for background tasks
- WebSocket for real-time availability
- Resend email + Twilio SMS notifications
- React TypeScript SDK for frontend integration

## Architecture

### Backend Structure (DDD/Clean Architecture)
```
/app/backend/
├── core/                    # Configuration
├── domain/                  # Domain Layer
│   ├── entities/           # Business entities
│   ├── events/             # Domain events
│   ├── repositories/       # Repository interfaces
│   └── services/           # Domain services
├── application/            # Application Layer
│   ├── use_cases/          # Business logic
│   └── dto/                # Data transfer objects
├── infrastructure/         # Infrastructure Layer
│   ├── database/           # MongoDB connection
│   ├── repositories/       # Repository implementations
│   ├── external/           # External services (REVEL, Email, SMS)
│   ├── cache/              # Redis cache
│   └── queue/              # Celery configuration
├── presentation/           # Presentation Layer
│   ├── api/                # FastAPI routers
│   ├── dependencies/       # DI dependencies
│   └── websockets/         # WebSocket handlers
└── workers/                # Celery background workers
```

### SDK Structure
```
/app/sdk/
├── src/
│   ├── api/                # API client & endpoints
│   ├── hooks/              # React Query hooks
│   ├── providers/          # NaturalPathProvider
│   ├── types/              # TypeScript types
│   ├── utils/              # Utility functions
│   └── websocket/          # WebSocket manager
├── docs/                   # Documentation
└── examples/               # Usage examples
```

## What's Been Implemented (March 2026)

### Backend (100% Complete)
- [x] FastAPI server with async endpoints
- [x] MongoDB database with proper indexes
- [x] JWT authentication (access + refresh tokens)
- [x] Complete CRUD for Services, Practitioners, Bookings
- [x] Multi-step booking flow (initiate → lock → confirm)
- [x] Mock REVEL POS integration
- [x] WebSocket for real-time availability
- [x] Celery workers for background tasks
- [x] Email service (Resend) - integrated
- [x] SMS service (Twilio) - integrated
- [x] Admin dashboard endpoints
- [x] Booking analytics endpoints
- [x] Seed data for testing
- [x] Casbin policy-based RBAC (`core/rbac_model.conf`, `core/rbac_policy.csv`) with authorization audit logs in Mongo (`authorization_audit`)
- [x] Startup seeding removed from app init; one-time seed scripts adopted (`scripts/seed_services.py`, `scripts/seed_owner.py`)
- [x] Local dev runner added (`scripts/run-local.sh`) with Mongo env loading and automatic service/review seed verification
- [x] CORS hardened via env (`CORS_ALLOWED_ORIGINS`) and no wildcard defaults

### SDK (100% Complete)
- [x] TypeScript types for all entities
- [x] React Query hooks for all endpoints
- [x] Authentication hooks (useAuth)
- [x] Service hooks (useServices, useService)
- [x] Practitioner hooks (usePractitioners, useAvailability)
- [x] Booking hooks (useBookingFlow, useUserBookings)
- [x] Admin hooks (useAdminStats, useBookingAnalytics)
- [x] WebSocket hooks (useRealtimeAvailability)
- [x] NaturalPathProvider component
- [x] Full documentation (README, Integration Guide)
- [x] Usage examples

### Frontend (Vite + React) — SDK integration in progress
**Repo:** `frontend/` (separate git root from `backend/`).  
**Local API:** `VITE_NATURAL_PATH_API_URL` (default `http://localhost:8000`). SDK consumed via `file:../backend/sdk` + Vite alias to SDK source. **Production builds** must set `VITE_NATURAL_PATH_API_URL` (app throws at bootstrap if missing in `import.meta.env.PROD`).

**Explicitly out of scope (per product direction):**
- **Revel POS:** no dedicated UI; mock/backend integration only.
- **Store / products:** no admin, practitioner, or guest/client storefront UI in this phase.

**Done (customer path):**
- [x] `NaturalPathProvider` in app bootstrap; `onAuthError` → `/sign-in`
- [x] Services list + service detail from API (`useServices`, `useService`); route `/service/:serviceId` (ID-based URLs)
- [x] Booking flow (`useBookingFlow`, practitioners, availability) + `?serviceId=` prefill; **sequential booking uses `booking_id` from `initiate` response** (SDK `lockSlot` / `confirmBooking` accept optional override id)
- [x] Booking history (`useUserBookings`) with upcoming/past grouping; null-safe `slot`; detail sheet `role="dialog"` + Escape
- [x] **Auth:** `SignIn` uses `useAuth().login`; `safePostLoginPath` for internal redirects only; shared `formatClientError` for API messages
- [x] **Auth gates:** `RequireAuth` on `/book-appointment`, `/booking-history`, and **practitioner shell routes** (`/availability`, `/practitioner`, `/services-management`, `/appointments`, `/reschedule`, `/reporting`)
- [x] `InputField` label/`htmlFor`/`id` via `useId` (a11y)
- [x] Service management supports `benefits` create/edit (one-per-line UI -> array payload)
- [x] **Vitest** (`npm test`): `src/lib/clientErrors.test.js`, `src/lib/safeRedirect.test.js`
- [x] ESLint flat config (`react-hooks` `recommended-latest`); `vite.config` ESM-safe `__dirname`

**Still to wire (high level):**
- [ ] `SignUp` / `SignUpBooking` → `useAuth().register` (or dedicated register flow)
- [x] Customer header / nav auth-aware links + logout
- [ ] `useRealtimeAvailability` on booking slot selection (optional polish)
- [ ] Practitioner + admin **data** on existing screens → SDK admin/practitioner hooks (UI shells exist; not store/Revel)
- [x] Production-like CORS/env controls in backend config

## AWS deployment

**Runbook (manual + ECS/EC2 options):** see [`docs/DEPLOYMENT_AWS.md`](../docs/DEPLOYMENT_AWS.md).  
**CLI note:** if `aws sts get-caller-identity` fails with session expired, run `aws login` (SSO) or refresh keys before pushing to ECR or updating ECS.

**After deploy:** align frontend `VITE_NATURAL_PATH_API_URL` with the public API URL; API listens on **port 8001** in Docker (`backend/Dockerfile` / `docker-compose.yml`). Keep `CORS_ALLOWED_ORIGINS` strict to CloudFront / app origin(s).

**Review — still left after AWS goes live:** sign-up/forgot-password UX; customer header + logout; practitioner **Clients** / reporting shells wired to admin hooks; **admin dashboard UI**; real **Resend/Twilio** keys; CI/CD to ECR/ECS; WebSocket stickiness if multiple API tasks; **Ecommerce/Revel** build-out per `docs/ECOMMERCE_REVEL_PLAN.md` (mock Revel today).

## Ecommerce (Revel) — planned

**Product spec:** [`docs/ECOMMERCE_REVEL_PLAN.md`](../docs/ECOMMERCE_REVEL_PLAN.md) — order–inventory flow, delivery address, **no online payment** (back office / Revel), practitioner + guest UIs, backend phases, SDK hooks outline.

## Integration plan — remaining work (planner snapshot)
Use this checklist to see **done vs left** without re-scanning the repo.

| Area | Status | Notes |
|------|--------|--------|
| Customer browse / service detail | Done | Errors normalized via `formatClientError`; categories `replaceAll` |
| Book appointment (initiate → lock → confirm) | Done | Try/catch + `reset()`; explicit `booking_id` after initiate |
| Booking history | Done | Optional `slot`; load errors normalized |
| Sign-in + protected customer routes | Done | Safe redirect; production env guard |
| Protected practitioner routes (shell) | Done | Data hooks still TODO on many pages |
| Sign-up / forgot-password flows | Not integrated | Wire to SDK/auth API when ready |
| Profile / session chrome | Not integrated | `useProfile`, logout in header |
| Practitioner features (calendar, clients, services, availability) | **Done (core)** | `/appointments` calendar (`usePractitionerCalendar`), `/services-management` (`useCreateService` + `useMyPractitioner`), `/availability` (PATCH availability + `useGenerateSlots`). Backend: `GET /api/me/practitioner`, `GET /api/booking/practitioner/calendar`, practitioner `POST /services` (no featured/REVEL), self-only `generate-slots`. |
| Admin dashboard UI | Not started | SDK hooks exist |
| Revel UI | Planned | See [`docs/ECOMMERCE_REVEL_PLAN.md`](../docs/ECOMMERCE_REVEL_PLAN.md) (practitioner catalog + guest storefront + orders, no web payment) |
| Store / product UI (any role) | Planned | Same doc; backend today uses **mock** `RevelService` until real API wired |

## Tests & integration memory (append as you verify)
**Automated (Vitest):** `formatClientError`, `safePostLoginPath` — run `cd frontend && npm test`.  
**Manual smoke (local API):** sign in → services → service detail → book (with `?serviceId=`) → history; open practitioner route while signed out → redirect to sign-in.

Record new rows here after each successful verification:
- *2026-03-24:* Vitest unit tests for `clientErrors` + `safeRedirect` passing; SDK `useBookingFlow` accepts optional booking id on lock/confirm; frontend lint + production build green.
- *2026-03-24:* Practitioner E2E: pytest `tests/test_access_control.py` (5); Vitest + RTL `RequireAuth.test.jsx`, `practitionerSchedule.test.js`; practitioner UI wired to SDK; backend practitioner service create strips `is_featured` / `revel_product_id`.

## Agent / planner guidance
When continuing frontend work:
1. Prefer **small commits** in `frontend/` after each vertical slice; use author email `dagogodboss@gmail.com` if committing on behalf of the project owner.
2. **TDD for new logic:** add `*.test.js` next to small pure modules (errors, redirects, formatters) before or alongside implementation; run `npm test` before commit.
3. **Auth first** for any `/api/me/*` or booking mutation routes — unauthenticated users should hit `RequireAuth` or explicit login prompts.
4. Reuse SDK hooks from `natural-path-sdk`; avoid duplicating `fetch`/axios in UI code.
5. After substantive integration milestones, **update this file** (`backend/memory/PRD.md`) so backlog, the integration table, and the test memory section stay truthful.

## Implementation roadmap (next phases)
Structured plan for remaining frontend + rollout work. Order assumes local backend first, then staging/production API.

### Phase A — Customer account completion
- Register screens wired to `register()`; optional email verification UX if backend adds it
- Profile page: `useProfile`, `useUpdateProfile`
- Global session UI: avatar/name, logout, optional `useRealtimeNotifications` for toasts

### Phase B — Booking UX hardening
- Loading/error boundaries consistent across services, booking, history
- Optional: WebSocket live slots on booking page; countdown if slot lock TTL is exposed
- Cancel booking: `useCancelBooking` from history detail when product requires it

### Phase C — Practitioner & admin
- Calendar / clients / reporting screens backed by `useAllBookings`, `useBookingsByDateRange`, analytics hooks
- Role-based routing: hide admin routes from `customer` JWT (decode role or use `/api/me`)

### Phase D — Environments & quality
- `.env.example` for frontend; document `VITE_NATURAL_PATH_API_URL`
- E2E smoke: login → book → confirm → see history
- Production build: publish or link SDK (`npm` / workspace) instead of only local `file:` + alias

### Phase E — Ops (from original backlog)
- Resend/Twilio real keys; deployment; monitoring/logging

## API Endpoints

### Auth
- POST /api/auth/register
- POST /api/auth/login
- POST /api/auth/refresh

### Services
- GET /api/services
- GET /api/services/featured
- GET /api/services/{id}
- POST /api/services (admin)
- PATCH /api/services/{id} (admin)
- DELETE /api/services/{id} (admin)

### Practitioners
- GET /api/practitioners
- GET /api/practitioners/featured
- GET /api/practitioners/{id}
- GET /api/practitioners/{id}/availability
- POST /api/practitioners (admin)
- PATCH /api/practitioners/{id}

### Booking
- POST /api/booking/initiate
- POST /api/booking/lock-slot
- POST /api/booking/confirm
- GET /api/booking/{id}
- POST /api/booking/cancel
- GET /api/booking/admin/all (admin)

### User
- GET /api/me
- PATCH /api/me
- GET /api/me/bookings
- GET /api/me/notifications

### Admin
- GET /api/admin/stats
- GET /api/admin/analytics/bookings
- GET /api/admin/customers
- GET /api/admin/users

### WebSocket
- WS /ws/availability/{practitioner_id}/{date}
- WS /ws/notifications/{user_id}

## Owner Bootstrap
- One-time script: `PYTHONPATH=. python3 scripts/seed_owner.py`
- Required env vars:
  - `MONGO_URL` (or `MONGODB_URL`)
  - `OWNER_PASSWORD` (set securely outside repo)
- Owner account seeded/updated as:
  - Name: Nichole Moore
  - Email: admin@thenaturalpath.com
  - Role: practitioner (admin-equivalent permissions via Casbin role inheritance)

## Prioritized Backlog

### P0 (Critical)
- [x] Backend API implementation
- [x] SDK implementation

### P1 (High Priority)
- [~] Frontend implementation using SDK (customer browse/book/history + auth gate in progress; see “Frontend” section above)
- [ ] **Production deployment on AWS** — follow [`docs/DEPLOYMENT_AWS.md`](../docs/DEPLOYMENT_AWS.md) (ECR, ECS or EC2, MongoDB Atlas or DocumentDB, ElastiCache, S3+CloudFront for SPA)
- [ ] Actual Resend/Twilio API key configuration

### P2 (Medium Priority)
- [ ] Rescheduling functionality
- [ ] Practitioner calendar management UI
- [ ] Customer reviews/ratings

### P3 (Nice to Have)
- [ ] Gift card support
- [ ] Package deals/bundles
- [ ] Loyalty points system
- [ ] Mobile app (React Native)

## Next Tasks
1. Frontend: SignUp flows, profile, logout/session UI; then practitioner/admin SDK wiring
2. Configure actual Resend API key for email notifications
3. Configure actual Twilio credentials for SMS
4. Deploy to production environment (frontend + API; env URLs)
5. Set up monitoring and logging
