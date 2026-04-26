"""
REVEL POS Webhook Handler
"""
from fastapi import APIRouter, Request, HTTPException, status, BackgroundTasks
import logging
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from core.config import settings
from infrastructure.database import get_database
from infrastructure.external import get_email_service
from infrastructure.payment_events import record_payment_event
from infrastructure.repositories import MongoBookingRepository, MongoPaymentRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def verify_revel_signature(payload: bytes, signature: str) -> bool:
    """Verify REVEL webhook signature"""
    expected = hmac.new(
        settings.revel_api_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _parse_event_timestamp(payload: Dict[str, Any]) -> datetime | None:
    candidates = [
        payload.get("timestamp"),
        payload.get("created_at"),
        payload.get("event_created_at"),
        payload.get("data", {}).get("timestamp"),
    ]
    for value in candidates:
        if not value:
            continue
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                continue
    return None


_ALLOWED_PAYMENT_STATUS = {
    "pending", "processing", "awaiting_payment", "awaiting_counter", "captured",
}
_ALLOWED_FULFILLMENT_STATUS = {
    "placed", "confirmed", "preparing", "fulfilled", "rejected", "cancelled",
}


def _extract_order_id(data: Dict[str, Any]) -> Optional[str]:
    raw = data.get("order_id")
    return str(raw) if raw is not None else None


async def _flip_booking_to_captured(db, link: Dict[str, Any], tx_id_str: Optional[str]) -> bool:
    now = datetime.now(timezone.utc)
    claim = await db.bookings.update_one(
        {
            "booking_id": link["ref_id"],
            "status": {"$in": ["pending", "confirmed", "in_progress"]},
            "payment_status": {
                "$in": ["none", "awaiting_payment", "awaiting_counter", None]
            },
        },
        {
            "$set": {
                "payment_status": "captured",
                "payment_mode": "card_online",
                "payment_amount": float(link.get("amount") or 0.0),
                "revel_transaction_id": tx_id_str,
                "receipt_id": tx_id_str,
                "paid_at": now,
                "updated_at": now.isoformat(),
            },
            "$push": {
                "payment_events": {
                    "action": "captured",
                    "source": "webhook",
                    "amount": float(link.get("amount") or 0.0),
                    "revel_transaction_id": tx_id_str,
                    "at": now,
                }
            },
        },
    )
    return bool(claim.modified_count)


_BOOKING_RECEIPT_STALE_MINUTES = 10


async def _claim_booking_receipt(db, booking_id: str) -> bool:
    """CAS the booking receipt in-progress flag. Also unsticks stale claims."""
    now = datetime.now(timezone.utc)
    stale_cutoff = now.replace(microsecond=0) - timedelta(minutes=_BOOKING_RECEIPT_STALE_MINUTES)
    claim = await db.bookings.update_one(
        {
            "booking_id": booking_id,
            "booking_receipt_sent_at": {"$exists": False},
            "$or": [
                {"booking_receipt_send_in_progress": {"$ne": True}},
                {"booking_receipt_send_started_at": {"$lt": stale_cutoff}},
            ],
        },
        {
            "$set": {
                "booking_receipt_send_in_progress": True,
                "booking_receipt_send_started_at": now,
                "updated_at": now.isoformat(),
            }
        },
    )
    return bool(claim.modified_count)


async def _load_booking_receipt_context(db, booking_id: str):
    booking = await db.bookings.find_one(
        {"booking_id": booking_id},
        {
            "_id": 0,
            "booking_id": 1,
            "customer_id": 1,
            "service_id": 1,
            "slot": 1,
            "payment_mode": 1,
            "payment_amount": 1,
            "total_price": 1,
            "receipt_id": 1,
        },
    )
    if not booking:
        return None, None, None
    customer = await db.users.find_one(
        {"user_id": booking.get("customer_id")},
        {"_id": 0, "email": 1, "first_name": 1, "last_name": 1},
    ) or {}
    service = await db.services.find_one(
        {"service_id": booking.get("service_id")}, {"_id": 0, "name": 1}
    ) or {}
    return booking, customer, service


async def _finalize_booking_receipt_send(
    db, booking_id: str, source_event: str, success: bool
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    if success:
        await db.bookings.update_one(
            {"booking_id": booking_id},
            {
                "$set": {
                    "booking_receipt_sent_at": now_iso,
                    "booking_receipt_source_event": source_event,
                    "booking_receipt_send_in_progress": False,
                    "updated_at": now_iso,
                }
            },
        )
    else:
        await db.bookings.update_one(
            {"booking_id": booking_id},
            {
                "$set": {
                    "booking_receipt_send_in_progress": False,
                    "booking_receipt_send_failed_at": now_iso,
                    "updated_at": now_iso,
                }
            },
        )


async def _send_booking_receipt_if_new(db, booking_id: str, source_event: str) -> None:
    """Idempotent: only one receipt email per booking capture."""
    if not await _claim_booking_receipt(db, booking_id):
        return
    booking, customer, service = await _load_booking_receipt_context(db, booking_id)
    if not booking or not customer.get("email"):
        await _finalize_booking_receipt_send(db, booking_id, source_event, success=False)
        return
    slot = booking.get("slot") or {}
    customer_name = (
        f"{customer.get('first_name') or ''} {customer.get('last_name') or ''}".strip()
        or "there"
    )
    try:
        await get_email_service().send_booking_receipt(
            to_email=customer["email"],
            customer_name=customer_name,
            service_name=service.get("name") or "Appointment",
            date=slot.get("date") or "",
            time=slot.get("start_time") or "",
            booking_id=booking_id,
            amount=float(booking.get("payment_amount") or booking.get("total_price") or 0.0),
            receipt_id=booking.get("receipt_id"),
            payment_mode=booking.get("payment_mode"),
        )
        await _finalize_booking_receipt_send(db, booking_id, source_event, success=True)
    except Exception as exc:
        logger.warning("Booking receipt send failed for %s: %s", booking_id, exc)
        await _finalize_booking_receipt_send(db, booking_id, source_event, success=False)


async def _send_store_receipts_for_paid_event(
    db, order_id: str, event_type: str, tx_id_str: Optional[str]
) -> None:
    store_rows = await db.store_orders.find(
        {"revel_order_id": order_id},
        {
            "_id": 0,
            "order_id": 1,
            "address.email": 1,
            "subtotal": 1,
            "tax": 1,
            "total": 1,
            "revel_transaction_id": 1,
        },
    ).to_list(length=50)
    email_service = get_email_service()
    for row in store_rows:
        await _send_single_store_receipt(db, row, order_id, event_type, tx_id_str, email_service)


_STORE_RECEIPT_STALE_MINUTES = 10


async def _send_single_store_receipt(
    db, row: Dict[str, Any], order_id: str, event_type: str,
    tx_id_str: Optional[str], email_service,
) -> None:
    email = (row.get("address") or {}).get("email")
    if not email:
        return
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=_STORE_RECEIPT_STALE_MINUTES)
    claim = await db.store_orders.update_one(
        {
            "order_id": row.get("order_id"),
            "receipt_sent_at": {"$exists": False},
            "$or": [
                {"receipt_send_in_progress": {"$ne": True}},
                {"receipt_send_started_at": {"$lt": stale_cutoff}},
            ],
        },
        {
            "$set": {
                "receipt_send_in_progress": True,
                "receipt_send_started_at": now,
                "updated_at": now.isoformat(),
            }
        },
    )
    if claim.modified_count == 0:
        return
    try:
        await email_service.send_store_receipt(
            to_email=email,
            order_id=row.get("order_id") or order_id,
            subtotal=float(row.get("subtotal") or 0.0),
            tax=float(row.get("tax") or 0.0),
            total=float(row.get("total") or 0.0),
            transaction_id=row.get("revel_transaction_id") or tx_id_str,
        )
        await db.store_orders.update_one(
            {"order_id": row.get("order_id")},
            {
                "$set": {
                    "receipt_sent_at": datetime.now(timezone.utc).isoformat(),
                    "receipt_source_event": event_type,
                    "receipt_send_in_progress": False,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
    except Exception as exc:
        logger.warning(
            "Store receipt send failed for order_id=%s: %s", row.get("order_id"), exc
        )
        await db.store_orders.update_one(
            {"order_id": row.get("order_id")},
            {
                "$set": {
                    "receipt_send_in_progress": False,
                    "receipt_send_failed_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )


async def _handle_order_paid(db, booking_repo, data: Dict[str, Any], event_type: str) -> None:
    order_id = _extract_order_id(data)
    if not order_id:
        return
    tx_id = data.get("transaction_id") or data.get("payment_id")
    tx_id_str = str(tx_id) if tx_id is not None else None

    link = await db.payment_links.find_one(
        {"revel_order_id": order_id},
        {"_id": 0, "link_id": 1, "ref_type": 1, "ref_id": 1, "amount": 1},
    )
    if link and link.get("ref_type") == "booking":
        if await _flip_booking_to_captured(db, link, tx_id_str):
            await db.payment_links.update_one(
                {"link_id": link["link_id"]},
                {"$set": {"status": "paid", "updated_at": datetime.now(timezone.utc).isoformat()}},
            )
            logger.info(
                "Booking %s marked captured via webhook (tx=%s)", link["ref_id"], tx_id_str
            )
            await record_payment_event(
                db,
                ref_type="booking",
                ref_id=link["ref_id"],
                action="captured",
                amount=float(link.get("amount") or 0.0),
                source="webhook",
                external_id=tx_id_str,
                metadata={"event_type": event_type},
            )
            await _send_booking_receipt_if_new(db, link["ref_id"], event_type)

    if not link or link.get("ref_type") != "booking":
        # Legacy fallback: a booking may still carry `revel_order_id` directly
        # without a payment_links row. Capture tx metadata where available and
        # promote payment_status to captured so revenue reports stay consistent.
        now_iso = datetime.now(timezone.utc).isoformat()
        legacy_set: Dict[str, Any] = {
            "status": "confirmed",
            "updated_at": now_iso,
        }
        if tx_id_str:
            legacy_set["revel_transaction_id"] = tx_id_str
            legacy_set["paid_at"] = datetime.now(timezone.utc)
            legacy_set["payment_status"] = "captured"
            legacy_set["payment_mode"] = "card_online"
        legacy_update = await booking_repo.collection.update_one(
            {
                "revel_order_id": order_id,
                "status": {"$in": ["pending", "confirmed"]},
                "payment_status": {"$nin": ["captured", "refunded", "voided", "failed"]},
            },
            {"$set": legacy_set},
        )
        if legacy_update.modified_count:
            logger.info(
                "Legacy booking confirmed via REVEL webhook for order %s", order_id
            )
            # Mirror the primary path: also send a receipt through the idempotent helper.
            legacy_booking = await booking_repo.collection.find_one(
                {"revel_order_id": order_id}, {"_id": 0, "booking_id": 1}
            )
            if legacy_booking and legacy_booking.get("booking_id"):
                await _send_booking_receipt_if_new(
                    db, legacy_booking["booking_id"], event_type
                )

        store_captured = await db.store_orders.update_many(
            {
                "revel_order_id": order_id,
                "payment_status": {
                    "$in": ["pending", "processing", "awaiting_payment", "awaiting_counter"]
                },
            },
            {
                "$set": {
                    "payment_status": "captured" if tx_id_str else "awaiting_payment",
                    "revel_transaction_id": tx_id_str,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
        if store_captured.modified_count and tx_id_str:
            async for row in db.store_orders.find(
                {"revel_order_id": order_id, "payment_status": "captured"},
                {"_id": 0, "order_id": 1, "total": 1},
            ):
                await record_payment_event(
                    db,
                    ref_type="store_order",
                    ref_id=row["order_id"],
                    action="captured",
                    amount=float(row.get("total") or 0.0),
                    source="webhook",
                    external_id=tx_id_str,
                    metadata={"event_type": event_type},
                )
        await _send_store_receipts_for_paid_event(db, order_id, event_type, tx_id_str)


async def _handle_order_refunded(payment_repo, data: Dict[str, Any]) -> None:
    order_id = _extract_order_id(data)
    if not order_id:
        return
    # Conditional update: never clobber terminal states via the legacy path.
    result = await payment_repo.collection.update_one(
        {
            "revel_order_id": order_id,
            "status": {"$nin": ["refunded", "voided", "failed"]},
        },
        {
            "$set": {
                "status": "refunded",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    if result.modified_count:
        logger.info("Payment row refunded via REVEL webhook for order %s", order_id)


async def _handle_order_cancelled(booking_repo, data: Dict[str, Any]) -> None:
    order_id = _extract_order_id(data)
    if not order_id:
        return
    cancel_update = await booking_repo.collection.update_one(
        {"revel_order_id": order_id, "status": {"$in": ["pending", "confirmed"]}},
        {
            "$set": {
                "status": "cancelled",
                "cancellation_reason": "Cancelled via REVEL POS",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    if cancel_update.modified_count:
        logger.info("Booking cancelled via REVEL webhook for order %s", order_id)


async def _handle_payment_failed(db, data: Dict[str, Any]) -> None:
    order_id = _extract_order_id(data)
    if not order_id:
        return
    reason = str(data.get("reason") or data.get("failure_message") or "")[:300]
    link = await db.payment_links.find_one(
        {"revel_order_id": order_id},
        {"_id": 0, "ref_type": 1, "ref_id": 1, "link_id": 1},
    )
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    # Store side: flip awaiting_payment rows to failed.
    await db.store_orders.update_many(
        {
            "revel_order_id": order_id,
            "payment_status": {"$in": ["pending", "processing", "awaiting_payment"]},
        },
        {
            "$set": {"payment_status": "failed", "updated_at": now_iso},
            "$push": {
                "timeline": {
                    "status": "payment_failed",
                    "at": now_iso,
                    "reason": reason,
                }
            },
        },
    )
    # Booking side: only act via payment_links.
    if link and link.get("ref_type") == "booking":
        await db.bookings.update_one(
            {
                "booking_id": link["ref_id"],
                "payment_status": {"$in": ["awaiting_payment"]},
            },
            {
                "$set": {
                    "payment_status": "failed",
                    "payment_link_last_error": reason,
                    "payment_link_last_error_at": now,
                    "updated_at": now_iso,
                },
                "$push": {
                    "payment_events": {
                        "action": "failed",
                        "source": "webhook",
                        "reason": reason,
                        "at": now,
                    }
                },
            },
        )
        await db.payment_links.update_one(
            {
                "link_id": link["link_id"],
                "status": {"$nin": ["paid", "refunded", "cancelled", "voided"]},
            },
            {"$set": {"status": "failed", "updated_at": now_iso}},
        )


class _UnresolvableRefundAmount(Exception):
    """Raised when we cannot derive the refund amount from any linked record."""


async def _resolve_refund_amount(
    db, order_id: str, reported_amount: float
) -> float:
    """
    When the webhook omits an `amount` (common for full-order `order.refunded`),
    derive the refund as the remaining captured balance on the linked record.

    Raises `_UnresolvableRefundAmount` when nothing can be derived — the caller
    must surface the error so the webhook event stays `processed=false` and
    the retry/reconciliation path can kick in.
    """
    if reported_amount > 0:
        return reported_amount
    store_order = await db.store_orders.find_one(
        {"revel_order_id": order_id},
        {"_id": 0, "total": 1, "refund_amount": 1},
    )
    if store_order and float(store_order.get("total") or 0.0) > 0:
        remaining = round(
            float(store_order["total"]) - float(store_order.get("refund_amount") or 0.0),
            2,
        )
        if remaining > 0:
            return remaining
    link = await db.payment_links.find_one(
        {"revel_order_id": order_id},
        {"_id": 0, "ref_type": 1, "ref_id": 1},
    )
    if link and link.get("ref_type") == "booking":
        booking = await db.bookings.find_one(
            {"booking_id": link["ref_id"]},
            {"_id": 0, "payment_amount": 1, "total_price": 1, "refund_amount": 1},
        )
        if booking:
            captured = float(
                booking.get("payment_amount") or booking.get("total_price") or 0.0
            )
            if captured > 0:
                remaining = round(captured - float(booking.get("refund_amount") or 0.0), 2)
                if remaining > 0:
                    return remaining
    raise _UnresolvableRefundAmount(
        f"Could not derive refund amount for order_id={order_id}"
    )


async def _handle_refund_created(db, data: Dict[str, Any]) -> bool:
    """Returns True if any record was updated (so callers can skip legacy path)."""
    order_id = _extract_order_id(data)
    if not order_id:
        return False
    # Prefer the canonical refund_id for dedupe; fall back to deterministic hash
    # when only a transaction/payment id is present.
    canonical_refund_id = data.get("refund_id")
    if canonical_refund_id:
        refund_id = str(canonical_refund_id)
    else:
        alt = data.get("transaction_id") or data.get("payment_id")
        if alt is None:
            return False
        # Dedupe key intentionally excludes amount — Revel sometimes reports
        # the same refund with different numeric representations on retry.
        refund_id = "dg:" + hashlib.sha256(
            f"{order_id}:{alt}".encode("utf-8")
        ).hexdigest()[:32]
    reported_amount = float(data.get("amount") or 0.0)
    amount = await _resolve_refund_amount(db, order_id, reported_amount)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    if amount <= 0:
        return False
    applied_any = False

    # Store orders: only apply if we haven't recorded this refund id yet AND
    # the additional amount won't push cumulative refunds past captured total.
    applied = await db.store_orders.update_one(
        {
            "revel_order_id": order_id,
            "revel_refund_ids": {"$ne": refund_id},
            "payment_status": {"$in": ["captured", "partial_refunded"]},
            "$expr": {
                "$lte": [
                    {"$add": [{"$ifNull": ["$refund_amount", 0.0]}, amount]},
                    {"$add": ["$total", 0.01]},
                ]
            },
        },
        {
            "$inc": {"refund_amount": amount},
            "$push": {
                "revel_refund_ids": refund_id,
                "timeline": {
                    "status": "refunded",
                    "at": now_iso,
                    "amount": amount,
                    "revel_refund_id": refund_id,
                    "source": "webhook",
                },
            },
            "$set": {"updated_at": now_iso},
        },
    )
    if applied.modified_count:
        applied_any = True
        # Derive new status from cumulative refund_amount.
        await db.store_orders.update_one(
            {
                "revel_order_id": order_id,
                "$expr": {"$lt": ["$refund_amount", {"$subtract": ["$total", 0.01]}]},
            },
            {"$set": {"payment_status": "partial_refunded", "updated_at": now_iso}},
        )
        await db.store_orders.update_one(
            {
                "revel_order_id": order_id,
                "$expr": {"$gte": ["$refund_amount", {"$subtract": ["$total", 0.01]}]},
            },
            {
                "$set": {
                    "payment_status": "refunded",
                    "fulfillment_status": "refunded",
                    "updated_at": now_iso,
                }
            },
        )

    # Booking side via payment_links — incremental refund accumulation.
    link = await db.payment_links.find_one(
        {"revel_order_id": order_id},
        {"_id": 0, "ref_type": 1, "ref_id": 1},
    )
    if link and link.get("ref_type") == "booking":
        booking_applied = await db.bookings.update_one(
            {
                "booking_id": link["ref_id"],
                "payment_status": {"$in": ["captured", "partial_refunded"]},
                "booking_refund_ids": {"$ne": refund_id},
                "$expr": {
                    "$lte": [
                        {"$add": [{"$ifNull": ["$refund_amount", 0.0]}, amount]},
                        {
                            "$add": [
                                {
                                    "$ifNull": [
                                        "$payment_amount",
                                        {"$ifNull": ["$total_price", 0]},
                                    ]
                                },
                                0.01,
                            ]
                        },
                    ]
                },
            },
            {
                "$inc": {"refund_amount": amount},
                "$set": {"updated_at": now_iso},
                "$push": {
                    "booking_refund_ids": refund_id,
                    "payment_events": {
                        "action": "refunded",
                        "source": "webhook",
                        "amount": amount,
                        "revel_refund_id": refund_id,
                        "at": now,
                    },
                },
            },
        )
        if booking_applied.modified_count:
            applied_any = True
            # Derive partial vs full from cumulative refund_amount.
            await db.bookings.update_one(
                {
                    "booking_id": link["ref_id"],
                    "$expr": {
                        "$lt": [
                            "$refund_amount",
                            {
                                "$subtract": [
                                    {
                                        "$ifNull": [
                                            "$payment_amount",
                                            {"$ifNull": ["$total_price", 0]},
                                        ]
                                    },
                                    0.01,
                                ]
                            },
                        ]
                    },
                },
                {"$set": {"payment_status": "partial_refunded", "updated_at": now_iso}},
            )
            await db.bookings.update_one(
                {
                    "booking_id": link["ref_id"],
                    "$expr": {
                        "$gte": [
                            "$refund_amount",
                            {
                                "$subtract": [
                                    {
                                        "$ifNull": [
                                            "$payment_amount",
                                            {"$ifNull": ["$total_price", 0]},
                                        ]
                                    },
                                    0.01,
                                ]
                            },
                        ]
                    },
                },
                {"$set": {"payment_status": "refunded", "updated_at": now_iso}},
            )
    return applied_any


async def _handle_hold_expired(db, data: Dict[str, Any]) -> None:
    order_id = _extract_order_id(data)
    if not order_id:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.store_orders.update_many(
        {
            "revel_order_id": order_id,
            "payment_status": "awaiting_counter",
        },
        {
            "$set": {
                "payment_status": "expired",
                "updated_at": now_iso,
            },
            "$push": {
                "timeline": {"status": "hold_expired", "at": now_iso, "source": "webhook"}
            },
        },
    )


async def _handle_order_status_sync(db, data: Dict[str, Any]) -> None:
    order_id = _extract_order_id(data)
    if not order_id:
        return
    status_value = str(data.get("status") or "").lower() or None
    payment_status = str(data.get("payment_status") or "").lower() or None
    fulfillment_status = str(data.get("fulfillment_status") or "").lower() or None
    tx_id = data.get("transaction_id") or data.get("payment_id")
    update_payload: Dict[str, Any] = {}
    if payment_status in _ALLOWED_PAYMENT_STATUS:
        update_payload["payment_status"] = payment_status
    if fulfillment_status in _ALLOWED_FULFILLMENT_STATUS:
        update_payload["fulfillment_status"] = fulfillment_status
    if (
        status_value in _ALLOWED_FULFILLMENT_STATUS
        and "fulfillment_status" not in update_payload
    ):
        update_payload["fulfillment_status"] = status_value
    if tx_id is not None:
        update_payload["revel_transaction_id"] = str(tx_id)
    if not update_payload:
        return
    update_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.store_orders.update_many(
        {
            "revel_order_id": order_id,
            "payment_status": {
                "$nin": ["captured", "refunded", "partial_refunded", "voided"]
            },
            "fulfillment_status": {
                "$nin": ["refunded", "fulfilled", "cancelled", "rejected"]
            },
        },
        {"$set": update_payload},
    )
    logger.info("Store orders synced from REVEL event for order %s", order_id)


async def process_revel_webhook(event_type: str, data: Dict[str, Any]):
    """Dispatch REVEL webhook events to per-type handlers."""
    db = get_database()
    booking_repo = MongoBookingRepository(db)
    payment_repo = MongoPaymentRepository(db)

    logger.info(f"Processing REVEL webhook: {event_type}")

    if event_type in {"order.paid", "payment.captured"}:
        await _handle_order_paid(db, booking_repo, data, event_type)
    elif event_type in {"payment.failed"}:
        await _handle_payment_failed(db, data)
    elif event_type in {"refund.created", "order.refunded"}:
        applied = await _handle_refund_created(db, data)
        # Only fall back to the legacy payment row update when the new paths
        # did not handle this event (e.g. an orphaned legacy payment record).
        if not applied:
            await _handle_order_refunded(payment_repo, data)
    elif event_type in {"order.hold_expired", "order.expired"}:
        await _handle_hold_expired(db, data)
    elif event_type == "order.cancelled":
        await _handle_order_cancelled(booking_repo, data)
    elif event_type in {"order.finalized", "order.updated"}:
        await _handle_order_status_sync(db, data)


def _require_signature_or_dev_bypass(body: bytes, signature: str) -> None:
    """
    Fail-closed signature verification.

    - In prod/staging-like envs: require a real secret AND a valid signature.
    - In any other env: still require a valid signature unless an explicit
      `ALLOW_UNSIGNED_WEBHOOKS=true` dev flag is set.
    """
    secret = settings.revel_api_secret or ""
    secret_looks_real = bool(secret) and secret != "mock_revel_secret"
    is_production = settings.app_env.lower() in {"production", "prod", "staging"}
    if is_production and not secret_looks_real:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook secret not configured",
        )
    if secret_looks_real:
        if not signature or not verify_revel_signature(body, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )
        return
    if not settings.allow_unsigned_webhooks:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook secret not configured; set REVEL_API_SECRET",
        )
    logger.warning(
        "Revel webhook accepted without signature verification (ALLOW_UNSIGNED_WEBHOOKS=true)"
    )


def _check_timestamp_skew(payload: Dict[str, Any]) -> Optional[datetime]:
    event_ts = _parse_event_timestamp(payload)
    if event_ts is not None:
        skew_seconds = abs((datetime.now(timezone.utc) - event_ts).total_seconds())
        if skew_seconds > settings.revel_webhook_tolerance_seconds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhook event timestamp outside tolerance window",
            )
    return event_ts


def _synthetic_event_id(body: bytes) -> str:
    """Fallback dedupe key when Revel does not send a stable `event_id`."""
    return "sha256:" + hashlib.sha256(body).hexdigest()


_WEBHOOK_IN_FLIGHT_RECLAIM_MINUTES = 5


async def _claim_event_id(
    db, event_id: str, event_type: str, received_at: datetime, event_ts: Optional[datetime]
) -> str:
    """
    Insert a webhook_events row with `processed=false`, relying on the unique
    `(provider, event_id)` index to make this race-safe. Returns:

    - "new": fresh claim (we own processing)
    - "duplicate": already processed successfully
    - "in_flight": someone else is (recently) processing — caller returns 202-ish
    - "retry_claim": previous attempt failed long enough ago that we should re-run
    """
    reclaim_cutoff = received_at - timedelta(minutes=_WEBHOOK_IN_FLIGHT_RECLAIM_MINUTES)
    # Atomic upsert; unique index on (provider, event_id) prevents races.
    result = await db.webhook_events.update_one(
        {"provider": "revel", "event_id": event_id},
        {
            "$setOnInsert": {
                "provider": "revel",
                "event_id": event_id,
                "event_type": event_type,
                "received_at": received_at,
                "event_timestamp": event_ts,
                "processed": False,
            }
        },
        upsert=True,
    )
    if result.upserted_id is not None:
        return "new"

    already = await db.webhook_events.find_one(
        {"provider": "revel", "event_id": event_id},
        {"_id": 0, "processed": 1, "last_error_at": 1, "received_at": 1},
    )
    if already and already.get("processed"):
        return "duplicate"
    last_err = (already or {}).get("last_error_at")
    if last_err and last_err < reclaim_cutoff:
        return "retry_claim"
    # Also retry when the initial receive is older than the reclaim window
    # (covers crashes that never reached the except path to write last_error_at).
    recv = (already or {}).get("received_at")
    if recv and recv < reclaim_cutoff:
        return "retry_claim"
    return "in_flight"


async def _run_and_mark_processed(event_type: str, data: Dict[str, Any], event_id: str) -> None:
    db = get_database()
    try:
        await process_revel_webhook(event_type, data)
        await db.webhook_events.update_one(
            {"provider": "revel", "event_id": event_id},
            {"$set": {"processed": True, "processed_at": datetime.now(timezone.utc)}},
        )
    except Exception as exc:
        logger.exception(
            "Revel webhook handler crashed for event_type=%s event_id=%s: %s",
            event_type, event_id, exc,
        )
        await db.webhook_events.update_one(
            {"provider": "revel", "event_id": event_id},
            {
                "$set": {
                    "processed": False,
                    "last_error": str(exc)[:500],
                    "last_error_at": datetime.now(timezone.utc),
                }
            },
        )


@router.post("/revel")
async def revel_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Handle REVEL POS webhooks (order.paid, order.refunded, order.cancelled, order.finalized/updated)."""
    body = await request.body()
    _require_signature_or_dev_bypass(body, request.headers.get("X-Revel-Signature", ""))

    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning("Invalid JSON webhook body: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    event_type = payload.get("event_type")
    data = payload.get("data", {})
    if not event_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing event_type")

    db = get_database()
    now = datetime.now(timezone.utc)
    event_ts = _check_timestamp_skew(payload)

    event_id = payload.get("event_id") or _synthetic_event_id(body)
    claim_state = await _claim_event_id(db, event_id, event_type, now, event_ts)
    if claim_state == "duplicate":
        return {"status": "duplicate_ignored", "event_type": event_type}
    if claim_state == "in_flight":
        return {"status": "in_flight", "event_type": event_type}

    # claim_state in {"new", "retry_claim"} — process in the background.
    background_tasks.add_task(_run_and_mark_processed, event_type, data, event_id)
    logger.info(f"REVEL webhook received: {event_type}")
    return {"status": "received", "event_type": event_type}


@router.post("/revel/test")
async def test_revel_webhook():
    """Test endpoint for REVEL webhook (development only)"""
    if settings.app_env.lower() in {"production", "prod", "staging"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return {
        "status": "ok",
        "message": "REVEL webhook endpoint is working",
        "supported_events": [
            "order.paid", "payment.captured",
            "payment.failed",
            "refund.created", "order.refunded",
            "order.hold_expired", "order.expired",
            "order.cancelled",
            "order.finalized", "order.updated",
        ],
    }
