# Revel Hosted Payment + HOLD Spike (A1)

## Scope

This spike validates two contracts we need before implementing Phase 2 payment flows:

1. Hosted payment link support in Revel (for online card flow).
2. Draft/HOLD order semantics in Revel (for walk-in flow with 24h expiration).

## Current codebase findings

- `RevelLiveClient` currently supports:
  - `POST /resources/Order/`
  - `POST /resources/OrderItem/`
  - `GET /resources/Order/{id}/`
  - `POST /resources/Payment/`
  - `GET /resources/Payment/{id}/`
- There is no hosted-link method and no explicit hold/cancel order method in:
  - `backend/backend/infrastructure/external/revel_live_client.py`
- Existing store payment-link route is a placeholder URL, not Revel-backed:
  - `backend/backend/presentation/api/store_routes.py` (`send_order_sms_pay_link`)

## Revel contract assumptions to verify

The implementation must not proceed on assumptions. We need to verify these against the merchant sandbox:

### A. Hosted payment link creation

Need confirmed endpoint and response fields for:

- Creating a hosted payment URL linked to a Revel order.
- Response fields:
  - provider link id
  - hosted URL
  - expiration timestamp
  - linked order reference
- Failure states:
  - link disabled for account
  - order in invalid state
  - amount mismatch

### B. HOLD/draft order behavior

Need confirmed endpoint or fields for:

- Creating an order in HOLD/draft state.
- Ensuring HOLD does **not** decrement inventory until capture/close.
- Cancelling HOLD order before fulfillment.
- Auto-expiration behavior (native Revel) or requirement to expire from our side.

## Probe checklist (run against sandbox account)

Use API auth headers already used in client:

- `API-AUTHENTICATION: {API_KEY}:{API_SECRET}`
- `Content-Type: application/json`
- `Accept: application/json`

### 1) Baseline order probe

- Create order (`POST Order/`)
- Add line (`POST OrderItem/`)
- Read order (`GET Order/{id}/`)
- Record full response JSON for status/state fields.

### 2) Hosted payment probe

- Attempt hosted-link creation endpoint provided by Revel support docs.
- Capture:
  - status code
  - full response JSON
  - which field is the public checkout URL
  - whether link is reusable
  - expiration behavior

### 3) HOLD probe

- Create HOLD/draft order using Revel-supported field/endpoint.
- Validate inventory before/after with product stock endpoint.
- Attempt conversion to paid order and observe transitions.
- Attempt cancel of HOLD and confirm inventory behavior.

### 4) Webhook probe

- Confirm webhook event names and payload fields for:
  - payment captured
  - payment failed
  - refund created
  - hold/order expired (if available)
- Confirm signature algorithm and signing input:
  - body-only HMAC SHA256 vs timestamp-prefixed scheme.

## Decision gate

Implementation for A2+ proceeds only when all are true:

- Hosted pay link endpoint is confirmed and returns stable URL field.
- HOLD/draft semantics are confirmed and inventory-safe.
- Cancel/expire path for HOLD is confirmed.
- Webhook payload + signature contract are confirmed.

If any of the above is not available in this Revel account, fallback is:

- Keep `PaymentLinkProvider` abstraction.
- Implement alternate provider in next phase (Stripe Payment Links) while preserving API contract in our app.

## Notes for follow-up tasks

- A2 should add `PaymentLinkProvider` and `RevelHostedPaymentProvider` only after endpoint contract is confirmed.
- B2/B3 should implement HOLD creation/cancellation only with verified Revel fields, not guessed ones.
- D1 should reconcile webhook signature logic with the exact Revel signing contract from probe results.
