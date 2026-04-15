# Naturepath — project memory (for assistants)

This file lives at **`backend/memory/PROJECT_MEMORY.md`** inside the **backend** git repo. The **frontend** app lives in the sibling **`../frontend`** repo (same parent folder as this repo).

The umbrella parent folder **`naturepath/`** is **not** a single git root. Treat **`frontend/`** and **`backend/`** (this repo) as separate repositories.

## Product context

- **The Natural Path** — booking (services, practitioners, appointments) plus a **Revel-synced product store** (catalog, cart, checkout, orders).
- **Staff / admin store UI**: **`StoreOperations`** at **`/store/ops`** (not labeled “Product Management” in the UI). Roles: `admin`, `owner`, `practitioner`, `manager`, `staff` (see `RequireAuth` in `frontend/src/App.jsx`).
- **Customer store**: **`/store`** (grid), **`/store/product/:productId`** (detail), **`/store/checkout`**, **`/store/orders`** (auth).

## Key paths

Paths below are from the **frontend** repo unless noted.

| Area | Path |
|------|------|
| Routes | `frontend/src/App.jsx` |
| Bottom nav + Store tab | `frontend/src/components/BottomNav.jsx` |
| Store pages | `frontend/src/pages/customer/ProductStore.jsx`, `ProductDetail.jsx`, `StoreCheckout.jsx`, `StoreOrders.jsx` |
| Staff store ops | `frontend/src/pages/practitioner/StoreOperations.jsx` |
| API errors / validation | `frontend/src/lib/clientErrors.js` |
| Store analytics (POST to API) | `frontend/src/lib/storeAnalytics.js` |
| Store API (backend) | `backend/presentation/api/store_routes.py` |
| SDK store | `sdk/src/hooks/useStore.ts`, `sdk/src/api/endpoints.ts` (`storeApi`) |

## API constraints (do not regress)

- **`GET /api/store/products`**: query param **`page_size`** must be **`≤ 48`** (backend `le=48`). The SDK **`storeApi.getProducts`** clamps `page_size` to **1–48** in `endpoints.ts`.
- **Address `country`**: backend expects a **2-character** code (e.g. `US`, `NG`), not full country names.

## Session work logged (consolidated)

### Store discovery & navigation

- Documented that **product management** lives under **Store Operations** at **`/store/ops`**; added a **Store** item to **`BottomNav`** for roles that can access that route (after Services; Access before Reports for owner/admin).

### Store UI / UX

- Redesigned **ProductStore**, **StoreCheckout**, **StoreOrders**, **StoreOperations** (layout, skeletons, badges, sticky CTAs, KPI + tabs on ops).
- **Product detail** (`ProductDetail.jsx`): hero image, pricing, “about” block, related products, quantity + add to cart; loads **one product via `storeApi.getProductsByIds`** (not a huge list query). Related products use **`getProducts({ category, page_size: 48 })`**.
- **Product grid** links image/title to **`/store/product/:id`**.

### Checkout errors & reliability

- **`formatClientError` / `parseValidationErrors`**: map FastAPI **`detail[]`** to readable messages and optional **per-field** list; highlight invalid fields; **country** labeled as country code with hint.
- **Double submit**: local **`submitting`** guard + disable CTA while mutations run.

### Bugs fixed

- **`page_size: 50`** caused **422**; use **48** max, SDK clamp, ProductDetail no longer relies on oversized list fetch for a single product.

### Git

- Commits were made inside **`frontend`** and **`backend`** repos (not the parent `naturepath` folder). Example messages: store feature + SDK/RBAC/backend work. **Do not** `git init` at parent unless intentionally monorepo-ing.

## Local dev (typical)

- Scripts: `run-local.sh` at repo root and under `backend/scripts/` — confirm ports (**API often 8001**, Vite **5173**) and `VITE_NATURAL_PATH_API_URL` if used.

---

*Update this file when architecture or conventions change.*
