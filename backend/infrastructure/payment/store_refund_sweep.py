"""
G2 follow-up — sweep stuck store card refunds.

When `admin_refund_order` leaves a `refund_reservations` entry in
`reconciliation_pending` (uncertain Revel outcome), this module retries the
same Revel idempotency key and finalizes Mongo accounting when the provider
now reports success. If the refund id was already recorded (rare race), it
releases the reservation capacity only.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.config import settings
from core.money import Money
from core.time_utils import add_business_days
from infrastructure.external import get_revel_service
from infrastructure.payment_events import record_payment_event

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _idempotency_key(ref_type: str, ref_id: str, action: str, attempt_no: int = 1) -> str:
    raw = f"{ref_type}:{ref_id}:{action}:{attempt_no}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _card_dedupe_id(order_id: str, idem_header: str) -> str:
    return "rref:" + _idempotency_key("store_order", order_id, f"refund:hdr:{idem_header}")[:24]


def _parse_iso_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


async def _release_reservation(
    db: AsyncIOMotorDatabase,
    *,
    order_id: str,
    attempt_id: str,
    amount: float,
    reserve_cents: int,
) -> None:
    await db.store_orders.update_one(
        {"order_id": order_id, "refund_reservations.attempt_id": attempt_id},
        {
            "$inc": {
                "refund_amount_reserved": -amount,
                "refund_amount_reserved_cents": -reserve_cents,
            },
            "$pull": {"refund_reservations": {"attempt_id": attempt_id}},
        },
    )


async def _apply_store_refund_accounting(
    db: AsyncIOMotorDatabase,
    *,
    order_id: str,
    order: Dict[str, Any],
    reservation_attempt_id: str,
    refund_amount: float,
    refund_id: str,
    card_idempotency_dedupe_id: str,
    idem_header: str,
) -> str:
    """
    Apply the same post-provider Mongo updates as admin_refund_order.
    Returns: applied | already_applied | rejected
    """
    refund_mode = "card"
    now = _utc_now_iso()
    currency = str(order.get("currency") or settings.default_currency or "USD")

    if refund_amount <= 0:
        return "rejected"

    set_payload: Dict[str, Any] = {"updated_at": now}
    push_payload: Dict[str, Any] = {
        "timeline": {
            "status": "refunded",
            "at": now,
            "amount": refund_amount,
            "refund_id": refund_id,
            "mode": refund_mode,
            "initiated_by": "system:refund_reconciliation_sweep",
            "reason": "refund_reconciliation_sweep",
        },
    }
    set_payload["revel_refund_id"] = refund_id
    push_payload["revel_refund_ids"] = refund_id
    push_payload["revel_refund_idempotency_keys"] = card_idempotency_dedupe_id

    expected_done = add_business_days(
        datetime.now(timezone.utc), int(settings.refund_sla_business_days)
    ).isoformat()
    push_payload["refunds"] = {
        "refund_id": refund_id,
        "amount": refund_amount,
        "mode": refund_mode,
        "reason": "refund_reconciliation_sweep",
        "initiated_by": "system:refund_reconciliation_sweep",
        "initiated_at": now,
        "expected_completion_at": expected_done,
        "status": "pending",
    }

    accounting_filter: Dict[str, Any] = {
        "order_id": order_id,
        "revel_refund_ids": {"$ne": refund_id},
    }
    accounting_result = await db.store_orders.update_one(
        accounting_filter,
        {
            "$inc": {
                "refund_amount": refund_amount,
                "refund_amount_cents": Money.from_float(refund_amount, currency).to_cents(),
            },
            "$set": set_payload,
            "$push": push_payload,
        },
    )
    if accounting_result.modified_count == 0:
        existing_ids = order.get("revel_refund_ids") or []
        if refund_id in existing_ids:
            return "already_applied"
        return "rejected"

    await record_payment_event(
        db,
        ref_type="store_order",
        ref_id=order_id,
        action="refunded",
        amount=refund_amount,
        source="refund_reconciliation_sweep",
        external_id=refund_id,
        metadata={
            "mode": refund_mode,
            "initiated_by": "system:refund_reconciliation_sweep",
            "idempotency_key": idem_header,
        },
    )
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
    now_iso = _utc_now_iso()
    await db.store_orders.update_one(
        {
            "order_id": order_id,
            "$expr": {"$lt": ["$refund_amount", {"$subtract": ["$total", 0.01]}]},
        },
        {"$set": {"payment_status": "partial_refunded", "updated_at": now_iso}},
    )
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
            "fulfillment_status": {"$in": ["placed", "confirmed", "preparing", "fulfilled"]},
        },
        {"$set": {"fulfillment_status": "refunded", "updated_at": now_iso}},
    )
    await db.store_orders.update_one(
        {"order_id": order_id},
        {
            "$push": {
                "timeline": {
                    "status": "refund_sweep_applied",
                    "at": now_iso,
                    "attempt_id": reservation_attempt_id,
                    "refund_id": refund_id,
                    "amount": refund_amount,
                }
            }
        },
    )
    return "applied"


async def sweep_store_refund_reconciliation_pending(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """
    Process a bounded batch of store_orders with card refund reservations stuck
    in reconciliation_pending.
    """
    min_age = timedelta(minutes=int(settings.refund_reconciliation_sweep_min_age_minutes))
    max_batch = int(settings.refund_reconciliation_sweep_max_batch)
    max_attempts = int(settings.refund_reconciliation_sweep_max_attempts)
    cutoff = datetime.now(timezone.utc) - min_age

    rows = await (
        db.store_orders.find(
            {"refund_reservations": {"$elemMatch": {"status": "reconciliation_pending"}}},
            {"_id": 0, "order_id": 1},
        )
        .limit(max_batch)
        .to_list(length=max_batch)
    )
    order_ids: List[str] = [r["order_id"] for r in rows]

    stats = {
        "orders_seen": len(order_ids),
        "reservations_attempted": 0,
        "applied": 0,
        "released_duplicate": 0,
        "still_pending": 0,
        "errors": 0,
        "exhaustion_reports": 0,
    }

    revel = get_revel_service()

    for order_id in order_ids:
        order = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0})
        if not order:
            continue
        payment_mode = str(order.get("payment_mode") or "card_online")
        if payment_mode != "card_online":
            continue
        tx_id = order.get("revel_transaction_id")
        if not tx_id:
            continue

        for res in list(order.get("refund_reservations") or []):
            if res.get("status") != "reconciliation_pending":
                continue
            reserved_at = _parse_iso_ts(str(res.get("reserved_at") or ""))
            if reserved_at and reserved_at > cutoff:
                continue

            attempt_id = str(res.get("attempt_id") or "")
            if not attempt_id:
                continue
            idem_header = (res.get("idempotency_key") or "").strip()
            if not idem_header:
                logger.warning("Sweep skip order_id=%s attempt missing idempotency_key", order_id)
                continue

            amount = round(float(res.get("amount") or 0.0), 2)
            if amount <= 0:
                continue

            reserve_cents = Money.from_float(amount, str(order.get("currency") or "USD")).to_cents()
            card_dedupe = _card_dedupe_id(order_id, idem_header)

            prior_sweeps = int(res.get("sweep_attempts") or 0)
            this_sweep = prior_sweeps + 1
            await db.store_orders.update_one(
                {"order_id": order_id, "refund_reservations.attempt_id": attempt_id},
                {
                    "$inc": {"refund_reservations.$.sweep_attempts": 1},
                    "$set": {"refund_reservations.$.sweep_last_at": _utc_now_iso()},
                },
            )

            stats["reservations_attempted"] += 1

            try:
                result = await revel.refund_payment(
                    str(tx_id),
                    amount,
                    idempotency_key=card_dedupe,
                )
            except Exception as exc:
                stats["errors"] += 1
                logger.warning(
                    "Refund sweep Revel retry failed order_id=%s attempt=%s: %s",
                    order_id,
                    attempt_id,
                    exc,
                )
                if await _maybe_emit_exhausted_report(
                    db, order_id, attempt_id, this_sweep, max_attempts, str(exc)[:200]
                ):
                    stats["exhaustion_reports"] += 1
                stats["still_pending"] += 1
                continue

            if not result.get("success"):
                if await _maybe_emit_exhausted_report(
                    db,
                    order_id,
                    attempt_id,
                    this_sweep,
                    max_attempts,
                    str(result.get("status") or "provider_failure")[:200],
                ):
                    stats["exhaustion_reports"] += 1
                stats["still_pending"] += 1
                continue

            refund_id = result.get("refund_id") or result.get("transaction_id")
            refund_amount = round(float(result.get("amount", amount)), 2)
            if refund_amount <= 0 or refund_amount > amount + 0.01:
                stats["still_pending"] += 1
                await db.store_orders.update_one(
                    {"order_id": order_id, "refund_reservations.attempt_id": attempt_id},
                    {
                        "$set": {
                            "refund_reservations.$.reconciliation_reason": (
                                f"sweep_amount_mismatch:{refund_amount}"
                            )[:200],
                        }
                    },
                )
                continue
            if not refund_id:
                stats["still_pending"] += 1
                continue

            fresh = await db.store_orders.find_one({"order_id": order_id}, {"_id": 0}) or order
            outcome = await _apply_store_refund_accounting(
                db,
                order_id=order_id,
                order=fresh,
                reservation_attempt_id=attempt_id,
                refund_amount=refund_amount,
                refund_id=str(refund_id),
                card_idempotency_dedupe_id=card_dedupe,
                idem_header=idem_header,
            )
            if outcome == "applied":
                stats["applied"] += 1
            elif outcome == "already_applied":
                await _release_reservation(
                    db,
                    order_id=order_id,
                    attempt_id=attempt_id,
                    amount=amount,
                    reserve_cents=reserve_cents,
                )
                await db.store_orders.update_one(
                    {"order_id": order_id},
                    {
                        "$push": {
                            "timeline": {
                                "status": "refund_sweep_released_reservation",
                                "at": _utc_now_iso(),
                                "attempt_id": attempt_id,
                                "refund_id": str(refund_id),
                                "detail": "Refund already recorded; released duplicate reservation",
                            }
                        }
                    },
                )
                stats["released_duplicate"] += 1
            else:
                stats["still_pending"] += 1

    return stats


async def _maybe_emit_exhausted_report(
    db: AsyncIOMotorDatabase,
    order_id: str,
    attempt_id: str,
    sweep_attempt_no: int,
    max_attempts: int,
    detail: str,
) -> bool:
    """Insert a single ops-visible report when sweep retries are exhausted."""
    if sweep_attempt_no < max_attempts:
        return False
    claimed = await db.store_orders.update_one(
        {
            "order_id": order_id,
            "refund_reservations": {
                "$elemMatch": {
                    "attempt_id": attempt_id,
                    "sweep_exhaust_reported": {"$ne": True},
                }
            },
        },
        {"$set": {"refund_reservations.$.sweep_exhaust_reported": True}},
    )
    if claimed.modified_count == 0:
        return False
    report_id = str(uuid.uuid4())
    row = {
        "report_id": report_id,
        "date": datetime.now(timezone.utc).date().isoformat(),
        "ref_type": "store_order_refund_sweep",
        "ref_id": order_id,
        "revel_order_id": None,
        "resolved": False,
        "created_at": datetime.now(timezone.utc),
        "drift_type": "refund_reconciliation_sweep_exhausted",
        "our_value": attempt_id,
        "revel_value": detail[:300],
    }
    await db.reconciliation_reports.insert_one(row)
    return True
