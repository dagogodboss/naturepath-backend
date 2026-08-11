"""
Store / Commerce API routes for Natural Path products and orders.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Literal
import uuid
import logging
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from core.config import settings
from core.money import Money
from core.money_fields import dual_money_fields, read_amount_cents_first
from core.rbac import Permission, has_permission
from core.time_utils import add_business_days
from infrastructure.payment_events import record_payment_event
from infrastructure.database import get_database
from infrastructure.external import (
    get_email_service,
    get_payment_link_provider,
    get_revel_service,
    get_sms_service,
)
from infrastructure.external.revel_live_client import RevelLiveError
from presentation.dependencies import (
    get_current_active_user,
    get_optional_user,
    get_auth_use_case,
)
from application.use_cases import AuthUseCase

router = APIRouter(prefix="/store", tags=["Store"])
logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _idempotency_key(ref_type: str, ref_id: str, action: str, attempt_no: int = 1) -> str:
    raw = f"{ref_type}:{ref_id}:{action}:{attempt_no}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _twilio_configured() -> bool:
    """True when Twilio creds are present (required to text a pay link)."""
    sid = settings.twilio_account_sid
    return bool(
        sid
        and sid != "placeholder"
        and settings.twilio_auth_token
        and settings.twilio_phone_number
    )


def _sms_pay_link_available() -> bool:
    """
    SMS pay-link is offered only when BOTH are true:
      - Revel hosted payments are enabled (REVEL_ENABLE_HOSTED_PAYMENTS) — this
        is the single flag to flip once Revel grants REST/SmartPay access, and
      - Twilio is configured to send the SMS.
    """
    return bool(settings.revel_enable_hosted_payments and _twilio_configured())


def _build_sms_pay_link_message(order_id: str, pay_url: str) -> str:
    short = order_id[-8:].upper()
    return (
        f"The Natural Path: complete payment for order #{short} here: {pay_url}\n"
        "This is a secure link. Reply STOP to opt out."
    )


class StoreOrderItemIn(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=99)


class StoreAddressIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=32)
    email: str = Field(min_length=5, max_length=120)
    line1: str = Field(min_length=3, max_length=200)
    line2: Optional[str] = Field(default=None, max_length=200)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    postal_code: str = Field(min_length=3, max_length=20)
    country: str = Field(default="US", min_length=2, max_length=2)
    delivery_notes: Optional[str] = Field(default=None, max_length=300)


class CreateStoreOrderIn(BaseModel):
    items: List[StoreOrderItemIn] = Field(min_length=1, max_length=50)
    address: StoreAddressIn
    payment_mode: Literal["card_online", "walk_in", "pay_offline", "sms_pay_link"] = "pay_offline"
    payment_method: str = Field(default="pay_on_delivery")
    customer_note: Optional[str] = Field(default=None, max_length=300)


class AdminOrderActionIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)
    amount: Optional[float] = Field(default=None, ge=0)


class ProductAdminUpdateIn(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)
    discount_price: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    is_active_web: Optional[bool] = None
    image_url: Optional[str] = None


class ProductIdsIn(BaseModel):
    product_ids: List[str] = Field(min_length=1, max_length=100)


class AnalyticsEventIn(BaseModel):
    event_name: str = Field(min_length=3, max_length=80)
    session_id: Optional[str] = Field(default=None, max_length=80)
    order_id: Optional[str] = Field(default=None, max_length=80)
    product_id: Optional[str] = Field(default=None, max_length=80)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Revel stores category as numeric IDs (e.g. "112"). Shop UI uses human slugs
# (supplements, topicals, teas, essentials). Map known IDs + name patterns so
# filters work without requiring a Revel ProductCategory sync.
STORE_CATEGORY_SLUGS: Dict[str, Dict[str, Any]] = {
    "supplements": {
        "label": "Supplements",
        "ids": {"11", "19", "23", "108", "146"},
        "name_patterns": [
            r"\bcaps?\b",
            r"capsule",
            r"tablet",
            r"vitamin",
            r"\bmulti\b",
            r"complex",
            r"\d+\s*ct\b",
            r"\d+\s*caps\b",
        ],
    },
    "topicals": {
        "label": "Topicals",
        "ids": {"13", "24", "119", "135"},
        "name_patterns": [
            r"cream",
            r"\boil\b",
            r"balm",
            r"lotion",
            r"soap",
            r"salve",
            r"ointment",
            r"serum",
            r"drops",
            r"polish",
            r"foundation",
            r"bath salt",
        ],
    },
    "teas": {
        "label": "Teas",
        "ids": {"112"},
        "name_patterns": [r"\btea\b", r"tisane"],
    },
    "essentials": {
        "label": "Essentials",
        "ids": {"116", "117", "165"},
        "name_patterns": [
            r"essential",
            r"salt lamp",
            r"incense",
            r"inhaler",
            r"cheese cloth",
        ],
    },
}


def _escape_regex(value: str) -> str:
    special = r"\.^$*+?{}[]|()\\"
    return "".join(f"\\{ch}" if ch in special else ch for ch in value)


def _build_search_clause(q: Optional[str]) -> Optional[Dict[str, Any]]:
    term = (q or "").strip()
    if not term:
        return None
    pattern = _escape_regex(term)
    return {
        "$or": [
            {"name": {"$regex": pattern, "$options": "i"}},
            {"description": {"$regex": pattern, "$options": "i"}},
            {"sku": {"$regex": pattern, "$options": "i"}},
        ]
    }


def _build_category_clause(category: Optional[str]) -> Optional[Dict[str, Any]]:
    raw = (category or "").strip()
    if not raw or raw.lower() in {"all", "uncategorized"}:
        return None
    slug = raw.lower()
    menu_match = {
        "$or": [
            {"category_slug": slug},
            {"category_label": {"$regex": f"^{_escape_regex(raw)}$", "$options": "i"}},
            {"category": raw},
        ]
    }
    group = STORE_CATEGORY_SLUGS.get(slug)
    if group:
        clauses: List[Dict[str, Any]] = [menu_match]
        ids = group.get("ids") or set()
        if ids:
            clauses.append({"category": {"$in": list(ids)}})
        for pattern in group.get("name_patterns") or []:
            clauses.append({"name": {"$regex": pattern, "$options": "i"}})
        return {"$or": clauses}
    return menu_match


def _slugify_category(label: str) -> str:
    raw = (label or "").strip().lower()
    out = []
    prev_dash = False
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")
    return slug or "uncategorized"


def _compose_product_query(
    *,
    q: Optional[str] = None,
    category: Optional[str] = None,
    active_web_only: bool = True,
    custom_menu_only: bool = True,
) -> Dict[str, Any]:
    clauses: List[Dict[str, Any]] = []
    if custom_menu_only:
        # After Custom Menu sync, only menu-selected products are shoppable.
        # Missing field is treated as excluded (legacy full-catalog rows stay hidden).
        clauses.append({"in_custom_menu": True})
    if active_web_only:
        # Emergency override: staff can hide a menu item without removing it in Revel.
        clauses.append({"is_active_web": {"$ne": False}})
    search = _build_search_clause(q)
    if search:
        clauses.append(search)
    cat = _build_category_clause(category)
    if cat:
        clauses.append(cat)
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


async def _resolve_store_products(
    db,
    q: Optional[str],
    category: Optional[str],
    page: int,
    page_size: int,
    *,
    active_web_only: bool = True,
    custom_menu_only: bool = True,
):
    query = _compose_product_query(
        q=q,
        category=category,
        active_web_only=active_web_only,
        custom_menu_only=custom_menu_only,
    )
    skip = (page - 1) * page_size
    # Products with images first, then newest Revel sync (created_at / updated_at).
    pipeline: List[Dict[str, Any]] = [
        {"$match": query},
        {
            "$addFields": {
                "has_image": {
                    "$cond": [
                        {
                            "$and": [
                                {"$ne": [{"$ifNull": ["$image_url", ""]}, ""]},
                            ]
                        },
                        1,
                        0,
                    ]
                },
                "sort_date": {"$ifNull": ["$created_at", "$updated_at"]},
            }
        },
        {"$sort": {"has_image": -1, "sort_date": -1, "name": 1}},
        {"$skip": skip},
        {"$limit": page_size},
        {
            "$project": {
                "_id": 0,
                "raw_revel_payload": 0,
                "has_image": 0,
                "sort_date": 0,
            }
        },
    ]
    items = await db.store_products.aggregate(pipeline).to_list(length=page_size)
    total = await db.store_products.count_documents(query)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def _store_order_allowed_actions(order: Dict[str, Any]) -> Dict[str, bool]:
    """UI hints for practitioner store ops (refund gated on Revel capture metadata)."""
    ps = order.get("payment_status") or ""
    fs = order.get("fulfillment_status") or ""
    mode = order.get("payment_mode") or ""
    has_tx = bool(order.get("revel_transaction_id"))
    return {
        "refund": ps == "captured" and has_tx and fs not in {"refunded", "rejected"},
        "reject": fs in {"placed", "confirmed", "preparing"} and ps != "refunded",
        "confirm": fs == "placed",
        "fulfill": fs in {"confirmed", "preparing"},
        # No-card orders are paid in person / via back office; ops records it.
        "record_payment": mode == "pay_offline"
        and ps in {"awaiting_offline_payment", "pending"},
        # SMS pay-link orders can re-send the text while still awaiting payment.
        "resend_sms": mode == "sms_pay_link"
        and ps == "awaiting_payment"
        and bool(order.get("payment_link_url")),
    }


def _enrich_store_order(order: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not order:
        return None
    out = dict(order)
    out.pop("_id", None)
    # Cents-first read during F2 cutover; keep legacy float fields in response.
    out["subtotal"] = read_amount_cents_first(
        out, cents_field="subtotal_cents", legacy_field="subtotal", default_currency="USD"
    )
    out["tax"] = read_amount_cents_first(
        out, cents_field="tax_cents", legacy_field="tax", default_currency="USD"
    )
    out["total"] = read_amount_cents_first(
        out, cents_field="total_cents", legacy_field="total", default_currency="USD"
    )
    if out.get("refund_amount_cents") is not None or out.get("refund_amount") is not None:
        out["refund_amount"] = read_amount_cents_first(
            out,
            cents_field="refund_amount_cents",
            legacy_field="refund_amount",
            default_currency="USD",
        )
    out["allowed_actions"] = _store_order_allowed_actions(out)
    return out


async def _reprice_order_lines_from_catalog(
    db, order_items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Build Revel line items with explicit unit price from synced store_products (source of truth)."""
    product_ids = [it["product_id"] for it in order_items]
    products = await db.store_products.find(
        {"product_id": {"$in": product_ids}, "is_active_web": {"$ne": False}, "in_custom_menu": True}, {"_id": 0}
    ).to_list(length=500)
    by_id = {p["product_id"]: p for p in products}
    revel_items: List[Dict[str, Any]] = []
    for it in order_items:
        pid = it["product_id"]
        p = by_id.get(pid)
        if not p:
            raise HTTPException(
                status_code=400,
                detail=f"Product {pid} is no longer available for purchase",
            )
        unit = float(p.get("discount_price") or p["price"])
        qty = int(it.get("quantity", 1))
        revel_items.append(
            {
                "product_id": pid,
                "name": p.get("name") or it.get("name") or "Product",
                "quantity": qty,
                "price": unit,
            }
        )
    return revel_items


async def _require_order_ops_user(user: dict):
    if has_permission(user, Permission.BOOKING_MANAGE) or has_permission(
        user, Permission.USER_ROLE_MANAGE
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Order management access required"
    )


@router.get("/products")
async def get_store_products(
    q: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=75),
    db=Depends(get_database),
):
    return await _resolve_store_products(db, q, category, page, page_size)


@router.get("/categories")
async def get_store_categories(db=Depends(get_database)):
    """Shop-facing category chips from Custom Menu products currently on the shop."""
    base = _compose_product_query(active_web_only=True, custom_menu_only=True)
    pipeline: List[Dict[str, Any]] = [
        {"$match": base},
        {
            "$group": {
                "_id": {
                    "slug": {
                        "$ifNull": [
                            "$category_slug",
                            {"$toLower": {"$ifNull": ["$category_label", "$category"]}},
                        ]
                    },
                    "label": {"$ifNull": ["$category_label", "$category"]},
                },
                "total": {"$sum": 1},
            }
        },
        {"$sort": {"_id.label": 1}},
    ]
    rows = await db.store_products.aggregate(pipeline).to_list(length=100)
    items: List[Dict[str, Any]] = []
    for row in rows:
        key = row.get("_id") or {}
        label = str(key.get("label") or "Other").strip() or "Other"
        slug = _slugify_category(str(key.get("slug") or label))
        if label.lower() in {"uncategorized", "none", "null", ""}:
            continue
        items.append({"slug": slug, "label": label, "total": int(row.get("total") or 0)})
    if not items:
        for slug, meta in STORE_CATEGORY_SLUGS.items():
            query = _compose_product_query(
                category=slug, active_web_only=True, custom_menu_only=True
            )
            total = await db.store_products.count_documents(query)
            if total > 0:
                items.append({"slug": slug, "label": meta["label"], "total": total})
    return {"items": items}


@router.get("/payment-config")
async def get_store_payment_config():
    """
    Public, unauthenticated. Lets the storefront decide which payment options
    to render without shipping feature-flag logic to the client.

    `sms_pay_link` flips to True automatically once REVEL_ENABLE_HOSTED_PAYMENTS
    is on AND Twilio is configured — no frontend redeploy needed.
    """
    sms = _sms_pay_link_available()
    return {
        "offline": True,  # always available (pay at pickup / back office)
        "card_online": bool(settings.revel_enable_hosted_payments),
        "walk_in": bool(settings.revel_enable_hold_orders),
        "sms_pay_link": sms,
        "currency": settings.default_currency,
    }


@router.post("/products/by-ids")
async def get_store_products_by_ids(
    body: ProductIdsIn,
    db=Depends(get_database),
):
    rows = await db.store_products.find(
        {
            "product_id": {"$in": body.product_ids},
            "is_active_web": {"$ne": False},
            "in_custom_menu": True,
        },
        {"_id": 0, "raw_revel_payload": 0},
    ).to_list(length=500)
    return {"items": rows}


@router.post("/analytics/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_store_analytics_event(
    body: AnalyticsEventIn,
    optional_user: Optional[dict] = Depends(get_optional_user),
    db=Depends(get_database),
):
    event = {
        "event_id": _id("evt"),
        "event_name": body.event_name,
        "session_id": body.session_id,
        "user_id": optional_user.get("user_id") if optional_user else None,
        "order_id": body.order_id,
        "product_id": body.product_id,
        "metadata": body.metadata,
        "created_at": datetime.now(timezone.utc),
    }
    await db.analytics_events.insert_one(event)
    return {"accepted": True}


@router.post("/admin/sync-revel-products")
async def sync_revel_products(
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """
    Sync shop catalog from Revel Custom Menu (online ordering menu), not the full
    product table. Fail-safe: if the menu fetch fails, leave the last good snapshot.
    """
    if not (
        has_permission(current_user, Permission.SERVICE_UPDATE)
        or has_permission(current_user, Permission.USER_ROLE_MANAGE)
    ):
        raise HTTPException(status_code=403, detail="Not allowed")
    revel = get_revel_service()
    try:
        revel_products = await revel.get_custom_menu_products()
    except Exception as exc:
        logger.exception("Custom Menu sync aborted; catalog unchanged")
        raise HTTPException(
            status_code=502,
            detail=f"Revel Custom Menu sync failed; catalog left unchanged ({exc})",
        ) from exc

    now = _utc_now_iso()
    upserts = 0
    menu_ids: List[str] = []
    for rp in revel_products:
        pid = rp["product_id"]
        menu_ids.append(pid)
        label = (rp.get("category_label") or "").strip() or None
        doc = {
            "product_id": pid,
            "revel_product_id": pid,
            "name": rp["name"],
            "category": rp.get("category") or "uncategorized",
            "category_label": label,
            "category_slug": _slugify_category(label) if label else None,
            "price": float(rp.get("price", 0)),
            "stock_qty": rp.get("stock_qty"),
            "is_active": bool(rp.get("is_active", True)),
            "in_custom_menu": True,
            "image_url": rp.get("image_url"),
            "description": rp.get("description"),
            "sku": rp.get("sku"),
            "raw_revel_payload": rp.get("raw"),
            "updated_at": now,
        }
        await db.store_products.update_one(
            {"product_id": pid},
            {
                "$set": doc,
                "$setOnInsert": {
                    "created_at": now,
                    "is_active_web": True,
                    "discount_price": None,
                },
            },
            upsert=True,
        )
        upserts += 1

    # Products removed from Custom Menu stay in DB for order history but leave the shop.
    removed = 0
    if menu_ids:
        res = await db.store_products.update_many(
            {"product_id": {"$nin": menu_ids}, "in_custom_menu": {"$ne": False}},
            {"$set": {"in_custom_menu": False, "updated_at": now}},
        )
        removed = int(res.modified_count or 0)
    else:
        # Empty menu is a valid PO state — clear the allowlist.
        res = await db.store_products.update_many(
            {"in_custom_menu": True},
            {"$set": {"in_custom_menu": False, "updated_at": now}},
        )
        removed = int(res.modified_count or 0)

    return {
        "success": True,
        "synced": upserts,
        "removed_from_menu": removed,
        "source": "custom_menu",
    }


@router.get("/admin/products")
async def admin_list_store_products(
    q: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=75),
    include_inactive: bool = Query(default=True),
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """Office catalog view — includes products hidden from the public shop."""
    if not (
        has_permission(current_user, Permission.SERVICE_UPDATE)
        or has_permission(current_user, Permission.USER_ROLE_MANAGE)
        or has_permission(current_user, Permission.BOOKING_MANAGE)
    ):
        raise HTTPException(status_code=403, detail="Not allowed")
    return await _resolve_store_products(
        db,
        q,
        category,
        page,
        page_size,
        active_web_only=not include_inactive,
        custom_menu_only=True,
    )


@router.patch("/admin/products/{product_id}")
async def update_store_product(
    product_id: str,
    body: ProductAdminUpdateIn,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    if not (
        has_permission(current_user, Permission.SERVICE_UPDATE)
        or has_permission(current_user, Permission.USER_ROLE_MANAGE)
    ):
        raise HTTPException(status_code=403, detail="Not allowed")
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        existing = await db.store_products.find_one({"product_id": product_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Product not found")
        return existing
    updates["updated_at"] = _utc_now_iso()
    res = await db.store_products.update_one({"product_id": product_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")

    # Keep Revel in sync where possible.
    revel = get_revel_service()
    existing = await db.store_products.find_one({"product_id": product_id}, {"_id": 0})
    if existing:
        if "price" in updates:
            await revel.validate_service(existing["revel_product_id"])
        await db.store_admin_audit.insert_one(
            {
                "audit_id": _id("prod_audit"),
                "actor_user_id": current_user["user_id"],
                "action": "product_update",
                "product_id": product_id,
                "changes": updates,
                "created_at": _utc_now_iso(),
            }
        )
    return await db.store_products.find_one({"product_id": product_id}, {"_id": 0})


@router.post("/checkout/orders", status_code=status.HTTP_201_CREATED)
async def create_store_order(
    body: CreateStoreOrderIn,
    optional_user: Optional[dict] = Depends(get_optional_user),
    auth_use_case: AuthUseCase = Depends(get_auth_use_case),
    db=Depends(get_database),
):
    product_ids = [i.product_id for i in body.items]
    products = (
        await db.store_products.find(
            {"product_id": {"$in": product_ids}, "is_active_web": {"$ne": False}, "in_custom_menu": True}, {"_id": 0}
        ).to_list(length=500)
    )
    by_id = {p["product_id"]: p for p in products}
    if len(by_id) != len(set(product_ids)):
        raise HTTPException(status_code=400, detail="One or more products are unavailable")

    priced_items: List[Dict[str, Any]] = []
    subtotal = 0.0
    for item in body.items:
        p = by_id[item.product_id]
        unit_price = float(p.get("discount_price") or p["price"])
        line_total = round(unit_price * item.quantity, 2)
        subtotal += line_total
        priced_items.append(
            {
                "product_id": p["product_id"],
                "name": p["name"],
                "quantity": item.quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )
    tax = round(subtotal * float(settings.store_tax_rate), 2)
    total = round(subtotal + tax, 2)
    now = _utc_now_iso()
    order_id = _id("np_ord")

    customer_id = optional_user.get("user_id") if optional_user else None
    # Guest checkout: upsert an unclaimed customer by email so later register can claim.
    if not customer_id:
        try:
            guest = await auth_use_case.upsert_guest_buyer(
                email=body.address.email,
                full_name=body.address.full_name,
                phone=body.address.phone,
            )
            customer_id = guest.get("user_id")
        except Exception as exc:
            logger.warning("Guest buyer upsert failed for order_id=%s: %s", order_id, exc)

    subtotal_money = Money.from_float(subtotal, "USD")
    tax_money = Money.from_float(tax, "USD")
    total_money = Money.from_float(total, "USD")
    order_doc = {
        "order_id": order_id,
        "customer_id": customer_id,
        "items": priced_items,
        "address": body.address.model_dump(),
        "payment_method": body.payment_method,
        "payment_mode": body.payment_mode,
        "payment_status": "pending",
        "fulfillment_status": "placed",
        "subtotal": subtotal_money.to_float(),
        "subtotal_cents": subtotal_money.to_cents(),
        "tax": tax_money.to_float(),
        "tax_cents": tax_money.to_cents(),
        "total": total_money.to_float(),
        "total_cents": total_money.to_cents(),
        "currency": "USD",
        "customer_note": body.customer_note,
        "revel_order_id": None,
        "payment_link_url": None,
        "invoice_id": None,
        # Guests remain unauthenticated even after upsert — keep action_token.
        "action_token": _id("act") if optional_user is None else None,
        "timeline": [{"status": "placed", "at": now}],
        "created_at": now,
        "updated_at": now,
    }
    await db.store_orders.insert_one(order_doc)
    # insert_one mutates order_doc with a non-serializable ObjectId _id; drop it
    # and return the enriched view (with allowed_actions) like the other endpoints.
    order_doc.pop("_id", None)
    try:
        from application.order_notifications import queue_order_notifications
        await queue_order_notifications(db, order_doc, ops_email=settings.ops_email)
    except Exception as exc:
        # Checkout must succeed even if a notification channel is temporarily down.
        logger.exception("Failed to queue order operations notification for %s: %s", order_id, exc)
    return _enrich_store_order(order_doc)


@router.post("/checkout/orders/{order_id}/pay")
async def pay_store_order(
    order_id: str,
    payment_method: str = Query(default="card"),
    action_token: Optional[str] = Query(default=None),
    optional_user: Optional[dict] = Depends(get_optional_user),
    db=Depends(get_database),
):
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if optional_user:
        if order.get("customer_id"):
            if order["customer_id"] != optional_user["user_id"]:
                raise HTTPException(status_code=403, detail="Not allowed")
        elif not action_token or action_token != order.get("action_token"):
            raise HTTPException(status_code=401, detail="Order action token required")
    elif not action_token or action_token != order.get("action_token"):
        raise HTTPException(status_code=401, detail="Order action token required")

    payment_mode = str(order.get("payment_mode") or "pay_offline")
    if payment_mode not in {"card_online", "walk_in", "pay_offline", "sms_pay_link"}:
        raise HTTPException(status_code=400, detail="Invalid order payment mode")

    # ── No-card WebStore flow ──────────────────────────────────────────────
    # Customer pays in person (pickup/delivery) or via back office. We record
    # the order in our app only; no online card capture and no Revel write is
    # required. A flag-gated, best-effort Revel mirror is attempted once cart
    # API access is granted (settings.revel_enable_order_push) but never blocks
    # order placement. Card capture (Stripe) lands in the next release.
    if payment_mode == "pay_offline":
        ps = order.get("payment_status")
        if ps in {"awaiting_offline_payment", "paid_offline", "captured"}:
            out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
            return _enrich_store_order(out)
        now = _utc_now_iso()
        await db.store_orders.update_one(
            {
                "order_id": order_id,
                "payment_status": {"$in": ["pending", "processing"]},
            },
            {
                "$set": {"payment_status": "awaiting_offline_payment", "updated_at": now},
                "$push": {
                    "timeline": {
                        "status": "order_submitted",
                        "at": now,
                        "mode": "pay_offline",
                        "method": order.get("payment_method"),
                    }
                },
            },
        )
        if settings.revel_enable_order_push and not order.get("revel_order_id"):
            try:
                revel_items = await _reprice_order_lines_from_catalog(db, order["items"])
                revel = get_revel_service()
                revel_order = await revel.create_order(
                    customer_id=order.get("customer_id") or "guest",
                    items=revel_items,
                    hold=True,
                    idempotency_key=_idempotency_key(
                        "store_order", order_id, "create_order"
                    ),
                )
                await db.store_orders.update_one(
                    {"order_id": order_id},
                    {
                        "$set": {
                            "revel_order_id": revel_order["order_id"],
                            "revel_channel": "live",
                            "updated_at": _utc_now_iso(),
                        }
                    },
                )
            except Exception as exc:
                # Never block the order on the Revel mirror; ops can key it in
                # manually until cart access is enabled.
                logger.warning(
                    "Offline order Revel mirror skipped for order_id=%s: %s",
                    order_id,
                    exc,
                )
        out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
        return _enrich_store_order(out)
    # ───────────────────────────────────────────────────────────────────────

    if payment_mode == "card_online" and not settings.revel_enable_hosted_payments:
        raise HTTPException(
            status_code=503,
            detail="Online hosted payments are not enabled for this environment",
        )
    if payment_mode == "sms_pay_link" and not _sms_pay_link_available():
        # Distinguish the two blockers so ops can act on the right one.
        if not settings.revel_enable_hosted_payments:
            raise HTTPException(
                status_code=503,
                detail="SMS pay link is unavailable: Revel hosted payments are not enabled "
                "(REVEL_ENABLE_HOSTED_PAYMENTS). This unlocks once Revel grants REST access.",
            )
        raise HTTPException(
            status_code=503,
            detail="SMS pay link is unavailable: Twilio is not configured (set "
            "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER).",
        )
    if payment_mode == "walk_in" and not settings.revel_enable_hold_orders:
        raise HTTPException(
            status_code=503,
            detail="Walk-in hold flow is not enabled for this environment",
        )

    # Idempotent terminal/active states.
    if order.get("payment_status") == "captured":
        out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
        return _enrich_store_order(out)
    if (
        payment_mode in {"card_online", "sms_pay_link"}
        and order.get("payment_status") == "awaiting_payment"
    ):
        out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
        return _enrich_store_order(out)
    if payment_mode == "walk_in" and order.get("payment_status") == "awaiting_counter":
        out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
        return _enrich_store_order(out)

    if order.get("payment_status") == "processing":
        raise HTTPException(status_code=409, detail="Payment already in progress")

    lock = await db.store_orders.update_one(
        {"order_id": order_id, "payment_status": "pending"},
        {"$set": {"payment_status": "processing", "updated_at": _utc_now_iso()}},
    )
    if lock.matched_count == 0:
        latest = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
        if latest and latest.get("payment_status") == "captured":
            return _enrich_store_order(latest)
        if latest:
            return _enrich_store_order(latest)
        raise HTTPException(status_code=404, detail="Order not found")

    # Re-price lines from Revel-synced catalog (explicit price sent to Revel).
    try:
        revel_items = await _reprice_order_lines_from_catalog(db, order["items"])
    except HTTPException as http_exc:
        fail_at = _utc_now_iso()
        await db.store_orders.update_one(
            {"order_id": order_id},
            {"$set": {"payment_status": "pending", "updated_at": fail_at}},
        )
        raise http_exc

    revel = get_revel_service()
    customer_id = order.get("customer_id") or "guest"
    try:
        revel_order = await revel.create_order(
            customer_id=customer_id,
            items=revel_items,
            hold=(payment_mode == "walk_in"),
            idempotency_key=_idempotency_key("store_order", order_id, "create_order"),
        )
    except RevelLiveError as exc:
        fail_at = _utc_now_iso()
        await db.store_orders.update_one(
            {"order_id": order_id},
            {
                "$set": {"payment_status": "pending", "updated_at": fail_at},
                "$push": {
                    "timeline": {
                        "status": "payment_error",
                        "at": fail_at,
                        "detail": str(exc)[:300],
                    }
                },
            },
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to complete checkout with the payment provider",
        ) from exc
    except Exception as exc:
        fail_at = _utc_now_iso()
        await db.store_orders.update_one(
            {"order_id": order_id},
            {
                "$set": {"payment_status": "pending", "updated_at": fail_at},
                "$push": {
                    "timeline": {
                        "status": "payment_error",
                        "at": fail_at,
                        "detail": str(exc)[:300],
                    }
                },
            },
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to complete checkout with the payment provider",
        ) from exc

    client_total = read_amount_cents_first(
        order, cents_field="total_cents", legacy_field="total", default_currency="USD"
    )
    revel_total = float(revel_order.get("total") or 0)
    revel_total_money = Money.from_float(revel_total, str(order.get("currency") or "USD"))
    pricing_drift = abs(client_total - revel_total) > 0.02
    # F4: validate Revel-returned tax against the catalog rate. Do NOT block
    # checkout — Revel is source of truth — but record any drift so G2 can
    # surface it for ops review.
    revel_subtotal = float(revel_order.get("subtotal") or 0)
    revel_tax = float(revel_order.get("tax") or 0)
    expected_tax = round(revel_subtotal * float(settings.store_tax_rate), 2)
    tax_drift_cents = int(round((revel_tax - expected_tax) * 100))
    if abs(tax_drift_cents) > 1:
        logger.warning(
            "Tax drift for order_id=%s: revel=%.2f expected=%.2f drift_cents=%s",
            order_id, revel_tax, expected_tax, tax_drift_cents,
        )
    now = _utc_now_iso()
    base_set = {
        "revel_order_id": revel_order["order_id"],
        "revel_channel": "live",
        "items": [
            {
                **line,
                "unit_price": line.get("price"),
                "line_total": round(float(line.get("price", 0)) * int(line.get("quantity", 1)), 2),
            }
            for line in revel_items
        ],
        "subtotal": Money.from_float(revel_order.get("subtotal") or 0, "USD").to_float(),
        "subtotal_cents": Money.from_float(revel_order.get("subtotal") or 0, "USD").to_cents(),
        "tax": Money.from_float(revel_order.get("tax") or 0, "USD").to_float(),
        "tax_cents": Money.from_float(revel_order.get("tax") or 0, "USD").to_cents(),
        "total": revel_total_money.to_float(),
        "total_cents": revel_total_money.to_cents(),
        "pricing_drift": pricing_drift,
        "pricing_drift_client_total": client_total if pricing_drift else None,
        "expected_tax": expected_tax,
        "tax_drift_cents": tax_drift_cents,
        "updated_at": now,
    }
    await db.store_orders.update_one(
        {"order_id": order_id},
        {"$set": {"revel_order_id": revel_order["order_id"], "updated_at": now}},
    )

    if payment_mode in {"card_online", "sms_pay_link"}:
        provider = get_payment_link_provider()
        try:
            link = await provider.create_link(
                order_ref=str(revel_order["order_id"]),
                amount=revel_total,
                currency=str(order.get("currency") or "USD"),
                metadata={"ref_type": "store_order", "ref_id": order_id},
                idempotency_key=_idempotency_key("store_order", order_id, "create_link"),
            )
        except Exception as exc:
            fail_at = _utc_now_iso()
            # Revel order was already created; the link step is what failed.
            # Return a pending_verification shape so the SDK can poll the
            # status endpoint rather than hard-502 the caller.
            await db.store_orders.update_one(
                {"order_id": order_id},
                {
                    "$set": {"payment_status": "awaiting_payment", "updated_at": fail_at},
                    "$push": {"timeline": {"status": "payment_link_error", "at": fail_at}},
                },
            )
            logger.exception("Hosted payment link creation failed for order_id=%s", order_id)
            return {
                "status": "pending_verification",
                "order_id": order_id,
                "check_url": f"/api/store/orders/{order_id}/status",
                "detail": "Payment link is still being provisioned; please poll the check_url.",
            }

        await db.payment_links.update_one(
            {"link_id": link.link_id},
            {
                "$set": {
                    "link_id": link.link_id,
                    "provider": "revel",
                    "ref_type": "store_order",
                    "ref_id": order_id,
                    "amount": revel_total_money.to_float(),
                    "amount_cents": revel_total_money.to_cents(),
                    "currency": str(order.get("currency") or "USD"),
                    "status": link.status,
                    "hosted_url": link.url,
                    "expires_at": link.expires_at,
                    "revel_order_id": revel_order["order_id"],
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        email = order.get("address", {}).get("email")
        if email:
            email_service = get_email_service()
            try:
                await email_service.send_store_payment_link(
                    to_email=email,
                    order_id=order_id,
                    pay_link_url=link.url,
                    expires_at=link.expires_at,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to send payment link email for order_id=%s: %s", order_id, exc
                )
        # SMS pay-link delivery: text the SmartPay/hosted link to the customer.
        sms_result: Optional[Dict[str, Any]] = None
        if payment_mode == "sms_pay_link":
            phone = (order.get("address") or {}).get("phone")
            if phone:
                try:
                    sms_result = await get_sms_service().send_sms(
                        to_phone=phone,
                        message=_build_sms_pay_link_message(order_id, link.url),
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to send pay-link SMS for order_id=%s: %s", order_id, exc
                    )
                    sms_result = {"success": False, "message": str(exc)[:200]}
        set_payload: Dict[str, Any] = {
            **base_set,
            "payment_status": "awaiting_payment",
            "payment_link_url": link.url,
            "payment_link_id": link.link_id,
        }
        timeline_entry: Dict[str, Any] = {
            "status": "payment_link_created",
            "at": now,
            "link_id": link.link_id,
        }
        if payment_mode == "sms_pay_link":
            set_payload["sms_pay_link_to"] = (order.get("address") or {}).get("phone")
            set_payload["sms_pay_link_last_status"] = (
                "sent" if (sms_result or {}).get("success") else "failed"
            )
            set_payload["sms_pay_link_last_sid"] = (sms_result or {}).get("message_sid")
            set_payload["sms_pay_link_sent_at"] = now
            timeline_entry["channel"] = "sms"
            timeline_entry["sms_status"] = set_payload["sms_pay_link_last_status"]
        await db.store_orders.update_one(
            {"order_id": order_id},
            {"$set": set_payload, "$push": {"timeline": timeline_entry}},
        )
    else:
        hold_expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        await db.store_orders.update_one(
            {"order_id": order_id},
            {
                "$set": {
                    **base_set,
                    "payment_status": "awaiting_counter",
                    "hold_expires_at": hold_expires_at,
                },
                "$push": {"timeline": {"status": "hold_created", "at": now, "expires_at": hold_expires_at}},
            },
        )
    out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    return _enrich_store_order(out)


@router.post("/checkout/orders/{order_id}/resend-sms")
async def resend_store_order_sms(
    order_id: str,
    action_token: Optional[str] = Query(default=None),
    optional_user: Optional[dict] = Depends(get_optional_user),
    db=Depends(get_database),
):
    """
    Re-send the SMS pay link for an order that is still awaiting payment.
    Reuses the already-provisioned hosted link (no new Revel call).
    """
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Same auth contract as pay_store_order.
    if optional_user:
        if order.get("customer_id"):
            if order["customer_id"] != optional_user["user_id"]:
                raise HTTPException(status_code=403, detail="Not allowed")
        elif not action_token or action_token != order.get("action_token"):
            raise HTTPException(status_code=401, detail="Order action token required")
    elif not action_token or action_token != order.get("action_token"):
        raise HTTPException(status_code=401, detail="Order action token required")

    if str(order.get("payment_mode") or "") != "sms_pay_link":
        raise HTTPException(status_code=409, detail="Order is not an SMS pay-link order")
    if order.get("payment_status") != "awaiting_payment":
        raise HTTPException(status_code=409, detail="Order is not awaiting payment")
    pay_url = order.get("payment_link_url")
    if not pay_url:
        raise HTTPException(status_code=409, detail="No payment link is available to send yet")
    phone = (order.get("address") or {}).get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Order has no phone number on file")
    if not _twilio_configured():
        raise HTTPException(status_code=503, detail="SMS sending is not configured")

    result = await get_sms_service().send_sms(
        to_phone=phone,
        message=_build_sms_pay_link_message(order_id, pay_url),
    )
    now = _utc_now_iso()
    await db.store_orders.update_one(
        {"order_id": order_id},
        {
            "$set": {
                "sms_pay_link_last_status": "sent" if result.get("success") else "failed",
                "sms_pay_link_last_sid": result.get("message_sid"),
                "sms_pay_link_sent_at": now,
                "updated_at": now,
            },
            "$push": {
                "timeline": {
                    "status": "payment_link_resent",
                    "at": now,
                    "channel": "sms",
                    "sms_status": "sent" if result.get("success") else "failed",
                }
            },
        },
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=result.get("message") or "Failed to send SMS",
        )
    out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    return _enrich_store_order(out)


@router.get("/orders/mine")
async def list_my_store_orders(
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    rows = (
        await db.store_orders.find({"customer_id": current_user["user_id"]}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(length=300)
    )
    return [_enrich_store_order(r) for r in rows]


@router.get("/orders/{order_id}")
async def get_store_order(
    order_id: str,
    current_user: Optional[dict] = Depends(get_optional_user),
    db=Depends(get_database),
):
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    is_owner = order.get("customer_id") == current_user.get("user_id")
    is_ops = has_permission(current_user, Permission.BOOKING_MANAGE) or has_permission(
        current_user, Permission.USER_ROLE_MANAGE
    )
    if not (is_owner or is_ops):
        raise HTTPException(status_code=403, detail="Not allowed")
    return _enrich_store_order(order)


@router.get("/orders/{order_id}/status")
async def get_store_order_status(
    order_id: str,
    action_token: Optional[str] = Query(default=None),
    optional_user: Optional[dict] = Depends(get_optional_user),
    db=Depends(get_database),
):
    """
    H1: re-fetch Revel order state if we're still in a pre-captured status.
    Returns the reconciled order view. Designed to be polled by the SDK
    interceptor (H3) after a pending-verification response.
    """
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if optional_user:
        if order.get("customer_id"):
            if order["customer_id"] != optional_user["user_id"]:
                raise HTTPException(status_code=403, detail="Not allowed")
        elif not action_token or action_token != order.get("action_token"):
            raise HTTPException(status_code=401, detail="Order action token required")
    elif not action_token or action_token != order.get("action_token"):
        raise HTTPException(status_code=401, detail="Order action token required")

    needs_check = order.get("payment_status") in {"pending", "processing", "awaiting_payment"}
    revel_order_id = order.get("revel_order_id")
    if needs_check and revel_order_id:
        try:
            revel = get_revel_service()
            revel_order = await revel.get_order(str(revel_order_id))
        except RevelLiveError:
            revel_order = None
        if revel_order:
            revel_total = float(revel_order.get("total") or 0.0)
            revel_total_money = Money.from_float(revel_total, str(order.get("currency") or "USD"))
            # Very conservative: only update our state when Revel clearly
            # reports a payment resolution.
            revel_status = str(revel_order.get("status") or "").lower()
            if revel_status in {"closed", "paid"}:
                now_iso = _utc_now_iso()
                await db.store_orders.update_one(
                    {
                        "order_id": order_id,
                        "payment_status": {
                            "$in": ["pending", "processing", "awaiting_payment"]
                        },
                    },
                    {
                        "$set": {
                            "payment_status": "captured",
                            "total": revel_total_money.to_float(),
                            "total_cents": revel_total_money.to_cents(),
                            "updated_at": now_iso,
                        }
                    },
                )
                order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0}) or order

    return _enrich_store_order(order)


@router.get("/practitioner/orders")
async def list_practitioner_store_orders(
    current_user: dict = Depends(get_current_active_user),
    status_filter: Optional[str] = Query(default=None),
    db=Depends(get_database),
):
    await _require_order_ops_user(current_user)
    query: Dict[str, Any] = {}
    if status_filter:
        query["fulfillment_status"] = status_filter
    rows = (
        await db.store_orders.find(query, {"_id": 0}).sort("created_at", -1).to_list(length=300)
    )
    if has_permission(current_user, Permission.USER_ROLE_MANAGE):
        return [_enrich_store_order(r) for r in rows]
    # Minimize PII exposure for non-admin operations users.
    redacted: List[Dict[str, Any]] = []
    for row in rows:
        masked = dict(row)
        addr = dict(masked.get("address") or {})
        if addr.get("phone"):
            addr["phone"] = f"***{addr['phone'][-4:]}"
        if addr.get("email") and "@" in addr["email"]:
            name, domain = addr["email"].split("@", 1)
            addr["email"] = f"{name[:2]}***@{domain}"
        for key in ("line1", "line2", "postal_code"):
            if key in addr:
                addr[key] = None
        masked["address"] = addr
        redacted.append(_enrich_store_order(masked))
    return redacted


@router.post("/admin/orders/{order_id}/confirm")
async def admin_confirm_order(
    order_id: str,
    _: AdminOrderActionIn,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    await _require_order_ops_user(current_user)
    existing = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    if existing["fulfillment_status"] not in {"placed"}:
        raise HTTPException(status_code=409, detail="Order cannot be confirmed from current state")
    now = _utc_now_iso()
    result = await db.store_orders.update_one(
        {"order_id": order_id},
        {"$set": {"fulfillment_status": "confirmed", "updated_at": now}, "$push": {"timeline": {"status": "confirmed", "at": now}}},
    )
    return await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})


@router.post("/admin/orders/{order_id}/record-payment")
async def admin_record_offline_payment(
    order_id: str,
    body: AdminOrderActionIn,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """
    Record an in-person / back-office payment for a no-card (pay_offline) order.
    Used until online card capture (Stripe) ships. Card-online and walk-in
    orders settle through Revel and are not eligible here.
    """
    await _require_order_ops_user(current_user)
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if str(order.get("payment_mode") or "") != "pay_offline":
        raise HTTPException(
            status_code=409,
            detail="Only no-card (pay_offline) orders can be settled here",
        )
    if order.get("payment_status") not in {"awaiting_offline_payment", "pending"}:
        raise HTTPException(
            status_code=409,
            detail="Order is not awaiting an offline payment",
        )
    order_total = read_amount_cents_first(
        order, cents_field="total_cents", legacy_field="total", default_currency="USD"
    )
    amount = round(float(body.amount if body.amount is not None else order_total), 2)
    if amount <= 0 or amount > order_total + 0.01:
        raise HTTPException(status_code=400, detail="Payment amount is out of range")
    now = _utc_now_iso()
    updated = await db.store_orders.update_one(
        {
            "order_id": order_id,
            "payment_status": {"$in": ["awaiting_offline_payment", "pending"]},
        },
        {
            "$set": {
                "payment_status": "paid_offline",
                "paid_offline_amount": amount,
                "paid_offline_by": current_user.get("user_id"),
                "paid_offline_at": now,
                "updated_at": now,
            },
            "$push": {
                "timeline": {
                    "status": "payment_recorded",
                    "at": now,
                    "amount": amount,
                    "method": order.get("payment_method"),
                    "by": current_user.get("user_id"),
                }
            },
        },
    )
    if updated.modified_count == 0:
        out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
        return _enrich_store_order(out)
    await record_payment_event(
        db,
        ref_type="store_order",
        ref_id=order_id,
        action="captured",
        amount=amount,
        source="manual_at_counter",
        provider="manual",
        external_id=None,
        metadata={
            "mode": "pay_offline",
            "method": order.get("payment_method"),
            "recorded_by": current_user.get("user_id"),
        },
    )
    out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    return _enrich_store_order(out)


@router.post("/admin/orders/{order_id}/fulfill")
async def admin_fulfill_order(
    order_id: str,
    _: AdminOrderActionIn,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    await _require_order_ops_user(current_user)
    existing = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    if existing["fulfillment_status"] not in {"confirmed", "preparing"}:
        raise HTTPException(status_code=409, detail="Order cannot be fulfilled from current state")
    now = _utc_now_iso()
    result = await db.store_orders.update_one(
        {"order_id": order_id},
        {"$set": {"fulfillment_status": "fulfilled", "updated_at": now}, "$push": {"timeline": {"status": "fulfilled", "at": now}}},
    )
    return await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})


@router.post("/admin/orders/{order_id}/reject")
async def admin_reject_order(
    order_id: str,
    body: AdminOrderActionIn,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    await _require_order_ops_user(current_user)
    if not body.reason:
        raise HTTPException(status_code=400, detail="Reason is required")
    existing = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    if existing["fulfillment_status"] in {"fulfilled", "delivered", "refunded"}:
        raise HTTPException(status_code=409, detail="Order cannot be rejected from current state")
    now = _utc_now_iso()
    result = await db.store_orders.update_one(
        {"order_id": order_id},
        {
            "$set": {"fulfillment_status": "rejected", "rejection_reason": body.reason, "updated_at": now},
            "$push": {"timeline": {"status": "rejected", "at": now, "reason": body.reason}},
        },
    )
    return await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})


@router.post("/admin/orders/{order_id}/refund")
async def admin_refund_order(
    order_id: str,
    body: AdminOrderActionIn,
    request: Request,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    await _require_order_ops_user(current_user)
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("payment_status") in {"awaiting_counter", "awaiting_payment"}:
        raise HTTPException(
            status_code=409,
            detail="Nothing to refund yet. Use POST /admin/orders/{id}/void to cancel the hold.",
        )
    if order.get("payment_status") not in {"captured", "partial_refunded"}:
        raise HTTPException(status_code=409, detail="Only captured payments can be refunded")
    payment_mode = str(order.get("payment_mode") or "card_online")
    tx_id = order.get("revel_transaction_id")
    if payment_mode == "card_online" and not tx_id:
        raise HTTPException(
            status_code=409,
            detail="Order has no Revel transaction id; refund is only available after a successful live capture",
        )
    order_total_f = read_amount_cents_first(
        order, cents_field="total_cents", legacy_field="total", default_currency="USD"
    )
    amount = round(float(body.amount if body.amount is not None else order_total_f), 2)
    if amount <= 0 or amount > order_total_f:
        raise HTTPException(status_code=400, detail="Refund amount is out of range")

    # Require Idempotency-Key on BOTH modes so client retries collapse to a
    # single provider call (walk-in: dedupes on manual_refund_id; card: passed
    # through to Revel).
    idem_header = (request.headers.get("Idempotency-Key") or "").strip()
    if not idem_header:
        raise HTTPException(
            status_code=400,
            detail="Refund requires an Idempotency-Key request header",
        )

    # Atomically reserve capacity AND append a per-attempt reservation entry
    # in a single update so the counter and the array are always in lock-step.
    reservation_attempt_id = _id("rres")
    reservation_now = _utc_now_iso()
    reserve_cents = Money.from_float(amount, str(order.get("currency") or "USD")).to_cents()
    reservation_filter: Dict[str, Any] = {
        "order_id": order_id,
        "payment_status": {"$in": ["captured", "partial_refunded"]},
        "$expr": {
            "$lte": [
                {
                    "$add": [
                        {
                            "$ifNull": [
                                "$refund_amount_reserved_cents",
                                {
                                    "$round": [
                                        {
                                            "$multiply": [
                                                {"$ifNull": ["$refund_amount_reserved", 0]},
                                                100,
                                            ]
                                        },
                                        0,
                                    ]
                                },
                            ]
                        },
                        reserve_cents,
                    ]
                },
                {
                    "$add": [
                        {
                            "$ifNull": [
                                "$total_cents",
                                {
                                    "$round": [
                                        {"$multiply": [{"$ifNull": ["$total", 0]}, 100]},
                                        0,
                                    ]
                                },
                            ]
                        },
                        1,
                    ]
                },
            ]
        },
    }
    if payment_mode == "card_online":
        reservation_filter["revel_transaction_id"] = tx_id
    reservation = await db.store_orders.find_one_and_update(
        reservation_filter,
        {
            "$inc": {"refund_amount_reserved": amount, "refund_amount_reserved_cents": reserve_cents},
            "$set": {"refund_amount_reserved_at": reservation_now},
            "$push": {
                "refund_reservations": {
                    "attempt_id": reservation_attempt_id,
                    "amount": amount,
                    "reserved_at": reservation_now,
                    "status": "live",
                    "idempotency_key": idem_header,
                }
            },
        },
        return_document=True,
        projection={"_id": 0, "refund_amount_reserved": 1, "refund_amount_reserved_cents": 1, "refund_amount": 1},
    )
    if not reservation:
        raise HTTPException(
            status_code=409,
            detail="Refund exceeds remaining captured balance or order is not refundable",
        )
    reserved_after = read_amount_cents_first(
        reservation,
        cents_field="refund_amount_reserved_cents",
        legacy_field="refund_amount_reserved",
        default_currency=str(order.get("currency") or "USD"),
    )
    reserved_before = round(reserved_after - amount, 2)
    refund_cents = int(round(amount * 100))

    async def _release_reservation(reason: str) -> None:
        """
        Decrement the reservation counter only if the corresponding attempt is
        still present in the array. This makes the release idempotent: a
        double-release (e.g. retry of an error path) decrements the counter
        exactly once, preventing it from going negative.
        """
        await db.store_orders.update_one(
            {
                "order_id": order_id,
                "refund_reservations.attempt_id": reservation_attempt_id,
            },
            {
                "$inc": {"refund_amount_reserved": -amount, "refund_amount_reserved_cents": -reserve_cents},
                "$pull": {"refund_reservations": {"attempt_id": reservation_attempt_id}},
            },
        )

    # Branch by payment mode (explicit allowlist so unknown modes fail loudly).
    if payment_mode == "walk_in":
        manual_refund_id = "mref:" + _idempotency_key(
            "store_order", order_id, f"manual_refund:hdr:{idem_header}"
        )[:24]
        existing = await db.store_orders.find_one(
            {"order_id": order_id, "manual_refund_ids": manual_refund_id},
            {"_id": 0, "order_id": 1},
        )
        if existing:
            await _release_reservation("duplicate_manual_refund")
            raise HTTPException(
                status_code=409,
                detail="Duplicate manual refund request; this refund has already been recorded",
            )
        result = {
            "success": True,
            "refund_id": manual_refund_id,
            "amount": amount,
            "status": "manual_refund",
            "mode": "manual",
        }
    elif payment_mode == "card_online":
        # Always pass an explicit amount to Revel. The earlier `None` (full-refund
        # sentinel) optimization was racy under concurrent requests: our
        # reservation counter reflects pending attempts, not what Revel has
        # actually captured as remaining balance.
        refund_to_revel = amount
        # Client-stable idempotency key so retries of the same logical refund
        # hit the same Revel record and never double-charge the customer.
        card_idempotency_dedupe_id = "rref:" + _idempotency_key(
            "store_order", order_id, f"refund:hdr:{idem_header}"
        )[:24]
        # Atomic claim: only one caller wins the key add; concurrent duplicates
        # 409 without ever reaching the provider.
        claim = await db.store_orders.update_one(
            {
                "order_id": order_id,
                "revel_refund_idempotency_keys": {"$ne": card_idempotency_dedupe_id},
            },
            {"$addToSet": {"revel_refund_idempotency_keys": card_idempotency_dedupe_id}},
        )
        if claim.modified_count == 0:
            await _release_reservation("duplicate_card_refund")
            raise HTTPException(
                status_code=409,
                detail="Duplicate card refund request; this refund has already been recorded",
            )
        revel = get_revel_service()
        try:
            result = await revel.refund_payment(
                str(tx_id),
                refund_to_revel,
                idempotency_key=card_idempotency_dedupe_id,
            )
        except Exception as exc:
            # Provider response is uncertain — we DO NOT release the
            # reservation, because a release would let an operator retry with
            # a different header/amount and double-charge the customer if
            # Revel actually processed the original request. The reservation
            # stays live under status=reconciliation_pending so the G2 sweeper
            # can verify against Revel before releasing.
            fail_at = _utc_now_iso()
            await db.store_orders.update_one(
                {
                    "order_id": order_id,
                    "refund_reservations.attempt_id": reservation_attempt_id,
                },
                {
                    "$set": {
                        "refund_reservations.$.status": "reconciliation_pending",
                        "refund_reservations.$.reconciliation_reason": str(exc)[:200],
                    },
                    "$push": {
                        "timeline": {
                            "status": "refund_reconciliation_required",
                            "at": fail_at,
                            "amount": amount,
                            "mode": "card",
                            "attempt_id": reservation_attempt_id,
                            "provider_status": str(exc)[:200],
                        }
                    },
                },
            )
            logger.exception("Revel refund failed for order_id=%s", order_id)
            raise HTTPException(
                status_code=502,
                detail="Refund could not be completed with payment provider",
            ) from exc
    else:
        await _release_reservation("unsupported_payment_mode")
        raise HTTPException(
            status_code=409,
            detail=f"Unsupported payment mode for refund: {payment_mode}",
        )
    if not result.get("success"):
        # Provider-reported failure is also an uncertain state (may or may not
        # have moved money). Keep the reservation live as reconciliation_pending
        # so operators can't retry with a different key and double-charge.
        fail_at = _utc_now_iso()
        fail_mode = "card" if payment_mode == "card_online" else "manual"
        await db.store_orders.update_one(
            {
                "order_id": order_id,
                "refund_reservations.attempt_id": reservation_attempt_id,
            },
            {
                "$set": {
                    "refund_reservations.$.status": "reconciliation_pending",
                    "refund_reservations.$.reconciliation_reason": str(
                        result.get("status") or ""
                    )[:200],
                },
                "$push": {
                    "timeline": {
                        "status": "refund_reconciliation_required",
                        "at": fail_at,
                        "amount": amount,
                        "mode": fail_mode,
                        "attempt_id": reservation_attempt_id,
                        "provider_status": str(result.get("status") or "")[:200],
                    }
                },
            },
        )
        raise HTTPException(
            status_code=502,
            detail=result.get("status", "Refund rejected by payment provider"),
        )

    refund_id = result.get("refund_id") or result.get("transaction_id")
    refund_amount = round(float(result.get("amount", amount)), 2)
    refund_mode = "manual" if payment_mode == "walk_in" else "card"
    now = _utc_now_iso()
    # Defensive: if the provider reports an amount that exceeds what we asked
    # for (or a non-positive amount), do not credit the ledger. Leave the
    # reservation in reconciliation_pending for operator review.
    if refund_amount <= 0 or refund_amount > amount + 0.01:
        await db.store_orders.update_one(
            {
                "order_id": order_id,
                "refund_reservations.attempt_id": reservation_attempt_id,
            },
            {
                "$set": {
                    "refund_reservations.$.status": "reconciliation_pending",
                    "refund_reservations.$.reconciliation_reason":
                        f"provider_amount_mismatch:{refund_amount}",
                },
                "$push": {
                    "timeline": {
                        "status": "refund_reconciliation_required",
                        "at": now,
                        "amount": amount,
                        "provider_amount": refund_amount,
                        "mode": refund_mode,
                        "attempt_id": reservation_attempt_id,
                        "provider_status": "amount_mismatch",
                    }
                },
            },
        )
        raise HTTPException(
            status_code=502,
            detail="Payment provider returned an unexpected refund amount",
        )
    # For card refunds we must have a concrete refund id from the provider to
    # dedupe; otherwise treat the response as reconcile-required.
    if refund_mode == "card" and not refund_id:
        await db.store_orders.update_one(
            {
                "order_id": order_id,
                "refund_reservations.attempt_id": reservation_attempt_id,
            },
            {
                "$set": {
                    "refund_reservations.$.status": "reconciliation_pending",
                    "refund_reservations.$.reconciliation_reason": "missing_refund_id",
                },
                "$push": {
                    "timeline": {
                        "status": "refund_reconciliation_required",
                        "at": now,
                        "amount": amount,
                        "mode": "card",
                        "attempt_id": reservation_attempt_id,
                        "provider_status": "missing_refund_id",
                    }
                },
            },
        )
        raise HTTPException(
            status_code=502,
            detail="Payment provider did not return a refund id",
        )

    accounting_applied = False
    try:
        # Atomically accumulate refund_amount so concurrent refunds both land
        # correctly; derive status afterwards from the post-update total.
        set_payload: Dict[str, Any] = {"updated_at": now}
        push_payload: Dict[str, Any] = {
            "timeline": {
                "status": "refunded",
                "at": now,
                "amount": refund_amount,
                "refund_id": refund_id,
                "mode": refund_mode,
                "initiated_by": current_user.get("user_id"),
                "reason": body.reason,
            },
        }
        # Keep provider-namespaced fields isolated from manual refunds.
        if refund_mode == "card":
            set_payload["revel_refund_id"] = refund_id
            push_payload["revel_refund_ids"] = refund_id
            push_payload["revel_refund_idempotency_keys"] = card_idempotency_dedupe_id
        else:
            set_payload["manual_refund_id"] = refund_id
            push_payload["manual_refund_ids"] = refund_id
        # E3/E4: append to an authoritative refunds[] ledger with SLA stamp.
        expected_done = add_business_days(
            datetime.now(timezone.utc), int(settings.refund_sla_business_days)
        ).isoformat()
        push_payload["refunds"] = {
            "refund_id": refund_id,
            "amount": refund_amount,
            "mode": refund_mode,
            "reason": body.reason,
            "initiated_by": current_user.get("user_id"),
            "initiated_at": now,
            "expected_completion_at": expected_done,
            "status": "pending" if refund_mode == "card" else "completed",
        }
        accounting_filter: Dict[str, Any] = {"order_id": order_id}
        # Final safety net against concurrent application of the same refund id.
        if refund_mode == "card":
            accounting_filter["revel_refund_ids"] = {"$ne": refund_id}
        else:
            accounting_filter["manual_refund_ids"] = {"$ne": refund_id}
        accounting_result = await db.store_orders.update_one(
            accounting_filter,
            {
                "$inc": {
                    "refund_amount": refund_amount,
                    "refund_amount_cents": Money.from_float(
                        refund_amount, str(order.get("currency") or "USD")
                    ).to_cents(),
                },
                "$set": set_payload,
                "$push": push_payload,
            },
        )
        if accounting_result.matched_count == 0:
            # Another concurrent request already applied this refund id.
            # For walk-in the provider was never touched — safe to release.
            # For card the provider has already moved money, so we must NOT
            # release the reservation; leave it reconciliation_pending.
            if refund_mode == "card":
                await db.store_orders.update_one(
                    {
                        "order_id": order_id,
                        "refund_reservations.attempt_id": reservation_attempt_id,
                    },
                    {
                        "$set": {
                            "refund_reservations.$.status": "reconciliation_pending",
                            "refund_reservations.$.reconciliation_reason":
                                "duplicate_refund_id_post_provider",
                        },
                        "$push": {
                            "timeline": {
                                "status": "refund_reconciliation_required",
                                "at": _utc_now_iso(),
                                "amount": refund_amount,
                                "mode": "card",
                                "attempt_id": reservation_attempt_id,
                                "refund_id": refund_id,
                                "provider_status": "duplicate_refund_id",
                            }
                        },
                    },
                )
            else:
                await _release_reservation("duplicate_refund_id")
            raise HTTPException(
                status_code=409,
                detail="Duplicate refund dedupe-id; refund already recorded",
            )
        accounting_applied = True
        await record_payment_event(
            db,
            ref_type="store_order",
            ref_id=order_id,
            action="refunded",
            amount=refund_amount,
            source="manual_at_counter" if refund_mode == "manual" else "api",
            external_id=refund_id,
            metadata={
                "mode": refund_mode,
                "initiated_by": current_user.get("user_id"),
                "idempotency_key": idem_header,
            },
        )
        # Mark the reservation entry committed so the sweeper can tell
        # it apart from still-live reservations.
        await db.store_orders.update_one(
            {"order_id": order_id, "refund_reservations.attempt_id": reservation_attempt_id},
            {
                "$set": {
                    "refund_reservations.$.status": "committed",
                    "refund_reservations.$.refund_id": refund_id,
                    "refund_reservations.$.committed_at": _utc_now_iso(),
                }
            },
        )
        # Guarded state derivation: only write "partial_refunded" when the
        # current refund_amount is still below total, and only "refunded" when it
        # has reached (or exceeded) total. Two racing writers therefore cannot
        # regress each other's status.
        now_iso = _utc_now_iso()
        await db.store_orders.update_one(
            {
                "order_id": order_id,
                "$expr": {"$lt": ["$refund_amount", {"$subtract": ["$total", 0.01]}]},
            },
            {"$set": {"payment_status": "partial_refunded", "updated_at": now_iso}},
        )
        # Cumulative-full transition: only promote fulfillment to refunded when
        # it's still in a pre-delivery / pre-fulfillment state. Physically
        # delivered/completed orders must keep their fulfillment ground truth.
        await db.store_orders.update_one(
            {
                "order_id": order_id,
                "$expr": {"$gte": ["$refund_amount", {"$subtract": ["$total", 0.01]}]},
            },
            {"$set": {"payment_status": "refunded", "updated_at": now_iso}},
        )
        await db.store_orders.update_one(
            {
                "order_id": order_id,
                "$expr": {"$gte": ["$refund_amount", {"$subtract": ["$total", 0.01]}]},
                "fulfillment_status": {
                    "$in": ["placed", "confirmed", "preparing", "fulfilled"]
                },
            },
            {"$set": {"fulfillment_status": "refunded", "updated_at": now_iso}},
        )
    except HTTPException:
        # 409/4xx raised above already released the reservation; just propagate.
        raise
    except Exception:
        # We reach here AFTER the provider reported success. Never release the
        # reservation on this path — doing so would let a subsequent (different
        # amount) attempt pass the reservation cap and double-refund the
        # customer at the provider. Prefer a small reservation "leak" that an
        # operator/G2 reconciliation job can clear over a real double charge.
        fail_at = _utc_now_iso()
        await db.store_orders.update_one(
            {"order_id": order_id},
            {
                "$push": {
                    "timeline": {
                        "status": "refund_reconciliation_required",
                        "at": fail_at,
                        "amount": refund_amount,
                        "mode": refund_mode,
                        "refund_id": refund_id,
                        "detail": (
                            "state_derivation_failed_after_accounting"
                            if accounting_applied
                            else "bookkeeping_failed_after_provider_success"
                        ),
                    }
                }
            },
        )
        logger.exception("Refund bookkeeping failed for order_id=%s", order_id)
        raise

    out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    return _enrich_store_order(out)


@router.post("/admin/orders/{order_id}/void")
async def admin_void_order(
    order_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """
    Cancel an order that hasn't been captured yet (HOLD or awaiting_payment).
    - Cancels any active hosted pay link.
    - Cancels the Revel order if one exists.
    - Does NOT call the refund API (there was no capture).
    """
    await _require_order_ops_user(current_user)
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    ps = order.get("payment_status")
    if ps not in {
        "awaiting_counter",
        "awaiting_payment",
        "awaiting_offline_payment",
        "pending",
        "processing",
    }:
        raise HTTPException(
            status_code=409,
            detail="Order is not in a voidable state (use refund after capture)",
        )

    now = _utc_now_iso()
    link_id = order.get("payment_link_id")
    if link_id:
        try:
            provider = get_payment_link_provider()
            await provider.cancel_link(link_id)
            await db.payment_links.update_one(
                {"link_id": link_id},
                {"$set": {"status": "cancelled", "updated_at": now}},
            )
        except Exception as exc:
            logger.warning(
                "Failed to cancel hosted pay link on void for order_id=%s: %s",
                order_id, exc,
            )
            await db.payment_links.update_one(
                {"link_id": link_id},
                {
                    "$set": {"status": "pending_cancel", "last_cancel_error_at": now},
                    "$inc": {"cancel_attempts": 1},
                },
            )

    revel_order_id = order.get("revel_order_id")
    if revel_order_id:
        try:
            revel = get_revel_service()
            await revel.update_order_status(str(revel_order_id), "cancelled")
        except Exception as exc:
            logger.warning(
                "Failed to cancel Revel order on void for order_id=%s: %s",
                order_id, exc,
            )

    await db.store_orders.update_one(
        {
            "order_id": order_id,
            "payment_status": {"$in": [
                "awaiting_counter", "awaiting_payment", "awaiting_offline_payment",
                "pending", "processing"
            ]},
        },
        {
            "$set": {
                "payment_status": "voided",
                "voided_at": now,
                "voided_by": current_user.get("user_id"),
                "updated_at": now,
            },
            "$unset": {"payment_link_id": "", "payment_link_url": ""},
            "$push": {
                "timeline": {"status": "voided", "at": now, "by": current_user.get("user_id")}
            },
        },
    )
    out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    return _enrich_store_order(out)


class BackfillRevelTxIn(BaseModel):
    revel_transaction_id: str = Field(min_length=1, max_length=80)


@router.post("/admin/orders/{order_id}/backfill-revel-tx")
async def admin_backfill_revel_tx(
    order_id: str,
    body: BackfillRevelTxIn,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """
    Dev/ops-only: stamp a missing revel_transaction_id onto a historical order
    that was captured before we started persisting transaction ids. Requires
    admin/owner role.
    """
    if not has_permission(current_user, Permission.USER_ROLE_MANAGE):
        raise HTTPException(status_code=403, detail="Admin role required")
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("revel_transaction_id"):
        raise HTTPException(
            status_code=409,
            detail="Order already has a revel_transaction_id; backfill refused",
        )
    revel = get_revel_service()
    try:
        # Best-effort verify the transaction exists in Revel before stamping.
        verified = await revel.confirm_payment(body.revel_transaction_id)
    except RevelLiveError as exc:
        logger.exception("Revel tx verify failed for %s", body.revel_transaction_id)
        raise HTTPException(status_code=502, detail="Could not verify transaction with Revel") from exc
    if not verified:
        raise HTTPException(
            status_code=404,
            detail=f"Revel transaction {body.revel_transaction_id} not found",
        )
    now = _utc_now_iso()
    await db.store_orders.update_one(
        {"order_id": order_id, "revel_transaction_id": {"$exists": False}},
        {
            "$set": {
                "revel_transaction_id": body.revel_transaction_id,
                "revel_transaction_status": str(verified.get("status") or "captured"),
                "backfilled_at": now,
                "backfilled_by": current_user.get("user_id"),
                "updated_at": now,
            },
            "$push": {
                "timeline": {
                    "status": "backfilled_revel_tx",
                    "at": now,
                    "by": current_user.get("user_id"),
                    "revel_transaction_id": body.revel_transaction_id,
                }
            },
        },
    )
    out = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    return _enrich_store_order(out)


@router.post("/admin/orders/{order_id}/invoice", status_code=status.HTTP_202_ACCEPTED)
async def send_order_invoice(
    order_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    await _require_order_ops_user(current_user)
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    invoice_id = _id("inv")
    html = f"""
    <html><body>
    <h2>Natural Path Invoice</h2>
    <p>Invoice: {invoice_id}</p>
    <p>Order: {order["order_id"]}</p>
    <p>Total: ${order["total"]:.2f}</p>
    <p>Payment status: {order["payment_status"]}</p>
    </body></html>
    """
    now = _utc_now_iso()
    await db.store_orders.update_one(
        {"order_id": order_id},
        {
            "$set": {
                "invoice_id": invoice_id,
                "invoice_email_status": {"status": "queued"},
                "updated_at": now,
            },
            "$push": {"timeline": {"status": "invoice_queued", "at": now}},
        },
    )
    from workers.notification_worker import send_store_invoice_email
    send_store_invoice_email.delay(
        order_id,
        order["address"]["email"],
        f"Your Natural Path invoice {invoice_id}",
        html,
    )
    return await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
