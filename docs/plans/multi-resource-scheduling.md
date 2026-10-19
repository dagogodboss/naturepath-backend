# Implementation Plan: Multi-resource scheduling & admin availability

**Status:** Phase 0 — **LOCKED** (2026-10-18 Message 3). Phases **1–5 implemented behind `MULTI_RESOURCE_SCHEDULING`** (default false). Phase **6 blocked on Entra app-only `Calendars.Read` (Application) admin consent** ([#8](https://github.com/dagogodboss/naturepath/issues/8)) plus staging **real Outlook** prove — [checklist](./phase-6-migrate-prove.md#staging-ops-checklist-phase-6-unblock).  
**Business:** Jonathan Moore / The Natural Path LA, Youngsville LA, `America/Chicago`  
**Companion canvas:** [multi-resource-scheduling.canvas.tsx](/Users/mac/.cursor/projects/Users-mac-naturepath/canvases/multi-resource-scheduling.canvas.tsx)  
**Goal title:** Multi-resource scheduling & admin availability *(arm via CreateGoal — see § Goal objective)*

### Truth table (2026-10-19 — do not overstate)

| Claim | Reality |
|-------|---------|
| Phases 1–5 code | **In tree** behind `MULTI_RESOURCE_SCHEDULING` (default **false**; staging **true**) |
| Prod flag | **Off / unset** — do **not** flip until Entra Accept + staging real prove + Jonathan sign-off |
| Discovery≠Salt | **Synthetic** staging API prove only (`discovery-neq-salt-staging-20261018c.json`). **Not** production-proved; **not** a cutover gate by itself |
| Outlook sync | **Blocked** on Entra Application **Calendars.Read** admin consent ([#8](https://github.com/dagogodboss/naturepath/issues/8)); delegated Clients@ token unavailable. Mailbox least-privilege (Clients@ + Nichole only) **required** same day as Accept — see [ops-oauth-prod-cutover.md](./ops-oauth-prod-cutover.md) |
| [#9](https://github.com/dagogodboss/naturepath/issues/9) engineering | Slices 1–4 done; B1 race fixed (`8d89d6a`). Accept package **READY TO SEND** ([#8](https://github.com/dagogodboss/naturepath/issues/8) / [ops-entra-consent-request.md](./ops-entra-consent-request.md)) — human sends; agents do not outreach |
| Goal complete | **No** |

### Locked decisions (Jonathan 2026-10-18)

- **Salt (capacity):** 1 booking at a time; up to 4 people per booking; session 45 + 15 cleanup = **60 occupied**; starts anytime room is free (not hour-only).
- **Consults:** Discovery/consults = **Nichole only** (no consult room v1); Discovery phone in office; consults F2F in office; app Salt hold = 1hr (45+15).
- **Nichole hours:** Office 10am–6pm M–F; off Mondays; clients **Tue–Fri from 10:30am**; all consultations finished by **5:45pm**; **last Discovery start = 5:00pm** (Dr — confirmed Message 3).
- **Holidays:** Flexible (sometimes open); **never** Thanksgiving or Christmas; default block both resources; admin can open other holidays.
- **Staff access (intent):** Nichole and Kristin can add/remove/edit/see all bookings; likes flagging for review.
- **Salt Outlook source:** **Clients@thenaturalpathla.com** only (not Nichole’s calendar for Salt).
- **Two-mailbox capacity (Phase 0 + [#9 comment](https://github.com/dagogodboss/naturepath/issues/9#issuecomment-6262033979)):** Clients@ authoritative for Salt room; Nichole authoritative for practitioner. Seeing Salt must **not** consume Nichole capacity. **Prefer** staff view of the **shared Clients@ calendar** alongside Nichole’s (no occupancy from copies). If staff still need Salt copies inside Nichole’s calendar, those copies must be explicitly visibility-only — do **not** ignore all unknown busy to “fix” copies.
- **Salt window:** M–F starts **10:30am–5:00pm**; last start **5:00pm** (room busy until **6:00pm**). Engine uses a **15-minute** candidate grid today; Phase 0 “anytime” means any free start in that grid within the window (reconcile if product later requires finer granularity).
- **Q7:** **B — Outlook/office priority** for what the app shows free; phone add/move in Outlook updates availability. Safer nuance: busy sync drives slots; conflicting app rows get flag/defined cancel path (not silent payment rewrite).
- **Mystery Outlook:** Keep blocked until labeled.

---

## Overview

Move Nature Path from a **single practitioner weekly schedule + global Outlook busy** model to **multi-resource capacity**: Nichole (practitioner) for Discovery and all consultations; Salt room for Salt sessions (does not require Nichole). Discovery at 3pm must not block Salt at 3pm. Outlook classification uses **category names → resources**. Admins configure; code enforces.

---

## Requirements

- Two resource types (generic for N practitioners / N rooms): practitioner capacity vs room capacity.
- Service → required resource; durations change start times inside resource hours (not per-service weekly calendars).
- Separate customer-visible appointment time vs prep / session / recovery occupation.
- Outlook: Graph **category names** map to resources; colors may later decorate admin cards only.
- Staff visibility copies (Salt on Nichole/Kristin calendars) must not double-count occupancy.
- Unclassified busy on Nichole’s authoritative calendar → block Nichole + admin review; Salt must be tagged or room stays wrongly free.
- Confirm-time recheck/reserve; fail closed on sync failure; conflict flags for races with manual Outlook.
- Admin UI v1: four sections (resources, services, Outlook mapping, preview/review).
- Safe schedule changes: preview affected bookings; never silent cancel.
- Migrate production single-schedule data; prove Salt ≠ Discovery concurrent blocking.

---

## Verdict & principles

1. **Capacity is per resource**, not per service catalog row.
2. **Two busy calendars** (Nichole, Salt room) that intersect only for business-closure categories.
3. **Category names classify**; app bookings store `resource_id` so Outlook recoloring never changes capacity.
4. **Occupied interval ≠ customer time**; do not double-apply buffers to Outlook intervals that already include the full span.
5. **One authoritative source** per resource; visibility copies are display-only.
6. **Fail closed** when sync is stale/failed for slots that depend on Outlook.
7. **Code enforces; admin configures** — sleek forms, not a visual rules engine.

---

## Current production baseline (migration from)

| Today | Problem |
|-------|---------|
| One practitioner `availability[]` weekly schedule covers every active service | Salt inherits Nichole’s hours/busy |
| Outlook sync stores busy by `practitioner_id` and subtracts from all service slots | Discovery at 3pm blocks Salt at 3pm |
| Service catalog has `duration_minutes` only (customer face time) | Prep/recovery not modeled |
| No category → resource map | All busy treated as practitioner occupancy |

Key code today: `booking_use_case._candidate_slots_for_practitioner`, `outlook_sync.sync_outlook_connection`, `AvailabilityManagement.jsx`.

---

## Architecture (Phases 1–5 — implemented behind flag)

Phase 0 is **locked**. Scaffold + runtime paths for Phases **1–5** are **in tree** behind `MULTI_RESOURCE_SCHEDULING` (default **false**). Staging may run with the flag **true**; **production remains flag-off**. Remaining work is integrity/UI hardening ([#9](https://github.com/dagogodboss/naturepath/issues/9)), Entra consent ([#8](https://github.com/dagogodboss/naturepath/issues/8)), and Phase 6 **real** prove — not greenfield implementation.

### Data model (Phase 1)

**Design:** [phase-1-data-model.md](./phase-1-data-model.md) — scaffold + seed/backfill landed; runtime booking/Outlook use these collections when the flag is on.

- **`resources`**: `resource_id`, `type` (`practitioner` | `room`), `name`, `weekly_hours[]`, `timezone`, `active`, optional `linked_practitioner_user_id`.
- **`services`**: `required_resource_id`, `customer_duration_minutes` / `duration_minutes`, `prep_minutes`, `recovery_minutes`, optional narrower hours, `booking_window` / `min_notice`, flags (e.g. `no_mondays`).
- **`outlook_calendar_connections`**: per mailbox; `authoritative_for_resource_ids[]`, `visibility_only`, category **name** → `resource_id` map, `auth_mode`, sync status/error timestamps.
- **`resource_busy_intervals`**: from sync + app bookings; source (`outlook` | `booking` | `manual` | …); `authoritative`; exclude visibility copies from occupancy queries.
- **`bookings`**: store `resource_id`; customer start/end vs occupied start/end.
- **`review_queue`**: unmapped categories, sync races, conflicts needing admin attention.

### Slot engine (Phase 3)

- Generate candidates from **required resource hours** ∩ free occupied intervals (wired when flag on).
- At confirm: recheck resource; strengthen fail-closed / atomic reserve per [#9](https://github.com/dagogodboss/naturepath/issues/9) A1–A3 (not claimed complete).

### Admin API / UI (Phases 4–5)

- Four sections under Scheduling & Availability; schedule-change preview; “Why unavailable?” explainer (behind flag). Connection-mode staff clarity tracked in [#9](https://github.com/dagogodboss/naturepath/issues/9#issuecomment-6262127156).

---

## Resource model (simple)

```
[Discovery / Consults / Education] ──requires──► [Nichole]     (practitioner)
[Salt Session]                      ──requires──► [Salt room]  (room)

Same wall-clock time can be busy on one and free on the other.
Business-closure category → both busy.
```

Salt occupied 60 min (45 session + 15 cleanup); starts anytime room free (**locked**). Outlook: **Clients@**. Hours: M–F starts **10:30–17:00** (last start 5pm → occupied until 6pm).  
No Discovery/consults on Mondays; clients Tue–Fri from 10:30am; finish by 5:45pm; **last Discovery start 5:00pm** (**locked**).

---

## Category → resource rules

| Outlook category name | Blocks | Notes |
|----------------------|--------|-------|
| Discovery | Nichole | All practitioner services share this capacity |
| Consultation | Nichole | Same as Discovery |
| Salt | Salt room | Does not require Nichole |
| Business closure | Both | Holiday / clinic closed |
| Unclassified busy (Nichole auth calendar) | Nichole + review flag | Room stays free |
| Staff visibility copy | No occupancy | Prefer shared Clients@ calendar in Outlook; if copies exist on Nichole, recognise via `visibility_copy_category_names` / category map `visibility_only` (Salt Session / Salt) — never title/color, never ignore all unknown busy (#9 B3) |

**Locked:** Graph category **names**, not colors/titles. Colors may later decorate admin appointment cards only.

---

## Slot math (Jonathan durations)

| Service | Customer-visible | Occupied (resource) | Notes |
|---------|------------------|---------------------|--------|
| Discovery | 30 | 45 (30 + 15 break) | |
| Wellness | 60 | 90 (60 + 15 buffer + 15 break) | Buffer before vs after **open** |
| Extended | 120 | 145 (120 + 10 + 15) | |
| Follow-up | 30 | 45 (30 + 15) | |
| Salt | 45 (session) | 60 (45 + 15 cleanup) | App books 1hr room hold; **locked** |

- **App-created bookings:** apply prep/session/recovery from service config once.
- **Outlook-imported busy:** treat event interval as already-full occupation; do not add prep/recovery again.

---

## Sync & fail-closed behavior

1. Pull Microsoft Graph `calendarView` (pagination, recurring expansion, clinic timezone).
2. Respect `showAs` / cancelled (free & cancelled do not occupy).
3. Classify by category name → resource busy intervals.
4. Authoritative mailbox owns occupancy; visibility copies ignored for capacity.
5. Unmapped busy on Nichole auth → block Nichole + enqueue review; require Salt tagging.
6. On sync error: mark connection unhealthy; **fail closed** for availability that depends on Outlook.
7. Confirm path: recheck + reserve; race with manual Outlook → conflict flag for admin.
8. Schedule config changes: preview affected bookings; never silent cancel.

---

## Admin IA (v1) — what admins change without code

| # | Section | Admin can change |
|---|---------|------------------|
| 1 | Resources & hours | Create/edit staff & rooms; weekly hours; active; timezone |
| 2 | Services & durations | Required resource; customer/prep/recovery minutes; notice/window; optional narrower hours; no-Monday |
| 3 | Outlook connection & category mapping | Per mailbox connect; authoritative vs visibility-only; category name → resource |
| 4 | Availability preview & review | See why a slot is blocked; clear review items; watch sync status |

---

## UX references

*Mobbin MCP authenticated but requires a paid plan — patterns below from vendor docs. Re-query Mobbin screens when subscription is available.*

| # | App | Pattern | Why it fits Nature Path |
|---|-----|---------|-------------------------|
| 1 | Fresha | Per-service blocked / processing / extra time | Prep & recovery as service config, not a rules engine ([docs](https://www.fresha.com/help-center/knowledge-base/catalog/101630-add-extra-time-to-services-and-appointments-1)) |
| 2 | Fresha | Repeating weekly shifts per team member | Resources & hours without per-service calendars ([docs](https://www.fresha.com/help-center/knowledge-base/calendar/252-schedule-and-update-team-shifts)) |
| 3 | Square Appointments | Block extra time / processing duration on services | Customer duration ≠ occupied interval ([docs](https://squareup.com/help/us/en/article/6756-add-gap-times-to-your-square-appointments-services)) |
| 4 | Calendly | Troubleshoot → reason codes (CALENDAR, BUFFER, HOST…) | Template for “Why unavailable?” ([docs](https://calendly.com/help/how-to-troubleshoot-unavailable-times-that-should-be-available)) |
| 5 | Calendly | Before/after buffers; stacking caution | Aligns with prep/recovery + Outlook-length caution ([docs](https://calendly.com/help/how-to-use-buffers)) |
| 6 | Jane App | Rooms vs Resources; service requires N from a pool | Salt room + practitioners; generic multi-resource ([docs](https://jane.app/guide/putting-resources-to-work)) |
| 7 | Mindbody | Room schedule; unavailable rooms grayed | Multi-resource calendar + conflict visibility ([docs](https://support.mindbodyonline.com/s/article/203254103-Rooms-and-resources)) |
| 8 | Acuity | Outlook sync by showAs; app is availability SoT; padding not re-imported | Fail-closed posture; don’t double-apply buffers ([docs](https://help.acuityscheduling.com/hc/en-us/articles/16676868807181-Syncing-your-calendar)) |
| 9 | Outlook | Category **names** on events | Locked classification key ([docs](https://support.microsoft.com/en-us/outlook/use-categories-in-outlook)) |

**Design bar:** sleek admin forms (Fresha/Jane resource hours + Calendly “why unavailable”) — not a visual rules engine.

---

## Open questions for Jonathan (Phase 0)

**Status:** **LOCKED** (2026-10-18 Message 3)  
**Questionnaire:** [phase-0-jonathan-questions.md](./phase-0-jonathan-questions.md)

| # | Topic | State |
|---|--------|--------|
| Q1 | Salt exclusivity / occupied | **Locked** — 1 booking; ≤4 people; 45+15=60 |
| Q2 | Buffers / consult room | **Locked** — Nichole only; no consult room v1; Salt 1hr hold |
| Q3 | Nichole weekly hours | **Locked** — Tue–Fri from 10:30; finish by 5:45; **last Discovery start 5:00pm** |
| Q4 | Auth calendar / review blocking | **Locked** — Nichole mailbox for practitioner; Clients@ for Salt; mystery busy stays blocked until labeled; phone Outlook ≠ review queue |
| Q5 | Holidays | **Locked** — never Thanksgiving/Christmas; default both; admin can open others |
| Q6 | Salt last start / grid / calendar | **Locked** — Clients@; M–F starts 10:30–17:00; last start 17:00 (occupied to 18:00); anytime starts |
| Q7 | Reschedule SoT | **Locked B** — Outlook/office priority for free times; safer: busy sync + flag/conflict path (not silent payment rewrite) |

---

## Implementation phases (match Goal)

| Phase | Deliverable | Exit criteria |
|-------|-------------|-----------------|
| **0** | Lock Jonathan questions — **LOCKED** (2026-10-18) ([questionnaire](./phase-0-jonathan-questions.md)) | Answers recorded; Clients@ Salt; Discovery last start 5pm; Salt last start 5pm; Q7 B safer; mystery blocked until labeled |
| **1** | Data model — [phase-1-data-model.md](./phase-1-data-model.md) (**scaffold + seed/backfill; flag off in prod**) | Resources, service→resource, prep/session/recovery, category maps, authoritative source in schema |
| **2** | Outlook sync by category — [phase-2-outlook-category-sync.md](./phase-2-outlook-category-sync.md) (**wired behind flag**) | Busy intervals per resource; unmapped review queue; fail-closed sync |
| **3** | Slot generation & confirm — [phase-3-slot-engine.md](./phase-3-slot-engine.md) (**wired behind flag**) | Per-resource slots; confirm recheck/reserve; unit proof Discovery≠Salt blocking |
| **4** | Admin Scheduling UI — [phase-4-admin-ui.md](./phase-4-admin-ui.md) (**API + UI shell behind flag**) | Four sections live; safe schedule-change preview; sync status visible |
| **5** | Why unavailable + conflicts — [phase-5-why-unavailable.md](./phase-5-why-unavailable.md) (**explainer behind flag**) | Explainer API/UI; conflict alerts |
| **6** | Migrate + deploy + prove — [phase-6-migrate-prove.md](./phase-6-migrate-prove.md) (**staging checklist; human OAuth + flag**) | Staging then prod data migrated; live proof Salt bookable while Discovery occupies Nichole at same time CT |

### Suggested migration path (Phase 6)

1. Seed `resources` from current practitioner + new Salt room.
2. Attach services to resources (Discovery/consults → Nichole; Salt → room).
3. Dual-write busy intervals during rollout; feature-flag slot engine.
4. Map existing Outlook connection to Nichole authoritative; add Salt category map before enabling room occupancy from Outlook.
5. Cut over; run proof script: Discovery booked 15:00 → Salt still offers 15:00.

---

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Visibility copies double-count | Authoritative flag; ignore visibility-only in occupancy |
| Untagged Salt leaves room free | Require Salt category; review queue |
| Sync outage blanks bookability | Fail closed with clear sync status; admin manual block only |
| Buffer/Outlook double-count | Phase 0 lock; never add prep/recovery to imported intervals |
| Migration breaks existing bookings | Dual-read, preview, feature flag, proof checklist |
| Race with manual Outlook | Confirm recheck + conflict flag |

---

## Constraints

- GCP project **only** `project-990664b0-1bae-4746-88d` (account `admin@gcp.thenaturalpathla.com`).
- No Route53 / mail DNS changes; no SMTP enablement unless explicitly requested.
- Commits as **ilamini Dagogo** when committing; do not commit unless asked.
- Do not print secrets/tokens.
- Do **not** mark Goal complete until Phase 6 production proof.

---

## Success criteria

- [x] Phase 0 Jonathan answers recorded (Message 3 locked 2026-10-18)
- [x] Data model scaffold supports N practitioners / N rooms (flag-gated; staging seeded)
- [ ] Outlook category names drive **live** resource busy intervals (blocked on Entra [#8](https://github.com/dagogodboss/naturepath/issues/8))
- [ ] Unmapped / race items appear in admin review (with real sync)
- [ ] Fail closed on sync failure (intent; [#9](https://github.com/dagogodboss/naturepath/issues/9) A1 still open)
- [x] Admin four-section shell behind flag (staging); polish + connection-mode UX remaining
- [x] “Why unavailable?” explainer behind flag (staging)
- [ ] **Production** (America/Chicago): Discovery at 3pm does **not** block Salt at 3pm — requires real Outlook busy prove, **not** synthetic-only artifacts

---

## Goal objective (for CreateGoal)

Paste into CreateGoal `objective` (do not mark complete until Phase 6 proven):

```
Multi-resource scheduling & admin availability for Nature Path (The Natural Path LA).

Do NOT mark complete until every phase below is proven in production. Planning artifacts alone are not completion.

Phase 0 — Lock Jonathan questions (Salt exclusivity/setup; buffer before vs after; Outlook lengths; consult room; Nichole hours; authoritative vs Kristin visibility; holidays; Salt last start/grid; reschedule SoT).

Phase 1 — Data model: resources; service→resource; prep/session/recovery; category maps; authoritative source.

Phase 2 — Outlook sync by Graph category names → resource busy; unmapped review queue; fail-closed; no double-count visibility copies; showAs/recurring/pagination/timezone.

Phase 3 — Per-resource slot generation & confirm-time recheck/reserve; Discovery at 3pm must NOT block Salt at 3pm.

Phase 4 — Admin UI: (1) Resources & hours (2) Services & durations (3) Outlook & category mapping (4) Preview & review; safe schedule changes; sync status visible.

Phase 5 — Why unavailable + conflict alerts.

Phase 6 — Migrate single-schedule prod data; deploy; prove Salt≠Discovery blocking on America/Chicago.

Constraints: GCP project-990664b0-1bae-4746-88d only; no Route53/mail DNS changes; commits as ilamini Dagogo when committing; app bookings store resource assignment; colors never drive capacity.
```
