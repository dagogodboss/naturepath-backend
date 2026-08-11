"""
Revel REST client (merchant subdomain + legacy API-AUTHENTICATION).

Uses the public Revel REST shape documented at:
https://developer.revelsystems.com/revelsystems/docs/how-to-make-an-api-call

RevelService delegates here; there is no mock in production code.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from core.config import Settings
from core.money import Money

logger = logging.getLogger(__name__)


class RevelLiveError(Exception):
    """Raised when a live Revel HTTP call fails or returns an unexpected payload."""


def _resources_base(settings: Settings) -> Optional[str]:
    """
    Return base URL ending in /resources/ for Revel REST calls.
    Prefer REVEL_REST_BASE_URL; else build from REVEL_SUBDOMAIN.
    """
    raw = (settings.revel_rest_base_url or "").strip()
    if raw:
        u = raw.rstrip("/")
        if u.endswith("/resources"):
            return u + "/"
        return u + "/resources/"

    sub = (settings.revel_subdomain or "").strip().strip("/")
    if sub:
        if sub.startswith("http://") or sub.startswith("https://"):
            u = sub.rstrip("/")
            if u.endswith("/resources"):
                return u + "/"
            return u + "/resources/"
        if sub.endswith(".revelup.com"):
            return f"https://{sub}/resources/"
        return f"https://{sub}.revelup.com/resources/"
    return None


def _merchant_base(settings: Settings) -> Optional[str]:
    """
    Return the merchant origin ending in `/`.

    Revel's legacy resource API lives under `/resources/`, while the
    weborders product catalog endpoint lives directly under the merchant
    origin (`/weborders/products/`).
    """
    sub = (settings.revel_subdomain or "").strip().strip("/")
    if sub:
        if sub.startswith("http://") or sub.startswith("https://"):
            u = sub.rstrip("/")
            if u.endswith("/resources"):
                u = u[: -len("/resources")]
            return u + "/"
        if sub.endswith(".revelup.com"):
            return f"https://{sub}/"
        return f"https://{sub}.revelup.com/"

    raw = (settings.revel_rest_base_url or "").strip()
    if raw:
        u = raw.rstrip("/")
        if u.endswith("/resources"):
            u = u[: -len("/resources")]
        return u + "/"
    return None


def _auth_headers(settings: Settings) -> Dict[str, str]:
    token = f"{settings.revel_api_key}:{settings.revel_api_secret}"
    return {
        "API-AUTHENTICATION": token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _unwrap_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("objects", "results", "data"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
    return []


def _normalize_product(
    raw: Dict[str, Any],
    *,
    category_label: Optional[str] = None,
) -> Dict[str, Any]:
    pid = raw.get("id")
    product_id = str(pid) if pid is not None else str(raw.get("id_product") or raw.get("product_id") or "")
    price = raw.get("price") or raw.get("cost_price") or raw.get("active_price") or 0
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        price_f = 0.0
    active = raw.get("active", raw.get("is_active", True))
    if isinstance(active, str):
        active = active.lower() in ("1", "true", "yes")
    stock_raw = raw.get("stock_amount", raw.get("stock_qty"))
    try:
        stock_qty = int(float(stock_raw)) if stock_raw is not None else None
    except (TypeError, ValueError):
        stock_qty = None
    category = raw.get("category") or raw.get("product_group") or raw.get("id_category") or ""
    image = raw.get("image")
    if not image and isinstance(raw.get("images"), list) and raw["images"]:
        first = raw["images"][0]
        image = first.get("url") if isinstance(first, dict) else first
    label = (category_label or "").strip() or None
    return {
        "product_id": product_id,
        "name": str(raw.get("name") or raw.get("product_name") or "Product"),
        "price": price_f,
        "category": str(category),
        "category_label": label,
        "is_active": bool(active),
        "stock_qty": stock_qty,
        "image_url": image,
        "description": raw.get("description"),
        "sku": raw.get("sku") or raw.get("barcode"),
        "raw": raw,
    }


def _walk_menu_categories(
    nodes: Any,
    *,
    parent_label: Optional[str] = None,
    out: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Flatten Revel Custom Menu Category > Subcategory > Product tree."""
    if out is None:
        out = []
    if not isinstance(nodes, list):
        return out
    for node in nodes:
        if not isinstance(node, dict):
            continue
        label = (
            (node.get("name") or node.get("parent_name") or parent_label or "")
            .strip()
            or None
        )
        products = node.get("products") or []
        if isinstance(products, list):
            for raw in products:
                if not isinstance(raw, dict):
                    continue
                product = _normalize_product(raw, category_label=label)
                if product.get("product_id") and product.get("is_active", True):
                    out.append(product)
        for key in ("subcategories", "children", "categories"):
            kids = node.get(key)
            if isinstance(kids, list) and kids:
                _walk_menu_categories(kids, parent_label=label, out=out)
    return out


def _establishment_id_from_order_payload(raw: Dict[str, Any], default: int) -> int:
    est = raw.get("establishment_id")
    if isinstance(est, int):
        return est
    uri = raw.get("establishment")
    if isinstance(uri, str) and "Establishment/" in uri:
        try:
            part = uri.split("Establishment/")[-1].strip("/")
            return int(part.split("/")[0])
        except (ValueError, IndexError):
            pass
    return default


def _items_from_order_payload(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = raw.get("orderitem_set") or raw.get("items") or []
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items
    return []


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Revel returns decimals as strings like '4.860000'; accept str, int, float, None."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_order(raw: Dict[str, Any], items: List[Dict[str, Any]], establishment_id: int) -> Dict[str, Any]:
    oid = raw.get("id")
    order_id = str(oid) if oid is not None else str(raw.get("order_id") or "")

    sub_raw = raw.get("sub_total") or raw.get("subtotal") or raw.get("subtotal_amount")
    tax_raw = raw.get("tax") or raw.get("total_tax") or raw.get("tax_amount")
    total_raw = raw.get("final_total") or raw.get("total_amount") or raw.get("total")

    if sub_raw is None:
        subtotal_f = sum(_coerce_float(i.get("price")) * int(i.get("quantity", 1) or 1) for i in items)
    else:
        subtotal_f = _coerce_float(sub_raw)
    tax_f = _coerce_float(tax_raw)
    total_f = _coerce_float(total_raw, default=round(subtotal_f + tax_f, 2))

    status = raw.get("status") or raw.get("order_status")
    if not status:
        closed = raw.get("closed")
        status = "closed" if closed else "open"

    customer = raw.get("customer") or raw.get("customer_id")
    if isinstance(customer, str) and "Customer/" in customer:
        try:
            customer = customer.split("Customer/")[-1].strip("/").split("/")[0]
        except (ValueError, IndexError):
            pass

    return {
        "order_id": order_id,
        "establishment_id": establishment_id,
        "customer_id": customer,
        "items": items,
        "subtotal": subtotal_f,
        "tax": tax_f,
        "total": total_f,
        "status": str(status).lower(),
        "created_at": raw.get("created_at") or raw.get("created_date"),
        "updated_at": raw.get("updated_at") or raw.get("updated_date"),
        "resource_uri": raw.get("resource_uri"),
    }


# payment_type ints per Revel POS convention seen in webhook samples (0=Cash, 1=Credit Card)
_PAYMENT_TYPE_MAP: Dict[str, int] = {
    "cash": 0,
    "card": 1,
    "credit": 1,
    "creditcard": 1,
    "credit_card": 1,
    "debit": 1,
}


def _payment_type_int(payment_method: str) -> int:
    key = str(payment_method or "").strip().lower().replace(" ", "")
    return _PAYMENT_TYPE_MAP.get(key, 1)


_PAYMENT_DECLINED_STATUSES = {
    "declined",
    "failed",
    "void",
    "voided",
    "error",
    "canceled",
    "cancelled",
    "refused",
}


def _is_live_payment_successful(raw: Dict[str, Any]) -> bool:
    """
    Revel payment JSON (from webhook + REST samples) uses:
      - processor_accepted (bool)
      - transaction_captured (bool)
      - executed (bool)
      - transaction_status (string, nullable; e.g. Captured/Accepted/Declined/Pending)
      - refunded (bool)
    """
    if raw.get("refunded") is True:
        return False

    status_val = str(raw.get("transaction_status") or "").strip().lower()
    if status_val in _PAYMENT_DECLINED_STATUSES:
        return False
    if status_val in {"captured", "accepted", "completed", "success", "successful"}:
        return True

    if raw.get("processor_accepted") is True and raw.get("transaction_captured") is True:
        return True
    if raw.get("executed") is True and raw.get("processor_accepted") is not False:
        # No processor field means this is non-card (cash) — executed means recorded.
        return True

    # Conservative default: unknown state is treated as not yet successful.
    return False


def _normalize_payment(raw: Dict[str, Any], fallback_order_id: str, amount: float) -> Dict[str, Any]:
    pid = raw.get("id") or raw.get("payment_id") or raw.get("transaction_id")
    tx_id = str(pid) if pid is not None else f"REVEL_TXN_{fallback_order_id}"
    order_ref = raw.get("order")
    order_id = fallback_order_id
    if isinstance(order_ref, str) and "Order/" in order_ref:
        try:
            order_id = order_ref.split("Order/")[-1].strip("/").split("/")[0]
        except (ValueError, IndexError):
            pass
    return {
        "success": _is_live_payment_successful(raw),
        "transaction_id": tx_id,
        "order_id": order_id,
        "amount": _coerce_float(raw.get("amount"), default=amount),
        "status": str(raw.get("transaction_status") or "").lower() or (
            "completed" if _is_live_payment_successful(raw) else "pending"
        ),
        "refunded": bool(raw.get("refunded")),
        "resource_uri": raw.get("resource_uri"),
        "message": "Payment recorded via Revel",
    }


class RevelLiveClient:
    """Thin async HTTP client for Revel REST resources."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._base = _resources_base(settings)
        self._merchant_base = _merchant_base(settings)

    def _log_http_warning(self, message: str, resp: httpx.Response) -> None:
        if self._settings.debug:
            logger.warning("%s status=%s body=%s", message, resp.status_code, resp.text[:500])
        else:
            logger.warning("%s status=%s", message, resp.status_code)

    def is_configured(self) -> bool:
        if not (self._base or self._merchant_base):
            return False
        if self._settings.revel_api_key in (None, "", "mock_revel_key"):
            return False
        if self._settings.revel_api_secret in (None, "", "mock_revel_secret"):
            return False
        return True

    def client_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self._settings.revel_http_timeout_seconds)

    async def validate_service(self, revel_product_id: str) -> Optional[Dict[str, Any]]:
        if not self._base:
            raise RevelLiveError("Revel REST base URL is not configured")
        url = f"{self._base}Product/{revel_product_id}/"
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            resp = await client.get(url, headers=_auth_headers(self._settings))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RevelLiveError("Unexpected Product response shape")
        return _normalize_product(data)

    async def get_all_products(self) -> List[Dict[str, Any]]:
        """Full weborders product catalog (legacy). Prefer get_custom_menu_products for shop."""
        if not self._merchant_base:
            raise RevelLiveError("Revel merchant base URL is not configured")
        url = (
            f"{self._merchant_base}weborders/products/"
            f"?establishment={int(self._settings.revel_establishment_id)}&limit=500"
        )
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            resp = await client.get(url, headers=_auth_headers(self._settings))
        if resp.status_code >= 400:
            self._log_http_warning("Revel weborders products GET failed", resp)
        resp.raise_for_status()
        payload = resp.json()
        rows = _unwrap_list(payload)
        out = [_normalize_product(r) for r in rows]
        return [p for p in out if p.get("is_active", True) and p.get("product_id")]

    async def get_custom_menu_products(self) -> List[Dict[str, Any]]:
        """
        Products selected in Revel Custom Menu / Online Ordering menu.

        This is the PO source of truth for what appears on the website shop.
        GET /weborders/menu/?establishment=N returns Category > Product tree.
        """
        if not self._merchant_base:
            raise RevelLiveError("Revel merchant base URL is not configured")
        url = (
            f"{self._merchant_base}weborders/menu/"
            f"?establishment={int(self._settings.revel_establishment_id)}"
        )
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            resp = await client.get(url, headers=_auth_headers(self._settings))
        if resp.status_code >= 400:
            self._log_http_warning("Revel weborders menu GET failed", resp)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        categories = []
        if isinstance(data, dict):
            categories = data.get("categories") or []
        elif isinstance(payload, dict):
            categories = payload.get("categories") or []
        products = _walk_menu_categories(categories)
        # Dedupe by product_id (a product can appear under one category only, but be safe).
        by_id: Dict[str, Dict[str, Any]] = {}
        for p in products:
            pid = p.get("product_id")
            if pid:
                by_id[pid] = p
        return list(by_id.values())

    async def create_order(
        self,
        customer_id: str,
        items: List[Dict[str, Any]],
        establishment_id: int,
        hold: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._base:
            raise RevelLiveError("Revel REST base URL is not configured")
        est = establishment_id
        body: Dict[str, Any] = {
            "establishment": f"/resources/Establishment/{est}/",
        }
        if hold:
            # A1 spike contract: keep order in draft/hold for walk-in flow.
            body["is_draft"] = True
            body["status"] = "on_hold"
        headers = _auth_headers(self._settings)
        order_headers = dict(headers)
        if idempotency_key:
            order_headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            resp = await client.post(f"{self._base}Order/", json=body, headers=order_headers)
            if resp.status_code >= 400:
                self._log_http_warning("Revel live Order POST failed", resp)
            resp.raise_for_status()
            order_json = resp.json()
            if not isinstance(order_json, dict):
                raise RevelLiveError("Unexpected Order create response")
            oid = order_json.get("id")
            if oid is None:
                raise RevelLiveError("Order create response missing id")
            order_uri = order_json.get("resource_uri") or f"/resources/Order/{oid}/"

            for idx, item in enumerate(items):
                pid = str(item.get("product_id") or "")
                if not pid:
                    continue
                item_headers = dict(headers)
                if idempotency_key:
                    item_headers["Idempotency-Key"] = f"{idempotency_key}:item:{idx}"
                item_payload: Dict[str, Any] = {
                    "order": order_uri,
                    "product": f"/resources/Product/{pid}/",
                    "quantity": int(item.get("quantity", 1) or 1),
                }
                price = item.get("price")
                if price is not None:
                    try:
                        item_payload["price"] = float(price)
                    except (TypeError, ValueError):
                        pass
                ir = await client.post(
                    f"{self._base}OrderItem/",
                    json=item_payload,
                    headers=item_headers,
                )
                if ir.status_code >= 400:
                    self._log_http_warning("Revel live OrderItem POST failed", ir)
                ir.raise_for_status()

            gr = await client.get(f"{self._base}Order/{oid}/", headers=headers)
            gr.raise_for_status()
            refreshed = gr.json()
            if not isinstance(refreshed, dict):
                raise RevelLiveError("Unexpected Order GET response")

        return _normalize_order(refreshed, items, establishment_id)

    async def process_payment(
        self,
        order_id: str,
        amount: float,
        payment_method: str = "card",
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record a payment against a Revel Order.

        Revel's Payment model (from public docs + webhook samples):
          - amount: decimal-as-string (e.g. "120.000000")
          - payment_type: int (0=Cash, 1=Credit Card)
          - order: "/resources/Order/{id}/"
          - transaction_status / processor_accepted / transaction_captured govern success
        """
        if not self._base:
            raise RevelLiveError("Revel REST base URL is not configured")
        order_uri = f"/resources/Order/{order_id}/"
        # Prefer Decimal-backed Money for wire format; fall back to float for
        # pre-F1 callers. Both paths produce a stable 2dp string.
        amount_str = (
            amount.to_revel_string()
            if isinstance(amount, Money)
            else Money.from_float(amount).to_revel_string()
        )
        body: Dict[str, Any] = {
            "order": order_uri,
            "amount": amount_str,
            "payment_type": _payment_type_int(payment_method),
        }
        headers = _auth_headers(self._settings)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            resp = await client.post(f"{self._base}Payment/", json=body, headers=headers)
            if resp.status_code >= 400:
                self._log_http_warning("Revel live Payment POST failed", resp)
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict):
            raise RevelLiveError("Unexpected Payment response shape")
        return _normalize_payment(data, order_id, amount)

    async def refund_payment(
        self,
        transaction_id: str,
        amount: Optional[float] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a refund payment in Revel tied to an existing payment.

        Approach (legacy Revel Payment suite):
          1) GET /resources/Payment/{id}/ to find the linked order URI and original amount.
          2) POST /resources/Payment/ with a new refund entry:
              - is_refund: true
              - refund_transaction_id: <original payment id>
              - order: <same order URI>
              - amount: negative string amount
              - payment_type: same as original when available, else 1 (card)

        Returns a normalized dict: {success, refund_id, original_transaction_id, amount, status}.
        """
        if not self._base:
            raise RevelLiveError("Revel REST base URL is not configured")
        headers = _auth_headers(self._settings)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            gr = await client.get(
                f"{self._base}Payment/{transaction_id}/",
                headers=headers,
            )
            if gr.status_code == 404:
                raise RevelLiveError(f"Original Revel payment {transaction_id} not found")
            gr.raise_for_status()
            original = gr.json() if isinstance(gr.json(), dict) else {}
            if not original:
                raise RevelLiveError("Unexpected original Payment response")

            original_amount = _coerce_float(original.get("amount"))
            if amount is None or amount <= 0:
                refund_amount = original_amount
            else:
                refund_amount = min(float(amount), original_amount) if original_amount else float(amount)
            if refund_amount <= 0:
                raise RevelLiveError("Refund amount must be > 0")

            order_ref = original.get("order") or ""
            if not order_ref:
                raise RevelLiveError("Original Payment has no order reference; cannot refund")

            payment_type = original.get("payment_type")
            if not isinstance(payment_type, int):
                payment_type = _payment_type_int("card")

            body: Dict[str, Any] = {
                "order": order_ref,
                "amount": f"-{refund_amount:.6f}",
                "payment_type": payment_type,
                "is_refund": True,
                "refund_transaction_id": str(transaction_id),
            }
            resp = await client.post(f"{self._base}Payment/", json=body, headers=headers)
            if resp.status_code >= 400:
                self._log_http_warning("Revel live refund Payment POST failed", resp)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise RevelLiveError("Unexpected refund Payment response shape")

            # Best-effort: mark the original Payment as refunded (ignore if Revel version disallows).
            try:
                mark = await client.patch(
                    f"{self._base}Payment/{transaction_id}/",
                    headers=headers,
                    json={"refunded": True},
                )
                if mark.status_code >= 400:
                    self._log_http_warning("Revel refund mark-original PATCH failed (non-fatal)", mark)
            except httpx.HTTPError as exc:
                logger.warning("Revel refund mark-original PATCH error (non-fatal): %s", exc)

        refund_id = data.get("id") or data.get("payment_id") or data.get("transaction_id")
        refund_id = str(refund_id) if refund_id is not None else f"REVEL_REF_{transaction_id}"
        declined = _is_live_payment_successful(data) is False and not data.get("refunded")
        return {
            "success": not declined,
            "refund_id": refund_id,
            "original_transaction_id": str(transaction_id),
            "amount": refund_amount,
            "status": "refunded" if not declined else str(data.get("transaction_status") or "failed").lower(),
            "resource_uri": data.get("resource_uri"),
        }

    async def fetch_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        if not self._base:
            raise RevelLiveError("Revel REST base URL is not configured")
        url = f"{self._base}Order/{order_id}/"
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            resp = await client.get(url, headers=_auth_headers(self._settings))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None
        est = _establishment_id_from_order_payload(data, int(self._settings.revel_establishment_id))
        items = _items_from_order_payload(data)
        return _normalize_order(data, items, est)

    async def patch_order_status(self, order_id: str, status: str) -> Optional[Dict[str, Any]]:
        if not self._base:
            raise RevelLiveError("Revel REST base URL is not configured")
        url = f"{self._base}Order/{order_id}/"
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            resp = await client.patch(
                url,
                headers=_auth_headers(self._settings),
                json={"status": status},
            )
        if resp.status_code in (400, 404, 405):
            raise RevelLiveError("Order status update not accepted by Revel")
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None

    async def fetch_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        if not self._base:
            raise RevelLiveError("Revel REST base URL is not configured")
        url = f"{self._base}Payment/{payment_id}/"
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            resp = await client.get(url, headers=_auth_headers(self._settings))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None
        return _normalize_payment(data, fallback_order_id=str(payment_id), amount=_coerce_float(data.get("amount")))

    async def sync_customer_http(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self._base:
            raise RevelLiveError("Revel REST base URL is not configured")
        name = (customer_data.get("name") or "").strip() or "Customer"
        parts = name.split()
        first = parts[0][:80]
        last = (" ".join(parts[1:]) if len(parts) > 1 else "Customer")[:80]
        payload: Dict[str, Any] = {
            "first_name": first,
            "last_name": last,
            "email": customer_data.get("email"),
            "phone_number": customer_data.get("phone"),
        }
        url = f"{self._base}Customer/"
        async with httpx.AsyncClient(timeout=self.client_timeout()) as client:
            resp = await client.post(url, headers=_auth_headers(self._settings), json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or data.get("id") is None:
            raise RevelLiveError("Unexpected Customer create response")
        return {
            "revel_customer_id": str(data["id"]),
            "synced": True,
            "email": customer_data.get("email"),
            "name": customer_data.get("name"),
            "revel_channel": "live",
        }
