# Plan: Revel-linked ecommerce (order–inventory, no online checkout)

**Goal:** Practitioners see **Revel POS products**; **guests and signed-in clients** browse those products and submit **orders** with a **delivery address**. **Payment is not collected in the web app** — staff record payment in **Revel / back office**. The system behaves as an **order + inventory coordination** layer, not a card-present storefront.

**Current state:** `RevelService` in `backend/backend/infrastructure/external/revel_service.py` is a **mock** (in-memory products/orders). Webhooks exist under `presentation/api/webhook_routes.py` for future real Revel events. **No product catalog UI** exists yet for guest or practitioner (previously deferred).

---

## 1. Product principles

| Principle | Decision |
|-----------|----------|
| Source of truth for **SKU, price, tax** | Revel POS (synced into our DB as a cache with `revel_product_id`) |
| Web checkout | **Disabled** — no Stripe/card in guest flow |
| Payment | **Back office / Revel** — order marked `payment_pending` until staff confirms |
| Inventory | Reflect Revel (or local reserved qty) — define whether decrements happen on **order submit** vs **payment confirmed** |
| Delivery | Required fields on order: name, phone, line1, line2?, city, state, postal, country, instructions? |

---

## 2. Roles & surfaces

### 2.1 Practitioner (authenticated)

- **Catalog browser:** List products synced from Revel (search, category if Revel exposes it).
- **Read-only awareness:** See which products are **active** on Revel / flagged for web display (if you add a “show on web” flag in Revel custom field or mapping table).
- **Order queue:** List **open web orders** assigned to location/practitioner (filter by status: `submitted`, `payment_pending`, `fulfilled`).
- **Actions:** Mark **ready for pickup / shipped**, add internal note, **link to Revel order** once created manually or via API.
- **Optional:** Trigger “create draft order in Revel” from our UI (if Revel API supports it) for back-office completion.

### 2.2 Guest / client (anonymous or customer account)

- **Storefront:** Product grid/detail from cached Revel catalog (only items marked available for web).
- **Cart:** Session or account-bound cart (Redis + anon session id or `customer_id`).
- **Checkout form:** Delivery address + contact + order notes — **no payment fields**.
- **Confirmation:** Order id + copy: “You will be contacted for payment” / “Pay at pickup per staff instructions.”

### 2.3 Admin / back office

- Reconcile payments in Revel; update order status in our app via admin API or webhook from Revel (`order.paid` already stubbed in webhook route).
- Override / cancel orders; handle refunds outside web.

---

## 3. Backend work (phased)

### Phase E1 — Data model & API (TDD recommended)

- **Collections (or tables):**  
  - `revel_product_cache` — `revel_product_id`, name, price, category, `updated_at`, `is_active_web`, raw payload JSON.  
  - `web_orders` — id, `customer_id` nullable, items[], delivery address object, status enum, `revel_order_id` nullable, timestamps, staff notes.
- **Endpoints (examples):**  
  - `GET /api/store/products` — public, paginated, only `is_active_web`.  
  - `POST /api/store/cart/...` — optional if cart server-side.  
  - `POST /api/store/orders` — guest or auth; validates address; creates `web_orders` status `submitted`.  
  - `GET /api/store/orders/mine` — customer.  
  - `GET /api/practitioner/store/orders` — practitioner scoped.  
  - `PATCH /api/admin/store/orders/{id}` — status transitions.
- **Sync job:** Celery task `sync_revel_products` (hourly) calling real Revel API when implemented; until then, extend mock or CSV import for demos.

### Phase E2 — Real Revel integration

- Replace mock `RevelService` with HTTP client to Revel’s API (per your Revel contract: establishment, OAuth/API key).
- Map Revel product → `revel_product_cache`; handle webhooks for inventory and payment events to update `web_orders`.
- **Idempotency** on webhooks (store `event_id`).

### Phase E3 — Inventory rules

- Decide: **soft reserve** on submit vs **hard decrement** only when staff confirms payment in Revel.  
- Document conflict handling if Revel shows out-of-stock after web submit.

---

## 4. SDK work

- Types: `StoreProduct`, `WebOrder`, `DeliveryAddress`, `OrderStatus`.
- Hooks: `useStoreProducts`, `useCreateWebOrder`, `usePractitionerStoreOrders`, `useMyWebOrders`.
- Reuse `NaturalPathProvider` base URL and auth headers.

---

## 5. Frontend work

| Screen | Owner | Notes |
|--------|--------|------|
| `/shop` or `/store` | Guest/client | PLP + PDP from `useStoreProducts` |
| Cart + checkout | Guest/client | Address form; call `useCreateWebOrder` |
| `/practitioner/orders` or under reporting | Practitioner | Queue + detail drawer |
| Admin | Admin | Full list, status edits, sync trigger button |

**Accessibility:** Form labels, error states, mobile-first (match existing 428px layout patterns).

---

## 6. Security & compliance

- **PII:** Address data encrypted at rest (Mongo encryption or KMS for sensitive fields if required).
- **Rate limit** `POST /api/store/orders` (per IP + per account).
- **Admin/practitioner** routes: role checks consistent with existing `get_current_practitioner` / admin deps.
- **No card data** in our DB or logs.

---

## 7. Milestones (suggested order)

1. **M1:** Schema + `GET /api/store/products` + seed from mock Revel list + minimal guest PLP (frontend).  
2. **M2:** `POST /api/store/orders` + confirmation page + practitioner order list (read-only).  
3. **M3:** Webhook handling to flip order status when Revel reports paid.  
4. **M4:** Real Revel API sync + hardening + observability (CloudWatch, alerts on sync failure).

---

## 8. Open decisions (fill before build)

- [ ] Single establishment vs multi-location Revel.  
- [ ] Guest checkout allowed or **sign-in required** to order.  
- [ ] Whether practitioners **create** Revel products from web (probably **no** — keep Revel as master).  
- [ ] Tax/shipping: display **estimate** only vs **final in Revel**.

---

## 9. References in repo

- `backend/backend/infrastructure/external/revel_service.py` — mock Revel.  
- `backend/backend/presentation/api/webhook_routes.py` — `/webhooks/revel`.  
- `backend/backend/presentation/api/service_routes.py` — `sync-revel` (admin).  
- [`../memory/PRD.md`](../memory/PRD.md) — overall backlog.
