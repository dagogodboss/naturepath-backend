"""
Store / Commerce API routes for Natural Path products and orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.rbac import Permission, has_permission
from infrastructure.database import get_database
from infrastructure.external import get_email_service, get_revel_service, get_sms_service
from presentation.dependencies import (
    get_current_active_user,
    get_optional_user,
)

router = APIRouter(prefix="/store", tags=["Store"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


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
    payment_method: str = Field(default="prepaid_online")
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


async def _resolve_store_products(db, q: Optional[str], category: Optional[str], page: int, page_size: int):
    query: Dict[str, Any] = {"is_active_web": True}
    if q:
        query["name"] = {"$regex": q, "$options": "i"}
    if category:
        query["category"] = category
    skip = (page - 1) * page_size
    items = (
        await db.store_products.find(query, {"_id": 0})
        .sort("name", 1)
        .skip(skip)
        .limit(page_size)
        .to_list(length=page_size)
    )
    total = await db.store_products.count_documents(query)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


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
    page_size: int = Query(default=12, ge=1, le=48),
    db=Depends(get_database),
):
    return await _resolve_store_products(db, q, category, page, page_size)


@router.post("/products/by-ids")
async def get_store_products_by_ids(
    body: ProductIdsIn,
    db=Depends(get_database),
):
    rows = await db.store_products.find(
        {"product_id": {"$in": body.product_ids}, "is_active_web": True}, {"_id": 0}
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
    if not (
        has_permission(current_user, Permission.SERVICE_UPDATE)
        or has_permission(current_user, Permission.USER_ROLE_MANAGE)
    ):
        raise HTTPException(status_code=403, detail="Not allowed")
    revel = get_revel_service()
    revel_products = await revel.get_all_products()
    now = _utc_now_iso()
    upserts = 0
    for rp in revel_products:
        doc = {
            "product_id": rp["product_id"],
            "revel_product_id": rp["product_id"],
            "name": rp["name"],
            "category": rp.get("category") or "uncategorized",
            "price": float(rp.get("price", 0)),
            "discount_price": None,
            "stock_qty": 50,
            "is_active": bool(rp.get("is_active", True)),
            "is_active_web": True,
            "image_url": None,
            "updated_at": now,
        }
        await db.store_products.update_one(
            {"product_id": rp["product_id"]},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        upserts += 1
    return {"success": True, "synced": upserts}


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
    db=Depends(get_database),
):
    product_ids = [i.product_id for i in body.items]
    products = (
        await db.store_products.find(
            {"product_id": {"$in": product_ids}, "is_active_web": True}, {"_id": 0}
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
    tax = round(subtotal * 0.0925, 2)
    total = round(subtotal + tax, 2)
    now = _utc_now_iso()
    order_id = _id("np_ord")

    order_doc = {
        "order_id": order_id,
        "customer_id": optional_user.get("user_id") if optional_user else None,
        "items": priced_items,
        "address": body.address.model_dump(),
        "payment_method": body.payment_method,
        "payment_status": "pending",
        "fulfillment_status": "placed",
        "subtotal": round(subtotal, 2),
        "tax": tax,
        "total": total,
        "currency": "USD",
        "customer_note": body.customer_note,
        "revel_order_id": None,
        "payment_link_url": None,
        "invoice_id": None,
        "action_token": _id("act") if optional_user is None else None,
        "timeline": [{"status": "placed", "at": now}],
        "created_at": now,
        "updated_at": now,
    }
    await db.store_orders.insert_one(order_doc)
    return order_doc


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
        if order.get("customer_id") and order["customer_id"] != optional_user["user_id"]:
            raise HTTPException(status_code=403, detail="Not allowed")
    elif not action_token or action_token != order.get("action_token"):
        raise HTTPException(status_code=401, detail="Order action token required")
    if order["payment_status"] == "captured":
        return order
    if order["payment_status"] == "processing":
        raise HTTPException(status_code=409, detail="Payment already processing")
    lock = await db.store_orders.update_one(
        {"order_id": order_id, "payment_status": "pending"},
        {"$set": {"payment_status": "processing", "updated_at": _utc_now_iso()}},
    )
    if lock.matched_count == 0:
        latest = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
        if latest:
            return latest
        raise HTTPException(status_code=404, detail="Order not found")

    revel = get_revel_service()
    customer_id = order.get("customer_id") or "guest"
    revel_order = await revel.create_order(customer_id=customer_id, items=order["items"])
    payment = await revel.process_payment(
        revel_order["order_id"], amount=order["total"], payment_method=payment_method
    )
    payment_status = "captured" if payment.get("success") else "failed"
    now = _utc_now_iso()
    await db.store_orders.update_one(
        {"order_id": order_id},
        {
            "$set": {
                "payment_status": payment_status,
                "revel_order_id": revel_order["order_id"],
                "updated_at": now,
            },
            "$push": {
                "timeline": {
                    "status": "payment_captured" if payment.get("success") else "payment_failed",
                    "at": now,
                }
            },
        },
    )
    return await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})


@router.post("/checkout/orders/{order_id}/sms-pay-link")
async def send_order_sms_pay_link(
    order_id: str,
    action_token: Optional[str] = Query(default=None),
    optional_user: Optional[dict] = Depends(get_optional_user),
    db=Depends(get_database),
):
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if optional_user:
        if order.get("customer_id") and order["customer_id"] != optional_user["user_id"]:
            raise HTTPException(status_code=403, detail="Not allowed")
    elif not action_token or action_token != order.get("action_token"):
        raise HTTPException(status_code=401, detail="Order action token required")
    if order["payment_status"] == "captured":
        raise HTTPException(status_code=400, detail="Order already paid")

    pay_link = f"https://pay.naturalpath.example/orders/{order_id}"
    sms = get_sms_service()
    recipient = order["address"]["phone"]
    message = (
        f"Natural Path: complete your payment for order {order_id[-8:].upper()} here: {pay_link}"
    )
    send_result = await sms.send_sms(recipient, message)
    await db.store_orders.update_one(
        {"order_id": order_id},
        {
            "$set": {"payment_link_url": pay_link, "updated_at": _utc_now_iso()},
            "$push": {"timeline": {"status": "payment_link_sent", "at": _utc_now_iso()}},
        },
    )
    return {"success": True, "order_id": order_id, "payment_link_url": pay_link, "sms": send_result}


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
    return rows


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
    return order


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
        return rows
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
        redacted.append(masked)
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
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    await _require_order_ops_user(current_user)
    order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("payment_status") not in {"captured"}:
        raise HTTPException(status_code=409, detail="Only captured payments can be refunded")
    amount = round(float(body.amount if body.amount is not None else order["total"]), 2)
    if amount > float(order["total"]):
        raise HTTPException(status_code=400, detail="Refund amount cannot exceed order total")
    now = _utc_now_iso()
    await db.store_orders.update_one(
        {"order_id": order_id},
        {
            "$set": {
                "payment_status": "refunded",
                "refund_amount": amount,
                "fulfillment_status": "refunded",
                "updated_at": now,
            },
            "$push": {"timeline": {"status": "refunded", "at": now, "amount": amount}},
        },
    )
    return await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})


@router.post("/admin/orders/{order_id}/invoice")
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
    email = get_email_service()
    send_result = await email.send_email(
        to_email=order["address"]["email"],
        subject=f"Your Natural Path invoice {invoice_id}",
        html_content=html,
    )
    now = _utc_now_iso()
    await db.store_orders.update_one(
        {"order_id": order_id},
        {
            "$set": {"invoice_id": invoice_id, "invoice_email_status": send_result, "updated_at": now},
            "$push": {"timeline": {"status": "invoice_sent", "at": now}},
        },
    )
    return await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
