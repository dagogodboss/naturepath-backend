"""
G2 — daily reconciliation against Revel.

For every store/booking order created or updated in the last 48h, fetch the
matching Revel order and compare key fields (total, payment_status). Any
drift writes a `reconciliation_reports` row and is summarized in a single
ops email.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorClient

from core.config import settings
from core.money_fields import read_amount_cents_first
from infrastructure.external import RevelService, get_email_service
from infrastructure.external.revel_live_client import RevelLiveError
from infrastructure.queue.celery_config import celery_app

logger = logging.getLogger(__name__)


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _check_store_order(db, revel: RevelService, order: Dict[str, Any]) -> List[Dict[str, Any]]:
    revel_order_id = order.get("revel_order_id")
    if not revel_order_id:
        return []
    try:
        revel_order = await revel.get_order(str(revel_order_id))
    except RevelLiveError as exc:
        logger.warning("Reconciliation fetch failed for %s: %s", revel_order_id, exc)
        return []
    if not revel_order:
        return [{
            "drift_type": "missing_remote_order",
            "our_value": None,
            "revel_value": None,
        }]
    drifts: List[Dict[str, Any]] = []
    our_total = round(
        read_amount_cents_first(
            order, cents_field="total_cents", legacy_field="total", default_currency="USD"
        ),
        2,
    )
    revel_total = round(float(revel_order.get("total") or 0.0), 2)
    if abs(our_total - revel_total) > 0.01:
        drifts.append({
            "drift_type": "total_mismatch",
            "our_value": our_total,
            "revel_value": revel_total,
        })
    drifts.extend(_payment_status_drifts(order.get("payment_status"), revel_order))
    return drifts


def _payment_status_drifts(our_payment_status: Any, revel_order: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Conservative status drift checks:
    - If Revel is clearly paid/closed and our state is still pre-capture -> drift.
    - If Revel is clearly refunded and our state is not refunded/partial_refunded -> drift.
    """
    drifts: List[Dict[str, Any]] = []
    our = str(our_payment_status or "").lower()
    revel_status = str(revel_order.get("status") or "").lower()

    if revel_status in {"paid", "closed"} and our in {
        "none",
        "pending",
        "processing",
        "awaiting_payment",
        "awaiting_counter",
        "",
    }:
        drifts.append(
            {
                "drift_type": "payment_status_mismatch",
                "our_value": our or None,
                "revel_value": revel_status,
            }
        )

    if revel_status in {"refunded"} and our not in {"refunded", "partial_refunded"}:
        drifts.append(
            {
                "drift_type": "payment_status_mismatch",
                "our_value": our or None,
                "revel_value": revel_status,
            }
        )
    return drifts


async def _reconcile() -> Dict[str, Any]:
    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        store_rows = await db.store_orders.find(
            {"updated_at": {"$gte": cutoff}, "revel_order_id": {"$ne": None}},
            {
                "_id": 0,
                "order_id": 1,
                "revel_order_id": 1,
                "total": 1,
                "total_cents": 1,
                "payment_status": 1,
            },
        ).to_list(length=1000)
        booking_rows = await db.bookings.find(
            {"updated_at": {"$gte": cutoff}, "revel_order_id": {"$ne": None}},
            {
                "_id": 0,
                "booking_id": 1,
                "revel_order_id": 1,
                "payment_amount": 1,
                "payment_amount_cents": 1,
                "payment_status": 1,
            },
        ).to_list(length=1000)

        revel = RevelService()
        reports: List[Dict[str, Any]] = []

        for order in store_rows:
            for drift in await _check_store_order(db, revel, order):
                report_id = str(uuid.uuid4())
                row = {
                    "report_id": report_id,
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "ref_type": "store_order",
                    "ref_id": order["order_id"],
                    "revel_order_id": order.get("revel_order_id"),
                    "resolved": False,
                    "created_at": datetime.now(timezone.utc),
                    **drift,
                }
                await db.reconciliation_reports.insert_one(row)
                reports.append(row)

        # Booking path: compare amount and terminal payment status.
        for booking in booking_rows:
            try:
                revel_order = await revel.get_order(str(booking["revel_order_id"]))
            except RevelLiveError:
                continue
            if not revel_order:
                continue
            our_amt = round(
                read_amount_cents_first(
                    booking,
                    cents_field="payment_amount_cents",
                    legacy_field="payment_amount",
                    default_currency="USD",
                ),
                2,
            )
            revel_amt = round(float(revel_order.get("total") or 0.0), 2)
            if abs(our_amt - revel_amt) > 0.01:
                row = {
                    "report_id": str(uuid.uuid4()),
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "ref_type": "booking",
                    "ref_id": booking["booking_id"],
                    "revel_order_id": booking.get("revel_order_id"),
                    "drift_type": "total_mismatch",
                    "our_value": our_amt,
                    "revel_value": revel_amt,
                    "resolved": False,
                    "created_at": datetime.now(timezone.utc),
                }
                await db.reconciliation_reports.insert_one(row)
                reports.append(row)
            for drift in _payment_status_drifts(booking.get("payment_status"), revel_order):
                row = {
                    "report_id": str(uuid.uuid4()),
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "ref_type": "booking",
                    "ref_id": booking["booking_id"],
                    "revel_order_id": booking.get("revel_order_id"),
                    "resolved": False,
                    "created_at": datetime.now(timezone.utc),
                    **drift,
                }
                await db.reconciliation_reports.insert_one(row)
                reports.append(row)

        # Summary email to ops (if configured).
        ops_email = getattr(settings, "ops_email", "") or ""
        if reports and ops_email:
            body = "\n".join(
                f"- {r['ref_type']} {r['ref_id']} {r['drift_type']} "
                f"ours={r['our_value']} revel={r['revel_value']}"
                for r in reports[:100]
            )
            email_service = get_email_service()
            try:
                await email_service.send_email(
                    to_email=ops_email,
                    subject=f"[NP] Revel reconciliation drift ({len(reports)} rows)",
                    html_content=f"<pre>{body}</pre>",
                )
            except Exception as exc:
                logger.warning("Ops email send failed: %s", exc)

        return {"reports": len(reports)}
    finally:
        client.close()


@celery_app.task(bind=True, max_retries=2)
def reconcile_revel_orders(self):
    try:
        return run_async(_reconcile())
    except Exception as exc:
        logger.error("reconcile_revel_orders failed: %s", exc)
        self.retry(exc=exc, countdown=300)
