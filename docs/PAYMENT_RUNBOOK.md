# Payment Runbook (Phase 2)

This document is the operator-facing reference for the Natural Path payment
flows — what the system does, what state it leaves behind, and how to
respond when something goes wrong.

## 1. Lifecycle overview

### Store orders

1. Customer creates order with `payment_mode` of either `card_online` or
   `walk_in`.
2. `POST /api/store/checkout/orders/{id}/pay` branches on mode:
   - **card_online** — we create a Revel order, create a hosted pay link,
     email the link, and set `payment_status = "awaiting_payment"`.
   - **walk_in** — we create a Revel HOLD order (feature-flagged behind
     `REVEL_ENABLE_HOLD_ORDERS`) with a 24h `hold_expires_at`, and set
     `payment_status = "awaiting_counter"`.
3. A Revel webhook `order.paid` (or `payment.captured`) flips the order to
   `captured` and our branded receipt email goes out (idempotent via
   `receipt_sent_at` CAS). The `payment_events` ledger records a
   `captured` row.
4. Walk-in HOLDs not collected within 24h are swept by the
   `expire_walk_in_holds` Celery task (every 15 min), which cancels the
   Revel HOLD and sets `payment_status = "expired"`.

### Bookings

1. Customer confirms a booking (`/api/booking/confirm`).
2. If `REVEL_ENABLE_HOSTED_PAYMENTS=true`, `issue_booking_invoice` is
   queued. It creates a Revel order, a hosted pay link, and emails the
   invoice. Booking is tentatively flipped to
   `payment_mode = "card_online", payment_status = "awaiting_payment"`.
3. Customer pays online → webhook flips booking to `captured` and fires
   `send_booking_receipt`. Alternatively the practitioner hits
   `/api/booking/{id}/mark-paid-at-counter` with a `revel_receipt_id`;
   booking flips to `payment_mode = "walk_in", payment_status = "captured"`
   and the pay link is cancelled.
4. Practitioner can `POST /api/booking/{id}/invoice/resend` to re-send the
   same invoice (if the link is still active) or mint a new one.

### Refunds (store)

- Card refund: `POST /api/store/admin/orders/{id}/refund` with an
  `Idempotency-Key` header. Runs through Revel. Partials accumulate in
  `refunds[]`. SLA: 3 business days (`expected_completion_at`).
- Walk-in refund: same endpoint + header. Skips Revel; stamps a
  `manual_refund` entry with a practitioner user id.
- Void (pre-capture): `POST /api/store/admin/orders/{id}/void`. Cancels the
  hosted link + Revel order with no refund call.
- Every refund state change appends to the `payment_events` ledger.

### Webhooks

- Revel webhook lands on `/webhooks/revel`.
- HMAC verification is fail-closed:
  - Prod/staging: real `REVEL_API_SECRET` required (500 otherwise).
  - Non-prod: still 401 unless `ALLOW_UNSIGNED_WEBHOOKS=true`.
- Dedupe is keyed on `(provider, event_id)` with a synthetic `sha256:<body>`
  fallback when the sender omits `event_id`.
- Handlers use conditional Mongo updates so replays, out-of-order
  deliveries, and late/stale events cannot regress terminal states.

## 2. Common incidents

### "Customer says they paid but the app says pending"

1. Fetch the order / booking. If `payment_status in {awaiting_payment,
   processing, pending}` and we have a `revel_order_id`:
   - `GET /api/store/orders/{id}/status` (or
     `/api/booking/{id}/payment/status`). It re-reads Revel and reconciles
     our state if the provider reports the order as paid.
2. If Revel reports captured but our DB is still pending, the
   reconciliation sweeper (daily) will raise a row in
   `reconciliation_reports`. You can see it at
   `GET /api/admin/reconciliation/reports?date=YYYY-MM-DD`.
3. If Revel says "unknown", escalate to finance — do NOT flip our state
   manually. The `backfill-revel-tx` endpoint is the only supported way to
   associate a historical `revel_transaction_id` with an order.

### "Refund request returned 502 — did money move?"

- Check the order's `timeline` for a `refund_reconciliation_required`
  entry with the provider status.
- Check the `refund_reservations` array — any entry with
  `status: "reconciliation_pending"` means we deliberately left the
  reservation live because the provider outcome was uncertain. Do NOT
  retry the refund with a different `Idempotency-Key`; retry with the
  same header so Revel dedupes.
- A Celery beat task runs **`sweep_store_refund_reconciliation` every 30
  minutes** (see `workers/refund_reconciliation_worker.py`). It re-calls
  Revel with the **same** card dedupe id, applies Mongo accounting when the
  provider now succeeds, and releases the reservation if the refund id was
  already recorded (duplicate race). After many failed sweeps it writes one
  `reconciliation_reports` row (`refund_reconciliation_sweep_exhausted`) per
  stuck attempt (guarded by `sweep_exhaust_reported` on the reservation).
- If finance confirms the money did move, resolve via the admin
  reconciliation UI (`POST /api/admin/reconciliation/reports/{id}/resolve`)
  once the state has been corrected in the DB.

### "Customer got two receipts"

- Idempotency is keyed on `receipt_sent_at` (store) and
  `booking_receipt_sent_at` (booking). Duplicate receipts in the same
  order/booking should not happen after C5/C6 land. If you see them:
  - Check for a replay where `event_id` was missing AND body differed
    enough to generate a different `sha256` hash.
  - File a ticket with the timeline entries for both events.

### "Webhook never seems to arrive"

- Check `webhook_events` for the order id's `revel_order_id`. If there's a
  row with `processed: false` older than 5 minutes, something crashed
  mid-processing — replaying the webhook (new claim after the stale
  window) will re-run the handler.
- Without the row entirely, Revel either failed to deliver or is hitting
  a different environment. Cross-check Revel's webhook log + our access
  log.

## 3. Feature flags + env knobs

| Variable | Default | Purpose |
|---|---|---|
| `REVEL_ENABLE_HOSTED_PAYMENTS` | `false` | Gates online pay-link generation. |
| `REVEL_ENABLE_HOLD_ORDERS` | `false` | Gates HOLD-order creation for walk-in. |
| `ALLOW_UNSIGNED_WEBHOOKS` | `false` | Dev-only bypass for webhook HMAC. |
| `REVEL_HOSTED_PAYMENT_ENDPOINT` | `HostedPaymentLink` | Revel resource name. |
| `REFUND_SLA_BUSINESS_DAYS` | `3` | SLA stamp on refunds. |
| `STORE_TAX_RATE` | `0.0925` | Used to validate Revel-returned tax. |
| `OPS_EMAIL` | *(unset)* | Daily reconciliation drift summary. |

## 4. Celery scheduled jobs

- `release-expired-slot-locks` — every 60s.
- `expire-walk-in-holds` — every 15 min; cancels pending Revel HOLDs.
- `reconcile-revel-orders` — daily; writes to `reconciliation_reports`.
- `send-booking-reminders` — hourly.

## 5. Useful shell snippets

```shell
# How many unresolved reconciliation drifts today?
curl "$API/api/admin/reconciliation/reports?resolved=false" | jq '.total'

# Back-fill a historical order's Revel transaction id (admin only).
curl -X POST "$API/api/store/admin/orders/$ORDER_ID/backfill-revel-tx" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"revel_transaction_id": "tx_12345"}'

# One-time non-destructive money migration (additive *_cents fields).
python -m scripts.migrate_money_to_cents --dry-run
python -m scripts.migrate_money_to_cents
```

## 6. Where things live

- `backend/backend/presentation/api/store_routes.py` — store checkout + admin refund + void + backfill + status endpoints.
- `backend/backend/presentation/api/booking_routes.py` — booking payment endpoints (invoice/resend, mark-paid-at-counter, payment status).
- `backend/backend/presentation/api/webhook_routes.py` — Revel webhook dispatcher + per-event handlers.
- `backend/backend/infrastructure/external/payment_links.py` — hosted-payment provider abstraction.
- `backend/backend/infrastructure/payment_events.py` — ledger writer.
- `backend/backend/workers/reconciliation_worker.py` — daily drift job.
- `backend/backend/workers/store_worker.py` — walk-in HOLD reaper.
- `backend/backend/workers/booking_invoice_worker.py` — auto-invoice task.
