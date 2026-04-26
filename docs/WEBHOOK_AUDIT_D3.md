# Webhook Idempotency Attestation — D3

All webhook handlers in `backend/backend/presentation/api/webhook_routes.py`
use conditional Mongo updates (`update_one` / `update_many` with `$in`/`$nin`
/`$expr` pre-state filters). No handler performs an unconditional `$set` of
payment state. If a handler's filter does not match, the update is a no-op and
the caller observes `modified_count == 0` so it can decide whether to fall
back to other paths (as the `order.paid` primary/legacy split does).

## Per-handler attestation

### `_handle_order_paid` → `_flip_booking_to_captured`
- Booking capture: filter `status ∈ {pending, confirmed, in_progress}` AND
  `payment_status ∈ {none, awaiting_payment, awaiting_counter, null}`.
- Store order sync: filter `payment_status ∈ {pending, processing,
  awaiting_payment, awaiting_counter}`.
- Legacy booking fallback: filter
  `status ∈ {pending, confirmed}` AND
  `payment_status $nin {captured, refunded, voided, failed}`.

### `_handle_payment_failed`
- Store order: filter `payment_status ∈ {pending, processing,
  awaiting_payment}`.
- Booking: filter `payment_status ∈ {awaiting_payment}`.
- Payment link: filter `status $nin {paid, refunded, cancelled, voided}`.

### `_handle_refund_created`
- Store order: filter `revel_refund_ids $ne refund_id` AND
  `payment_status ∈ {captured, partial_refunded}` AND the `$expr` cap so
  `refund_amount + amount <= total + 0.01`. Status transitions
  (`partial_refunded` / `refunded`) are derived after the `$inc` via two
  subsequent `$expr`-guarded updates.
- Booking: same pattern keyed on `booking_refund_ids` with
  `payment_amount || total_price` as the cap.

### `_handle_order_refunded` (legacy)
- Runs only when `_handle_refund_created` did **not** apply (the dispatcher
  inspects its return value). Conditional update filter excludes terminal
  states: `status $nin {refunded, voided, failed}`.

### `_handle_hold_expired`
- Filter: `payment_status == awaiting_counter`. Expired rows cannot be
  re-stamped.

### `_handle_order_cancelled`
- Filter: `status ∈ {pending, confirmed}` so terminal states
  (`cancelled`, `completed`, `no_show`, `in_progress`) are preserved.

### `_handle_order_status_sync` (`order.finalized` / `order.updated`)
- Allow-lists on untrusted `payment_status` / `fulfillment_status` /
  `status` fields prevent arbitrary strings from landing in Mongo.
- `$nin` guard against regressing terminal store orders
  (`captured, refunded, partial_refunded, voided` for payment;
  `refunded, fulfilled, cancelled, rejected` for fulfillment).

## Dispatcher idempotency

- `_claim_event_id` atomically upserts a `webhook_events` row keyed on the
  unique `(provider, event_id)` index. Concurrent deliveries either win the
  upsert (`new`) or see `duplicate` / `in_flight` / `retry_claim`.
- Receipt send helpers (`_send_booking_receipt_if_new`,
  `_send_single_store_receipt`) each perform a CAS on their own
  in-progress flag with a stale-claim reset so crashed sends don't
  permanently block a retry.

This covers D3. No code change required beyond what C5 / D2 already landed.
