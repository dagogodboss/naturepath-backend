"""
Notification Worker - Celery Background Tasks
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from infrastructure.queue.celery_config import celery_app
from infrastructure.external.email_service import get_email_service
from infrastructure.external.sms_service import get_sms_service
from core.config import settings

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async functions in Celery"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3)
def send_booking_confirmation_email(
    self,
    to_email: str,
    customer_name: str,
    service_name: str,
    practitioner_name: str,
    date: str,
    time: str,
    booking_id: str,
    pay_at_counter: bool = True,
    google_calendar_url: str = "",
    yahoo_calendar_url: str = "",
    outlook_live_url: str = "",
    outlook_office_url: str = "",
    ics_base64: str = "",
):
    """Send booking confirmation email (calendar links + optional .ics)."""
    try:
        email_service = get_email_service()
        result = run_async(
            email_service.send_booking_confirmation(
                to_email=to_email,
                customer_name=customer_name,
                service_name=service_name,
                practitioner_name=practitioner_name,
                date=date,
                time=time,
                booking_id=booking_id,
                pay_at_counter=pay_at_counter,
                google_calendar_url=google_calendar_url or None,
                yahoo_calendar_url=yahoo_calendar_url or None,
                outlook_live_url=outlook_live_url or None,
                outlook_office_url=outlook_office_url or None,
                ics_base64=ics_base64 or None,
            )
        )
        logger.info(f"Booking confirmation email sent: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send booking confirmation email: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def send_practitioner_booking_notice_email(
    self,
    to_email: str,
    practitioner_first_name: str,
    customer_name: str,
    service_name: str,
    date: str,
    time: str,
    booking_id: str,
    google_calendar_url: str = "",
    yahoo_calendar_url: str = "",
    outlook_live_url: str = "",
    outlook_office_url: str = "",
    ics_base64: str = "",
):
    """Notify practitioner of a new booking with the same calendar affordances as the client email."""
    try:
        email_service = get_email_service()
        result = run_async(
            email_service.send_practitioner_booking_notice(
                to_email=to_email,
                practitioner_first_name=practitioner_first_name,
                customer_name=customer_name,
                service_name=service_name,
                date=date,
                time=time,
                booking_id=booking_id,
                google_calendar_url=google_calendar_url or None,
                yahoo_calendar_url=yahoo_calendar_url or None,
                outlook_live_url=outlook_live_url or None,
                outlook_office_url=outlook_office_url or None,
                ics_base64=ics_base64 or None,
            )
        )
        logger.info(f"Practitioner booking notice sent: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send practitioner booking notice: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def send_booking_confirmation_sms(
    self,
    to_phone: str,
    customer_name: str,
    service_name: str,
    date: str,
    time: str
):
    """Send booking confirmation SMS task"""
    try:
        sms_service = get_sms_service()
        result = run_async(
            sms_service.send_booking_confirmation_sms(
                to_phone=to_phone,
                customer_name=customer_name,
                service_name=service_name,
                date=date,
                time=time
            )
        )
        logger.info(f"Booking confirmation SMS sent: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send booking confirmation SMS: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def send_reminder_email(
    self,
    to_email: str,
    customer_name: str,
    service_name: str,
    date: str,
    time: str,
    reminder_kind: str = "d1",
):
    """Send booking reminder email task (d3 / d1 / d0)."""
    try:
        email_service = get_email_service()
        result = run_async(
            email_service.send_booking_reminder(
                to_email=to_email,
                customer_name=customer_name,
                service_name=service_name,
                date=date,
                time=time,
                reminder_kind=reminder_kind,
            )
        )
        logger.info(f"Reminder email sent: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send reminder email: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def send_reminder_sms(
    self,
    to_phone: str,
    customer_name: str,
    service_name: str,
    time: str
):
    """Send booking reminder SMS task"""
    try:
        sms_service = get_sms_service()
        result = run_async(
            sms_service.send_booking_reminder_sms(
                to_phone=to_phone,
                customer_name=customer_name,
                service_name=service_name,
                time=time
            )
        )
        logger.info(f"Reminder SMS sent: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send reminder SMS: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def send_cancellation_notification(
    self,
    to_email: str,
    to_phone: str,
    customer_name: str,
    service_name: str,
    date: str,
    time: str
):
    """Send booking cancellation notification"""
    try:
        email_service = get_email_service()
        sms_service = get_sms_service()
        
        # Send email
        email_result = run_async(
            email_service.send_cancellation_notice(
                to_email=to_email,
                customer_name=customer_name,
                service_name=service_name,
                date=date,
                time=time
            )
        )
        
        # Send SMS if phone provided
        sms_result = None
        if to_phone:
            sms_result = run_async(
                sms_service.send_cancellation_sms(
                    to_phone=to_phone,
                    customer_name=customer_name,
                    service_name=service_name,
                    date=date
                )
            )
        
        return {"email": email_result, "sms": sms_result}
    except Exception as e:
        logger.error(f"Failed to send cancellation notification: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def send_generic_email(
    self,
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = "",
):
    """Generic HTML email — used for non-blocking booking-related notices."""
    try:
        email_service = get_email_service()
        result = run_async(
            email_service.send_email(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                text_content=text_content or None,
            )
        )
        logger.info("Generic email sent to %s: %s", to_email, result)
        return result
    except Exception as e:
        logger.error("Failed to send generic email: %s", e)
        self.retry(exc=e, countdown=60)


async def _deliver_store_invoice(order_id: str, to_email: str, subject: str, html_content: str):
    from motor.motor_asyncio import AsyncIOMotorClient

    result = await get_email_service().send_email(
        to_email=to_email,
        subject=subject,
        html_content=html_content,
    )
    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        now = datetime.now(timezone.utc).isoformat()
        status_value = "sent" if result.get("success") else "failed"
        await client[settings.db_name].store_orders.update_one(
            {"order_id": order_id},
            {
                "$set": {"invoice_email_status": {"status": status_value, **result}, "updated_at": now},
                "$push": {"timeline": {"status": f"invoice_{status_value}", "at": now}},
            },
        )
        if status_value != "sent":
            raise RuntimeError(result.get("message") or "Invoice email failed")
        return result
    finally:
        client.close()


@celery_app.task(bind=True, max_retries=3)
def send_store_invoice_email(
    self,
    order_id: str,
    to_email: str,
    subject: str,
    html_content: str,
):
    """Deliver a store invoice without blocking the admin request."""
    try:
        return run_async(_deliver_store_invoice(order_id, to_email, subject, html_content))
    except Exception as exc:
        logger.error("Failed to send store invoice %s: %s", order_id, exc)
        self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def send_welcome_email(self, to_email: str, customer_name: str):
    """Send welcome email to new customer"""
    try:
        email_service = get_email_service()
        result = run_async(
            email_service.send_welcome_email(
                to_email=to_email,
                customer_name=customer_name
            )
        )
        logger.info(f"Welcome email sent: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")
        self.retry(exc=e, countdown=60)


REMINDER_OFFSETS = {
    "d3": 3,
    "d1": 1,
    "d0": 0,
}


async def _send_daily_reminders() -> dict:
    """
    Send 3-day / 1-day / day-of reminder emails for confirmed single bookings.

    Idempotent via booking.reminders_sent.{d3|d1|d0}. Skips cancelled and
    inactive recurrence intent does not block reminders for the booked slot itself.
    Full monthly series materialization is out of scope for MVP.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    from core.config import settings

    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.db_name]
    try:
        from core.time_utils import clinic_now

        today = clinic_now().date()
    except Exception:
        today = datetime.now(timezone.utc).date()
    sent = {"d3": 0, "d1": 0, "d0": 0, "skipped": 0, "errors": 0}

    try:
        for kind, days_ahead in REMINDER_OFFSETS.items():
            target = (today + timedelta(days=days_ahead)).isoformat()
            cursor = db.bookings.find(
                {
                    "status": {"$in": ["confirmed", "pending"]},
                    "slot.date": target,
                    f"reminders_sent.{kind}": {"$ne": True},
                },
                {"_id": 0},
            )
            bookings = await cursor.to_list(length=500)
            for booking in bookings:
                booking_id = booking.get("booking_id")
                # Claim idempotency before send to avoid duplicate emails on overlap.
                claim = await db.bookings.update_one(
                    {
                        "booking_id": booking_id,
                        f"reminders_sent.{kind}": {"$ne": True},
                    },
                    {"$set": {f"reminders_sent.{kind}": True}},
                )
                if claim.modified_count == 0:
                    sent["skipped"] += 1
                    continue

                customer = await db.users.find_one(
                    {"user_id": booking.get("customer_id")},
                    {"_id": 0, "email": 1, "first_name": 1, "last_name": 1, "phone": 1},
                )
                service = await db.services.find_one(
                    {"service_id": booking.get("service_id")},
                    {"_id": 0, "name": 1},
                )
                if not customer or not customer.get("email"):
                    sent["skipped"] += 1
                    continue

                slot = booking.get("slot") or {}
                try:
                    send_reminder_email.delay(
                        to_email=customer["email"],
                        customer_name=f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
                        or "there",
                        service_name=(service or {}).get("name") or "Appointment",
                        date=slot.get("date") or target,
                        time=slot.get("start_time") or "",
                        reminder_kind=kind,
                    )
                    if customer.get("phone") and kind in ("d1", "d0"):
                        send_reminder_sms.delay(
                            to_phone=customer["phone"],
                            customer_name=customer.get("first_name") or "there",
                            service_name=(service or {}).get("name") or "Appointment",
                            time=slot.get("start_time") or "",
                        )
                    sent[kind] += 1
                except Exception as exc:
                    logger.error(
                        "Failed to queue reminder %s for booking %s: %s",
                        kind,
                        booking_id,
                        exc,
                    )
                    # Allow retry on next beat tick
                    await db.bookings.update_one(
                        {"booking_id": booking_id},
                        {"$unset": {f"reminders_sent.{kind}": ""}},
                    )
                    sent["errors"] += 1
    finally:
        client.close()

    return {"status": "completed", **sent}


@celery_app.task
def send_daily_reminders():
    """
    Periodic task: 3d / 1d / day-of booking reminder emails.
    Scheduled hourly via celery beat (send-booking-reminders).
    """
    logger.info("Running booking reminder check (d3/d1/d0)...")
    try:
        result = run_async(_send_daily_reminders())
        logger.info("Reminder run result: %s", result)
        return result
    except Exception as e:
        logger.error("Failed to process daily reminders: %s", e)
        return {"status": "error", "message": str(e)}
