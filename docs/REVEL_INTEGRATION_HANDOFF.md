# Revel Integration Handoff

Last updated: 2026-05-31

This is the working handoff for the next agent completing The Natural Path
Revel integration. Do not paste or commit real Revel secrets. The live keys live
only in `backend/backend/.env`, which is ignored by git.

## Read first

- `backend/backend/memory/PROJECT_MEMORY.md`
- `backend/memory/PRD.md`
- `backend/docs/ECOMMERCE_REVEL_PLAN.md`
- `backend/docs/REVEL_HOSTED_PAYMENT.md`
- `backend/docs/PAYMENT_RUNBOOK.md`

## Current verified state

- Business host: `thenaturalpathla.revelup.com`
- Backend env should use either:
  - `REVEL_SUBDOMAIN=thenaturalpathla`
  - or `REVEL_SUBDOMAIN=thenaturalpathla.revelup.com`
- Live product pull is verified through the WebOrders endpoint:
  - `GET https://thenaturalpathla.revelup.com/weborders/products/?establishment=1&limit=500`
  - Auth header: `API-AUTHENTICATION: <api_key>:<api_secret>`
  - Result observed locally: `2,157` products.
- Local Mongo `store_products` cache was synced to `2,157` active web products.
- `GET /api/store/products` returns cached products and hides `raw_revel_payload`.
- Regression test exists:
  - `backend/backend/tests/test_revel_live_client.py`

Important: `resources/Product/` returned `401` for this account. Do not switch
product sync back to `resources/Product/`.

## Current code paths

Backend:

- `backend/backend/infrastructure/external/revel_live_client.py`
  - Product sync now uses merchant `weborders/products`.
  - Legacy order/payment methods still use `/resources/Order/`,
    `/resources/OrderItem/`, and `/resources/Payment/`.
- `backend/backend/infrastructure/external/revel_service.py`
  - Facade over `RevelLiveClient`.
- `backend/backend/presentation/api/store_routes.py`
  - Store catalog, order creation, payment/checkout, admin ops.
  - `POST /api/store/admin/sync-revel-products` upserts Revel product cache.
- `backend/backend/infrastructure/external/payment_links.py`
  - Hosted payment link abstraction. Current Revel endpoint is still an
    assumption and remains feature-flagged.

SDK/frontend:

- `backend/sdk/src/api/endpoints.ts` exposes `storeApi`.
- `backend/sdk/src/hooks/useStore.ts` exposes store hooks.
- Frontend store screens live under:
  - `frontend/src/pages/customer/ProductStore.jsx`
  - `frontend/src/pages/customer/ProductDetail.jsx`
  - `frontend/src/pages/customer/StoreCheckout.jsx`
  - `frontend/src/pages/customer/StoreOrders.jsx`
  - `frontend/src/pages/practitioner/StoreOperations.jsx`

## Environment flags

Keep these disabled until the specific live contracts are verified:

```env
REVEL_ENABLE_HOSTED_PAYMENTS=false
REVEL_ENABLE_HOLD_ORDERS=false
```

Product sync only needs:

```env
REVEL_API_KEY=...
REVEL_API_SECRET=...
REVEL_ESTABLISHMENT_ID=1
REVEL_SUBDOMAIN=thenaturalpathla
```

## Safe verification commands

Run from `backend/backend`:

```bash
.venv/bin/python -m pytest tests/test_revel_live_client.py
```

Read-only live product probe:

```bash
.venv/bin/python - <<'PY'
import asyncio
from core.config import get_settings
from infrastructure.external.revel_service import RevelService

async def main():
    products = await RevelService(get_settings()).get_all_products()
    print("product_count=", len(products))
    for p in products[:5]:
        print(p["product_id"], p["name"], p["price"], p.get("stock_qty"))

asyncio.run(main())
PY
```

Local cache check:

```bash
.venv/bin/python - <<'PY'
import asyncio
from infrastructure.database import Database

async def main():
    await Database.connect()
    try:
        db = Database.get_db()
        print("store_products=", await db.store_products.count_documents({}))
        print("active_web=", await db.store_products.count_documents({"is_active_web": True}))
    finally:
        await Database.disconnect()

asyncio.run(main())
PY
```

## Remaining integration work

### 1. Product sync hardening

The first pass works. Improve it without changing the verified endpoint.

- Add pagination if Revel caps `limit=500`; current result returned all 2,157
  products, but verify whether this is stable or if `page`/offset is needed.
- Decide how to represent categories. Current category is the numeric
  `id_category` from Revel. If user-facing category names are required, discover
  and sync the WebOrders category/menu endpoint instead of inventing names.
- Decide web visibility rules. Today every synced product is set
  `is_active_web=true`. If Revel has a "show online" or menu availability flag,
  map that instead.
- Decide stock display. Revel returns negative `stock_amount` for many products.
  Do not block purchases solely because stock is negative until business rules
  are confirmed.

### 2. Order/payment contract discovery

Do not start by POSTing a live order. The current legacy resource probes showed:

- `GET /resources/Order/?limit=1` -> `401`
- `GET /resources/OrderItem/?limit=1` -> `401`
- `GET /resources/Payment/?limit=1` -> `401`
- `GET /resources/Customer/?limit=1` -> `401`

This means the existing checkout implementation is not safe to enable as-is.

Revel docs point to WebOrders cart endpoints for ecommerce:

- `POST /specialresources/cart/validate`
- `POST /specialresources/cart/calculate`
- `POST /specialresources/cart/submit`

Build a small diagnostic client first, preferably as a script or isolated
methods on `RevelLiveClient`, to capture redacted responses from validate and
calculate. Only call `submit` after the owner approves a live test product/order.

Questions to answer from the live contract:

- Exact request body for `validate` and `calculate`.
- Required cart fields: `skin`, `establishmentId`, `items`, `orderInfo`,
  `notifications`, `serviceFees`, `discounts`, `paymentInfo`.
- Product id field expected in cart item payload.
- Whether delivery address/contact fields are accepted in `orderInfo`.
- Whether price override is allowed or Revel recomputes from catalog.
- Whether cart submit can create a payment-pending order without card capture.
- What order id/reference field comes back from `submit`.
- What payment-related fields come back for card, cash/walk-in, or payment link
  flows.

### 3. Replace checkout's legacy order path

Once WebOrders cart validate/calculate/submit are verified:

- Add explicit methods to `RevelLiveClient`, for example:
  - `validate_cart(...)`
  - `calculate_cart(...)`
  - `submit_cart(...)`
- Keep product sync and order/payment flows separate. Product sync uses
  `/weborders/products`; checkout likely uses `/specialresources/cart/...`.
- Update `RevelService.create_order(...)` or add a new store-specific method so
  `store_routes.py` no longer depends on `/resources/Order/` for store checkout.
- Preserve idempotency where possible. If Revel WebOrders submit has no native
  idempotency header, guard idempotency in Mongo before making the submit call.
- Normalize the submit response into the existing app shape:
  - `revel_order_id`
  - `subtotal`
  - `tax`
  - `total`
  - `payment_status`
  - `fulfillment_status`
  - `timeline`

### 4. Hosted payment and HOLD decisions

Current docs mention hosted payment links and HOLD orders, but those contracts
are not verified for this account.

Do not set these true until verified:

```env
REVEL_ENABLE_HOSTED_PAYMENTS=true
REVEL_ENABLE_HOLD_ORDERS=true
```

If Revel WebOrders submit can return a payment link or payment-pending order,
prefer that over the speculative `HostedPaymentLink` resource. If not, keep
`PaymentLinkProvider` and implement a confirmed provider only after Revel
support gives the exact endpoint/response.

For walk-in/HOLD:

- Confirm whether WebOrders supports draft/hold orders.
- Confirm whether inventory is decremented on submit, on payment, or on
  fulfillment.
- Confirm cancel/expire semantics.
- Only then wire `expire_walk_in_holds`.

### 5. Webhooks and payment response capture

Existing webhook infrastructure is hardened for idempotency:

- `backend/backend/presentation/api/webhook_routes.py`
- `backend/docs/WEBHOOK_AUDIT_D1.md`
- `backend/docs/WEBHOOK_AUDIT_D3.md`

Need to confirm live Revel event names and payloads for this account:

- order paid/captured
- payment failed
- refund created
- order cancelled
- order submitted/finalized

Capture full redacted payload samples in a non-secret fixture or doc. Then map
them to the existing handlers instead of guessing.

### 6. Frontend/SDK follow-through

After backend checkout is corrected:

- Ensure `storeApi.createOrder`, `storeApi.payOrder`, and status polling match
  the backend response shapes.
- Exercise:
  - `/store` product browse
  - `/store/product/:productId`
  - `/store/checkout`
  - `/store/orders`
  - `/store/ops`
- Keep `page_size <= 48`; SDK already clamps this.

## Definition of done

The integration is complete when all of these are true:

- Product sync pulls the full Revel catalog repeatedly without 401s.
- Store products show in customer and staff UIs from cached data.
- Checkout creates the correct Revel-side order using a verified endpoint.
- App order state stores the real Revel order reference.
- Payment mode behavior is verified:
  - card online/payment link, or explicitly disabled
  - walk-in/HOLD, or explicitly disabled
- Webhook or status reconciliation flips payment state from pending to captured.
- Refund/void behavior is either verified end-to-end or disabled with clear UI/API
  errors.
- Tests cover product normalization, checkout response normalization, and the
  webhook/status transition used in production.
- Docs and memory files are updated after final verification.

## Useful Revel docs

- How to make an API call:
  `https://developer.revelsystems.com/revelsystems/docs/how-to-make-an-api-call`
- WebOrders products:
  `https://developer.revelsystems.com/revelsystems/reference/getproducts`
- Cart validate:
  `https://developer.revelsystems.com/revelsystems/reference/validatecart-1`
- Cart calculate:
  `https://developer.revelsystems.com/revelsystems/reference/calculatecart-1`
- Cart submit:
  `https://developer.revelsystems.com/revelsystems/reference/submitcart-1`
