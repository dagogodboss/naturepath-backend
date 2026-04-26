"""
Booking invoice worker — auto-issues a Revel order + hosted pay link
and emails the customer an invoice. No-ops when hosted payments are disabled.

Concurrency model
-----------------
1. Atomic claim on the booking (`payment_link_issue_in_progress`) using a
   filter that requires `payment_link_id` to not exist yet. Lost claimers
   exit cleanly.
2. Idempotency keys are passed to both Revel order create and hosted link
   create so retries converge to the same provider resources.
3. Final write stamps the booking with `payment_link_id` before clearing
   the in-progress flag; on any error we clear the flag and raise so
   Celery retries with backoff.
"""
import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from core.config import settings
from core.money import Money
from core.money_fields import read_amount_cents_first
from infrastructure.external.email_service import get_email_service
from infrastructure.external.payment_links import get_payment_link_provider
from infrastructure.external.revel_live_client import RevelLiveError
from infrastructure.external.revel_service import RevelService
from infrastructure.queue.celery_config import celery_app

logger = logging.getLogger(__name__)


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _idempotency_key(ref_type: str, ref_id: str, action: str) -> str:
    raw = f"{ref_type}:{ref_id}:{action}:1".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _clear_in_progress(db, booking_id: str, error: Optional[str] = None) -> None:
    update: Dict[str, Any] = {
        "payment_link_issue_in_progress": False,
        "updated_at": _now_iso(),
    }
    if error is not None:
        update["payment_link_last_error"] = error[:500]
        update["payment_link_last_error_at"] = _now_iso()
    await db.bookings.update_one({"booking_id": booking_id}, {"$set": update})


async def _issue_booking_invoice(booking_id: str) -> Dict[str, Any]:
    if not settings.revel_enable_hosted_payments:
        logger.info(
            "Hosted payments disabled; skipping invoice issue for booking_id=%s", booking_id
        )
        return {"skipped": True, "reason": "hosted_payments_disabled"}

    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]

        claim = await db.bookings.update_one(
            {
                "booking_id": booking_id,
                "status": "confirmed",
                "payment_link_id": {"$exists": False},
                "payment_link_issue_in_progress": {"$ne": True},
            },
            {
                "$set": {
                    "payment_link_issue_in_progress": True,
                    "updated_at": _now_iso(),
                }
            },
        )
        if claim.modified_count == 0:
            return {"skipped": True, "reason": "already_claimed_or_issued"}

        try:
            booking = await db.bookings.find_one({"booking_id": booking_id}, {"_id": 0})
            if not booking:
                await _clear_in_progress(db, booking_id, error="booking_not_found")
                return {"error": "booking_not_found"}
            service = await db.services.find_one(
                {"service_id": booking.get("service_id")},
                {"_id": 0, "service_id": 1, "name": 1, "revel_product_id": 1, "price": 1, "discount_price": 1},
            ) or {}
            customer = await db.users.find_one(
                {"user_id": booking.get("customer_id")},
                {"_id": 0, "email": 1, "first_name": 1, "last_name": 1},
            ) or {}
            email = customer.get("email")
            if not email:
                await _clear_in_progress(db, booking_id, error="customer_missing_email")
                return {"skipped": True, "reason": "customer_missing_email"}

            amount = (
                read_amount_cents_first(
                    booking,
                    cents_field="total_price_cents",
                    legacy_field="total_price",
                    default_currency=str(booking.get("currency") or "USD"),
                )
                or float(service.get("discount_price") or service.get("price") or 0)
            )
            money = Money.from_float(amount, "USD")
            currency = "USD"

            revel = RevelService()
            items = []
            if service.get("revel_product_id"):
                items.append(
                    {
                        "product_id": service["revel_product_id"],
                        "quantity": 1,
                        "price": money.to_float(),
                    }
                )
            revel_order = await revel.create_order(
                customer_id=booking.get("customer_id") or "guest",
                items=items,
                idempotency_key=_idempotency_key("booking", booking_id, "create_order"),
            )
            if not revel_order or not revel_order.get("order_id"):
                await _clear_in_progress(db, booking_id, error="revel_no_order_id")
                return {"skipped": True, "reason": "revel_no_order_id"}

            provider = get_payment_link_provider()
            link = await provider.create_link(
                order_ref=str(revel_order["order_id"]),
                amount=money.to_float(),
                currency=currency,
                metadata={"ref_type": "booking", "ref_id": booking_id},
                idempotency_key=_idempotency_key("booking", booking_id, "create_link"),
            )

            now = _now_iso()
            await db.payment_links.update_one(
                {"link_id": link.link_id},
                {
                    "$set": {
                        "link_id": link.link_id,
                        "provider": "revel",
                        "ref_type": "booking",
                        "ref_id": booking_id,
                        "amount": money.to_float(),
                        "amount_cents": money.to_cents(),
                        "currency": currency,
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

            # Tentatively flip booking to card_online awaiting_payment — walk-in path
            # is re-asserted if practitioner later marks paid at counter (C4).
            await db.bookings.update_one(
                {"booking_id": booking_id},
                {
                    "$set": {
                        "revel_order_id": str(revel_order["order_id"]),
                        "payment_mode": "card_online",
                        "payment_status": "awaiting_payment",
                        "payment_amount": money.to_float(),
                        "payment_amount_cents": money.to_cents(),
                        "total_price": money.to_float(),
                        "total_price_cents": money.to_cents(),
                        "currency": currency,
                        "payment_link_id": link.link_id,
                        "payment_link_url": link.url,
                        "payment_link_issue_in_progress": False,
                        "payment_link_pending": False,
                        "updated_at": now,
                    },
                    "$unset": {"payment_link_last_error": "", "payment_link_last_error_at": ""},
                },
            )

            email_service = get_email_service()
            customer_name = (
                f"{customer.get('first_name') or ''} {customer.get('last_name') or ''}".strip()
                or "there"
            )
            slot = booking.get("slot") or {}
            try:
                await email_service.send_booking_invoice(
                    to_email=email,
                    customer_name=customer_name,
                    service_name=service.get("name") or "Appointment",
                    date=slot.get("date") or "",
                    time=slot.get("start_time") or "",
                    booking_id=booking_id,
                    amount=money.to_float(),
                    pay_link_url=link.url,
                    expires_at=link.expires_at,
                )
            except Exception as exc:
                # Email is advisory — practitioner can resend. Record but don't retry.
                logger.warning(
                    "Booking invoice email failed for booking_id=%s: %s", booking_id, exc
                )

            return {
                "booking_id": booking_id,
                "link_id": link.link_id,
                "revel_order_id": revel_order["order_id"],
            }

        except RevelLiveError as exc:
            logger.error("Revel call failed during invoice for %s: %s", booking_id, exc)
            await _clear_in_progress(db, booking_id, error=f"revel:{exc}")
            raise
        except Exception as exc:
            logger.exception("Invoice issuance failed for booking_id=%s", booking_id)
            await _clear_in_progress(db, booking_id, error=str(exc))
            raise
    finally:
        client.close()


@celery_app.task(bind=True, max_retries=3)
def issue_booking_invoice(self, booking_id: str):
    try:
        return run_async(_issue_booking_invoice(booking_id))
    except Exception as exc:
        logger.error("issue_booking_invoice retrying for %s: %s", booking_id, exc)
        self.retry(exc=exc, countdown=60)
