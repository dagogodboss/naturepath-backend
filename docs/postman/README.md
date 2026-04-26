# Postman — Natural Path Phase 2 payments E2E

Import `natural-path-payments.postman_collection.json` into Postman.

## Variables to set

- `baseUrl` — API root (e.g. `http://localhost:8000`).
- `accessToken` — customer bearer token (from `/api/auth/login`).
- `adminToken` — admin/practitioner bearer token (ops actions).
- `productId`, `serviceId`, `practitionerId` — seed these from the admin
  endpoints before running flow 1/2.
- `revelOrderId` / `revelTransactionId` — values you expect Revel to
  return. For local runs, populate these manually and point the synthetic
  webhook at an order you've already created in step 2.

## Running the flows

1. **Booking**: send `Initiate` → `Lock slot` → `Confirm booking` →
   `Mark paid at counter` (or leave for the hosted-link path). Use
   `Resend invoice` to reissue the email.
2. **Store**: `Create store order — card_online` → `Pay store order` →
   `Status check`. Or the `walk_in` variant to exercise HOLD path.
3. **Refund**: `Full refund` then `Partial refund`. Each call sends a
   fresh `Idempotency-Key` — retry the same request by fixing the header
   if you want to test duplicate-request dedupe.
4. **Reconciliation + webhook**: list reports, fire a synthetic
   `order.paid` webhook, replay it (expect `duplicate_ignored`), and send
   a bad-HMAC request (expect 401).

The synthetic webhook requests need a valid HMAC signature when the
server is configured with a real `REVEL_API_SECRET`. For local dev, set
`ALLOW_UNSIGNED_WEBHOOKS=true` in `.env` (NOT in production) and leave
the signature blank.

## Notes

- The collection ships with deterministic `event_id`s for replay tests.
  Clear them between full-flow runs, or the dedupe guard will keep
  returning `duplicate_ignored`.
- Walk-in refund requires an `Idempotency-Key` header (enforced server-
  side). The collection includes one via `{{$randomUUID}}`.
