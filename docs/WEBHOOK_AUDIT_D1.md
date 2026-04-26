# Webhook Hardening — D1 Audit (Revel)

This is the audit deliverable for Phase 2 / D1. All findings confirmed against
the post-C5 state of the code.

## Verified guarantees

### 1. Signature verification is fail-closed

- HMAC scheme: `hmac.new(settings.revel_api_secret, body, sha256).hexdigest()`
  compared with `hmac.compare_digest` to the `X-Revel-Signature` header.
- Body-only signing: no timestamp prefix. If Revel rolls out a timestamped
  scheme later, `verify_revel_signature` is the single place to update.
- Production/staging with unset or placeholder (`mock_revel_secret`) secret
  returns **500** ("Webhook secret not configured") — never accepts the
  request. See `backend/backend/presentation/api/webhook_routes.py`
  `_require_signature_or_dev_bypass`.
- Any env with a real secret must present a valid signature or is **401**.
- Non-prod envs with a placeholder secret are also **401** unless the
  explicit `ALLOW_UNSIGNED_WEBHOOKS=true` dev flag is set.

### 2. Event deduplication

- `webhook_events` collection with unique index on `(provider, event_id)`.
  See `backend/backend/infrastructure/database/mongodb.py` (unique compound
  index).
- Handler inserts a `processed=false` row on receipt, processes in a
  background task, then flips `processed=true` only after success.
- Duplicate deliveries observe either:
  - `processed=true` → returns `{status: "duplicate_ignored"}`; or
  - `processed=false` (in-flight) → returns `{status: "in_flight"}`.
- Event IDs: uses `payload.event_id` when present. When Revel does not
  supply one, a synthetic id `sha256:<hex-of-body>` is generated so that
  byte-identical replays still dedupe.

### 3. Timestamp skew check

- Configurable `revel_webhook_tolerance_seconds` (default 300s). Events
  whose `timestamp` / `event_created_at` drift beyond the tolerance window
  are rejected with **400**.
- `received_at` + `event_timestamp` are both persisted on every
  `webhook_events` row.
- TTL index on `received_at` retires rows after
  `revel_webhook_replay_ttl_seconds` (default 86400s).

### 4. Handler safety (idempotent writes)

- `order.paid` booking path: CAS update with
  `status ∈ {pending, confirmed, in_progress}` **and**
  `payment_status ∈ {none, awaiting_payment, awaiting_counter, null}`. A
  terminal booking (cancelled/completed/refunded/captured) cannot be flipped.
- `order.paid` legacy fallback: CAS update with
  `status ∈ {pending, confirmed}`. Cannot resurrect a cancelled booking.
- `order.paid` `store_orders` sync: CAS update with
  `payment_status ∈ {pending, processing, awaiting_payment, awaiting_counter}`.
- `order.cancelled`: CAS update with `status ∈ {pending, confirmed}` —
  cannot clobber `completed` / `no_show`.
- `order.finalized / order.updated`: uses allow-lists for
  `payment_status` / `fulfillment_status`; `$nin` guard against terminal
  states (`captured`, `refunded`, `partial_refunded`, `voided` /
  `refunded`, `fulfilled`, `cancelled`, `rejected`).
- Store receipt sends are CAS-claimed on `receipt_sent_at`/`receipt_send_in_progress`.
- Booking receipt sends are CAS-claimed on
  `booking_receipt_sent_at`/`booking_receipt_send_in_progress`, with a 10-minute
  stale-claim recovery so crashes cannot permanently block a receipt.

## Out-of-scope (tracked elsewhere)

- Additional event types beyond `order.{paid, refunded, cancelled, finalized, updated}`
  (e.g. `refund.created`, `payment.failed`, `order.hold_expired`): **D2**.
- Body-hash dedupe fallback + atomic claim + background processing (these are
  already in place as listed above; D1 also confirmed present).
- Pytest coverage for webhook-before-pay race: **D4**.
