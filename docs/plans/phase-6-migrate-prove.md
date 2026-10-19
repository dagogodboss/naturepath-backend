# Phase 6 — Migrate production + prove Salt ≠ Discovery

**Status:** Runbook + **staging ops checklist** (below); P1–P5 **implemented behind flag** (default false). **Staging API live** with seed, service attach, booking backfill, Outlook connection templates / Clients@ placeholder; **admin JWT smoke passed**; **prod API** revision **natural-path-api-00021-hv8** with flag **unset/false**; **prod Mongo `natural_path` data prep applied** — see `qa/reports/multi-resource-proof/prod-migrate-20261018f.json`.  
**Primary unblock:** Entra admin consent for Application **`Calendars.Read`** on app `daf7c7db-…` ([naturepath#8](https://github.com/dagogodboss/naturepath/issues/8)) **plus** Exchange mailbox least-privilege (Clients@ + Nichole only — **required**, not optional) so app-only Graph can read those calendars. [#9](https://github.com/dagogodboss/naturepath/issues/9) engineering slices 1–4 are complete; Accept remains a **human** send when ready (agents do not outreach). Delegated Clients@ OAuth is **not** the preferred path (legacy tokens unusable).  
**Timezone:** America/Chicago.  
**GCP:** project-990664b0-1bae-4746-88d only.

**STOP:** Do **not** enable `MULTI_RESOURCE_SCHEDULING` in **production**, deploy for cutover, or mark the Goal complete until Entra Accept + staging **real Outlook** Discovery≠Salt prove + Jonathan sign-off. Synthetic prove artifacts are **not** that gate. Local/agent work stays flag-off unless ops runs staging checklist step 6.

### Prove artifacts — synthetic vs real (do not conflate)

| Artifact / claim | Mode | Counts as cutover / Goal gate? |
|------------------|------|--------------------------------|
| `prove_multi_resource_slots.py` | In-process **synthetic** busy | **No** — unit/scaffold only |
| `discovery-neq-salt-staging-20261018c.json` | Staging API + **synthetic** Nichole busy (`source=staging_prove_synthetic`) | **No** — engine wiring smoke only |
| `post-consent-cutover-*-*.json` dry-run exit **10** | Graph probe; Entra still denied | **No** — consent still required |
| Post-consent cutover with `INJECT_SYNTHETIC_BUSY=0` / `--real-busy-only` | **Real** Outlook→`resource_busy_intervals` | **Yes** for staging gate (after Accept) |
| Prod flag on + live CT book | Real calendars in production | **Yes** for Goal complete |

**Do not** write “Discovery≠Salt proved” without saying **synthetic** or **real Outlook**.

### Staging snapshot (2026-10-18, automatable ops)

| Item | Value |
|------|--------|
| Staging API | https://natural-path-api-staging-30255322344.us-central1.run.app |
| DB | `natural_path_staging` |
| `MULTI_RESOURCE_SCHEDULING` staging | **true** |
| `MULTI_RESOURCE_SCHEDULING` prod `natural-path-api` | **unset** (defaults **false**); revision **natural-path-api-00021-hv8** → `qa/reports/multi-resource-proof/prod-deploy-20261018e.json` |
| Prod data prep (flag off) | **Applied** on VM Mongo **`natural_path`** only → `qa/reports/multi-resource-proof/prod-migrate-20261018f.json` |
| Seed + indexes + service backfill | Done (prior turn) |
| Booking backfill | **Applied** — 2/2 updated, 0 anomalies → `qa/reports/multi-resource-proof/booking-backfill-apply-20261018b.json` |
| Nichole Outlook row | `connection_id` **0ae88711-4e79-42b4-831f-141705d6ca9c** — locked maps applied; **sync failed 2026-10-18** (Graph token refresh **400**) → `qa/reports/multi-resource-proof/outlook-sync-nichole-20261018c.json`; `resource_busy_intervals` for Nichole still **0** until re-consent + successful sync |
| Clients@ Outlook row | **Placeholder** `connection_id` **9fba4c5f-38e7-4a69-888c-3f84627ed3ea** — maps prefilled, `is_active=false`, `oauth_pending=true`; real OAuth must supply refresh token |
| Discovery ≠ Salt prove (staging API) | **Synthetic pass only** — 2026-10-21 CT, injected Nichole Discovery busy 15:00–15:45; Discovery excludes 15:00, Salt still offers 15:00 → `qa/reports/multi-resource-proof/discovery-neq-salt-staging-20261018c.json`. **Real Outlook busy prove still outstanding.** |
| Admin API smoke (JWT) | **Pass** — minted access JWT for staging **owner**; `GET /api/admin/resources` **200** → `qa/reports/multi-resource-proof/admin-smoke-20261018c.json` (smoke ≠ Goal complete) |
| VPC ops helper | `backend/scripts/phase6_vm_staging_ops.py` on **naturepath-data-1** (Mongo + staging API; no secrets in output) |
| Progress artifact | `qa/reports/multi-resource-proof/staging-progress-20261018c.json` |
| Graph app-only probe | **Blocked** — exit **10** / 403 Clients@ (`post-consent-cutover-staging-20261018*.json`) until Entra Accept |

**Human / Entra still required (order matters):**

1. **Entra Global Admin — primary** — Accept Application **`Calendars.Read`** for app `daf7c7db-…` ([#8](https://github.com/dagogodboss/naturepath/issues/8), [ops-entra-consent-request.md](./ops-entra-consent-request.md)). Then restrict the app to **Clients@** + Nichole mailboxes (Exchange application access policy / RBAC) — **required before cutover**, not “optional later.”
2. **App-only sync** — After Accept, run `phase6_post_consent_cutover` on staging (probe → auth_mode application → sync → **real-busy** Discovery≠Salt). Prefer shared Clients@ calendar for Salt visibility ([#9 comment](https://github.com/dagogodboss/naturepath/issues/9#issuecomment-6262033979)).
3. **Delegated fallback (only if app-only blocked)** — Nichole / Clients@ device-code or browser consent; legacy refresh tokens are **not** recoverable. Staging redirect must stay registered if using delegated.
4. **Admin JWT** — Resources list **done**. Still capture locked templates + review queue JSON when convenient.
5. **Manual P1–P8** — Synthetic engine prove **done**; remaining: **real** Outlook-tagged busy, live booking at 15:00, Monday rule, P5 review queue, etc. (America/Chicago).

Ops helper (VM Mongo, same path as seed): `python -m scripts.apply_locked_outlook_connection_templates --report-json …`

---

## Staging ops checklist (Phase 6 unblock)

Run on **staging Mongo + staging API only**. Order matters. Keep production flag **false** until this checklist passes and is reviewed.

### Phase 0 locks (do not re-litigate in staging)

| Lock | Value |
|------|--------|
| Salt hours | Mon–Fri **10:30–18:00** room window; **last start 17:00** (occupied may run to 18:00) |
| Salt occupied | Customer **45** + cleanup **15** = **60**; capacity **1** |
| Discovery / consults | **Nichole only**; **no Monday** client slots (`flags.no_mondays`) |
| Discovery last start | **17:00** when occupied 45m (finish by 17:45) |
| Salt Outlook authority | **Clients@thenaturalpathla.com** — not Nichole’s calendar for Salt |
| Mystery / unlabeled Outlook busy | **Stay blocked** until category map or review classifies (Q4) |
| Reschedule SoT | **Q7 B** — Outlook/office priority for free times; app conflicts → flag/review, not silent payment rewrite |

Reference: [phase-0-jonathan-questions.md](./phase-0-jonathan-questions.md), [multi-resource-scheduling.md](./multi-resource-scheduling.md) locked table.

### 1. Seed resources + indexes

```bash
cd backend
PYTHONPATH=backend python -m scripts.seed_multi_resource_resources --dry-run
PYTHONPATH=backend python -m scripts.seed_multi_resource_resources --apply --create-indexes
```

Verify in Mongo or `/admin/scheduling` (after step 6): **Dr. Nichole** practitioner resource linked to existing Nichole practitioner; **Salt room** with Mon–Fri 10:30–18:00, `last_start_time` **17:00**.

### 2. Backfill services → resources + prep/recovery

Locked attach rules live in `backend/domain/multi_resource_service_attach.py` (Discovery/consults/education/labs → Nichole; Salt → room; Salt **0/45/15** prep/session/recovery on catalog).

```bash
cd backend
PYTHONPATH=backend python -m scripts.backfill_multi_resource_services --dry-run
PYTHONPATH=backend python -m scripts.backfill_multi_resource_services --apply
```

Or combined with seed: `seed_multi_resource_resources --apply --create-indexes --backfill-services`.

Confirm: Discovery + consults have `required_resource_id` → Nichole, `prep_minutes`/`recovery_minutes` per [phase-1-data-model.md](./phase-1-data-model.md) §2.2; Salt → Salt room with **0 prep, 15 recovery** (45 customer in `duration_minutes`).

### 3. OAuth + Outlook connections (human)

| Mailbox | Role | After OAuth |
|---------|------|-------------|
| Nichole practitioner mailbox | Authoritative for **Nichole** resource | PATCH connection with templates from seed dry-run output or `GET /api/admin/scheduling/outlook/locked-connection-templates` (flag on) |
| **Clients@thenaturalpathla.com** | Authoritative for **Salt room** only | Same; `authoritative_for_resource_ids` = Salt resource id |

Apply locked fields from `domain/multi_resource_defaults.py` / locked-connection-templates:

- `authoritative_for_resource_ids`
- `category_maps` (Discovery, Consultation, Salt Session, Salt legacy, Business Closure)
- `visibility_only: false` for both authoritative mailboxes
- Kristin (if connected later): **visibility_only** — must not double-count occupancy

Do **not** skip Clients@ — Salt room stays wrongly free without it.

### 4. Enable flag — **staging only**

Set on staging API service env (not local agent default, not production):

```text
MULTI_RESOURCE_SCHEDULING=true
```

Redeploy/restart staging API. Production and local `.env` remain **false** until prod cutover approved.

**Rollback:** set `MULTI_RESOURCE_SCHEDULING=false` (or unset) → immediate legacy booking + Outlook path; **do not** delete `resources` / `resource_busy_intervals` collections.

### 5. Smoke `/admin/scheduling` (staging, flag on)

As admin/practitioner:

| Section | Check |
|---------|--------|
| Resources & hours | Nichole + Salt listed; Salt last start 17:00 |
| Services & durations | `required_resource_id`, prep/recovery match step 2 |
| Outlook | Both connections show sync status; category maps match locked templates |
| Preview / explain | Sample date shows per-resource reasons (not global practitioner busy) |
| Review queue | Empty or actionable; unmapped busy creates items (P5 prep) |

Route: `/admin/scheduling` (no BottomNav link yet — direct URL OK).

### 6. Prove Discovery ≠ Salt

**Automated (no Mongo):**

```bash
cd backend
PYTHONPATH=backend python -m scripts.prove_multi_resource_slots
PYTHONPATH=backend pytest backend/tests/test_multi_resource* -q
```

**Staging manual (America/Chicago):**

1. With Nichole busy for Discovery at **15:00** from **real Outlook** (or a tagged live event — **not** `staging_prove_synthetic`), confirm Salt still offers **15:00**. *(Synthetic API prove already passed 2026-10-21 — `discovery-neq-salt-staging-20261018c.json` — that is **not** this step.)*
2. Book Salt at **15:00**; confirm Discovery still offers other Nichole-free times same day.
3. **Monday:** no Discovery slots; Salt may still show Mon–Fri window.

Capture screenshots + API JSON under `qa/reports/multi-resource-proof/` for P1–P8 table below.

**Staging DB + API prove (2026-10-18):**

```bash
# On naturepath-data-1 (VPC), after copying scripts/phase6_vm_staging_ops.py:
python3 ~/phase6_vm_staging_ops.py
# Writes JSON markers to stdout; save under qa/reports/multi-resource-proof/*20261018c.json
```

Local Mongo from laptop is **not** reachable (private IP); use VM helper or staging API only.

### Fail criteria (stop and rollback)

| Symptom | Action |
|---------|--------|
| Salt 15:00 disappears when only Nichole Discovery busy | Flag off; check service `required_resource_id` and slot path not mixing global busy |
| Salt Outlook events do not block room | Verify Clients@ connection authoritative + Salt Session category map |
| All services empty slots with flag on | Missing `required_resource_id` or inactive resource — re-run backfill + seed |
| Sync error but slots still open for Outlook-dependent services | P6 fail — fail-closed bug; flag off until fixed |
| Silent booking cancel on hours edit | P8 fail — stop cutover |

### 7. Not in this checklist (later prod cutover)

- ~~Historical **bookings** `resource_id` backfill~~ — **done on prod** 2026-10-18 (flag still off); artifact `prod-migrate-20261018f.json`
- Production **flag enable** — exact gcloud in `prod-migrate-20261018f.json` § cutover_after_oauth_and_staging_signoff
- BottomNav **Scheduling** entry
- Goal complete

---

## Scaffold / code status (2026-10-18)

**P1–P5 code is in tree behind `MULTI_RESOURCE_SCHEDULING` (default false). Phase 6 ops + production P1–P8 still outstanding.**

| Piece | Location | Live? |
|-------|----------|-------|
| In-process Discovery≠Salt prove (P1/P2 core + P3/P4 cores) | `backend/scripts/prove_multi_resource_slots.py` | Synthetic only; exit 0 on pass; no Mongo/prod |
| Seed Nichole + Salt (`--dry-run` default; `--apply` to write) | `backend/scripts/seed_multi_resource_resources.py` | **Not auto-run**; apply off by default |
| Service attach backfill | `backend/scripts/backfill_multi_resource_services.py` | Dry-run default; `--apply` writes |
| Booking + slots + confirm (flag on) | `multi_resource_booking.py`, `booking_use_case.py` | Legacy when flag false |
| Historical bookings `resource_id` backfill | `backend/scripts/backfill_multi_resource_bookings.py` | Dry-run default; `--apply` writes |
| Prove JSON artifact | `prove_multi_resource_slots --write-artifact` → `qa/reports/multi-resource-proof/` | Local synthetic P1–P4 core |
| Admin scheduling API + UI shell | `scheduling_admin_routes.py`, `SchedulingAdmin.jsx` | 404 when flag false |
| Inventory + cutover order | this doc (§ Inventory / Cutover order) | Docs + staging checklist above |

**Explicitly not done:** Entra Application **Calendars.Read** Accept + mailbox least-privilege scope, successful **app-only** sync of Clients@ + Nichole, staging **real Outlook** Discovery≠Salt, staging manual P1–P8, production **flag enable**, prod P1–P8, Goal complete. (Prod Mongo seed/backfill already applied with flag off.)

**Staging automatable ops done (2026-10-18):** separate Cloud Run service, flag **on** staging only, seed/indexes/service attach, **booking backfill apply**, Nichole connection template PATCH + Clients@ placeholder, **synthetic** Discovery≠Salt API prove, **admin resources smoke**, **prod deploy flag-off**.

**Goal status:** Phase 6 **blocked on Entra + real Outlook prove** — **do not** mark the multi-resource Goal complete.

### Prove command (local)

```bash
cd backend
PYTHONPATH=backend python -m scripts.prove_multi_resource_slots
```

---

## Inventory — scaffold files (Phases 1–5) in working tree

Paths relative to repo root. Flag `MULTI_RESOURCE_SCHEDULING` default **false** everywhere.

### Phase 1 — Data model

| File | Role |
|------|------|
| `backend/backend/domain/entities/models.py` | `Resource`, `ResourceBusyInterval`, `ReviewQueueItem`, Outlook map fields, service/booking optional fields |
| `backend/backend/domain/scheduling_occupation.py` | Pure `occupied_minutes` / duration helpers |
| `backend/backend/core/config.py` | `MULTI_RESOURCE_SCHEDULING` / `settings.multi_resource_scheduling` |
| `backend/scripts/seed_multi_resource_resources.py` | Manual Nichole + Salt seed (dry-run default) |
| `backend/backend/tests/test_multi_resource_models.py` | Flag-off + model tests |
| `docs/plans/phase-1-data-model.md` | Design + scaffold status |

### Phase 2 — Outlook category sync

| File | Role |
|------|------|
| `backend/backend/application/outlook_category_sync.py` | Classify / build busy docs / fail-closed / persist helpers |
| `backend/backend/application/outlook_sync.py` | Flag-gated dual-write branch (legacy path when flag false) |
| `backend/backend/infrastructure/external/microsoft_graph.py` | `$select` includes categories (legacy ignore when flag false) |
| `backend/backend/tests/test_outlook_category_sync.py` | Mapping + fail-closed tests |
| `docs/plans/phase-2-outlook-category-sync.md` | Design + scaffold status |

### Phase 3 — Slot engine

| File | Role |
|------|------|
| `backend/backend/application/multi_resource_slots.py` | Per-resource slots (**wired when flag on** via `multi_resource_booking`) |
| `backend/scripts/backfill_multi_resource_services.py` | Service `required_resource_id` + prep/recovery backfill (dry-run default) |
| `backend/backend/domain/multi_resource_service_attach.py` | Locked name → resource attach rules |
| `backend/backend/tests/test_multi_resource_slots.py` | T1–T5 Discovery≠Salt unit proof |
| `docs/plans/phase-3-slot-engine.md` | Design + scaffold status |

### Phase 4 — Admin UI

| File | Role |
|------|------|
| `backend/backend/presentation/api/scheduling_admin_routes.py` | Admin scheduling routes (**404 when flag false**) |
| `backend/backend/tests/test_scheduling_admin_routes.py` | Admin route tests |
| `frontend/src/pages/admin/SchedulingAdmin.jsx` | Thin four-section UI shell |
| `frontend/src/App.jsx` | Registers `/admin/scheduling` (no BottomNav More entry) |
| `docs/plans/phase-4-admin-ui.md` | Design + scaffold status |

### Phase 5 — Why unavailable

| File | Role |
|------|------|
| `backend/backend/application/availability_explain.py` | Pure reason codes + `explain_availability` |
| `backend/backend/tests/test_availability_explain.py` | Explainer unit tests |
| `docs/plans/phase-5-why-unavailable.md` | Design + scaffold status |

*(Explain/review-queue HTTP handlers live in Phase 4 `scheduling_admin_routes.py`.)*

### Phase 6 — Migrate / prove (this phase)

| File | Role |
|------|------|
| `backend/scripts/prove_multi_resource_slots.py` | In-process P1–P4 core prove; exit 0 on pass |
| `docs/plans/phase-6-migrate-prove.md` | This plan + inventory + cutover order |
| `docs/plans/multi-resource-scheduling.md` | Parent Goal plan |
| `docs/plans/phase-0-jonathan-questions.md` | Phase 0 questionnaire (**LOCKED** 2026-10-18 Message 3) |

---

## Cutover order (after Phase 0 lock)

Run only after Jonathan answers are locked and Phases 1–5 scaffolds are reviewed. Keep flag **false** until step 6.

1. **Lock Phase 0** — confirm hours, durations, categories, Kristin visibility, Salt Mon–Fri 10–17, Discovery no-Mondays.
2. **Seed resources** — `seed_multi_resource_resources --apply` (optional `--create-indexes`); verify Nichole linked + Salt hours.
3. **Attach services** — set `required_resource_id` + prep/recovery on Discovery/consults → Nichole; Salt → room.
4. **Outlook connection** — authoritative mailbox for Nichole; category maps (Discovery/Consultation → Nichole; Salt → room; Closure → both).
5. **Dual-write warm** — enable flag in a staging/API canary only after sync writes `resource_busy_intervals` without wiping legacy; keep dual-read off until prove.
6. **Wire slot path** — point open-dates / confirm at `multi_resource_slots` (still behind flag); regenerate open slots.
7. **Backfill bookings** — one-time `resource_id` + occupied times; log anomalies.
8. **Local prove** — `prove_multi_resource_slots` (already green in CI/local) + full pytest `multi_resource*` / related.
9. **Production prove P1–P8** — checklist below; screenshots + API JSON under `qa/reports/multi-resource-proof/`.
10. **Cleanup (later)** — stop global busy subtract; retire unused fields carefully.

Rollback at any time: disable `MULTI_RESOURCE_SLOTS` / `MULTI_RESOURCE_SCHEDULING` → legacy path. Do not delete new collections on rollback.

---

## Migration steps

1. **Seed resources**  
   - Practitioner resource linked to existing Nichole Moore practitioner (`a6e5a244-…`).  
   - Salt room resource (new). Copy current weekly hours onto Nichole; set Salt Mon–Fri 10–17 (Phase 0 locked values).

2. **Attach services**  
   - Discovery + consults (+ Education if Nichole-required) → Nichole resource + prep/recovery from Phase 0.  
   - Salt → room, 60m session (confirm catalog duration).  
   - Keep prerequisite flags unchanged.

3. **Outlook connection**  
   - Mark Nichole mailbox authoritative for practitioner resource.  
   - Kristin (if connected later) visibility-only.  
   - Admin maps categories: Discovery/Consultation → Nichole; Salt → room; Closure → both.

4. **Dual-write / dual-read**  
   - Feature flag `MULTI_RESOURCE_SLOTS` / `MULTI_RESOURCE_SCHEDULING`.  
   - While off: old global busy path.  
   - While on: resource busy intervals + new slot engine.  
   - Sync writes `resource_busy_intervals`; keep legacy `outlook_calendar_events` until cutover stable.

5. **Backfill bookings**  
   - Existing bookings get `resource_id` + occupied times derived from service durations (one-time script; log anomalies).

6. **Cut over**  
   - Enable flag on API; regenerate open slots; monitor sync status.

7. **Cleanup** (later)  
   - Stop subtracting global busy for all services; retire unused fields carefully.

---

## Production proof checklist (Goal exit)

| # | Proof | Pass criteria |
|---|--------|----------------|
| P1 | Book Discovery at 15:00 CT | Occupies Nichole 15:00–occupied end |
| P2 | Same day open Salt at 15:00 | Salt still offered / bookable |
| P3 | Book Salt at 15:00 | Room busy; Discovery still offers other Nichole-free times |
| P4 | Monday Discovery | No slots; Salt may still show if hours allow |
| P5 | Unmapped Outlook busy on Nichole | Blocks Nichole; appears in review queue |
| P6 | Sync forced error | Practitioner booking fail-closed; clear admin banner |
| P7 | Admin explain API | Reasons match P1–P6 |
| P8 | No silent cancel | Hours change previews future bookings |

**Automated core (scaffold):** `scripts/prove_multi_resource_slots.py` covers P1–P4 **in-process** with synthetic busy (not a substitute for production P1–P8).

Screenshots + API JSON under `qa/reports/multi-resource-proof/`.

---

## Rollback

- Disable `MULTI_RESOURCE_SLOTS` → legacy slot path.  
- Do not delete new collections on rollback; keep dual-write offline.

---

## Constraints

- Commits as ilamini Dagogo when committing; no Route53/mail DNS changes.  
- Do **not** mark Goal complete until P1–P8 pass in production.

---

## Document history

| Date | Note |
|------|------|
| 2026-10-18 | Initial Phase 6 migration + production proof checklist |
| 2026-10-18 | Scaffold: in-process prove script, seed --apply off by default, inventory + cutover order; flag remains false |
| 2026-10-18 | Staging ops checklist; service backfill script; status reflects P1–P5 wired-behind-flag |
| 2026-10-18 | Prod `natural_path` seed/backfill + Outlook templates (flag off); cutover commands in `prod-migrate-20261018f.json` |
