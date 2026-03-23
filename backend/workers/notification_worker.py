"""
Notification Worker - Celery Background Tasks
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from infrastructure.queue.celery_config import celery_app
from infrastructure.external.email_service import get_email_service
from infrastructure.external.sms_service import get_sms_service

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
    booking_id: str
):
    """Send booking confirmation email task"""
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
                booking_id=booking_id
            )
        )
        logger.info(f"Booking confirmation email sent: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send booking confirmation email: {e}")
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
    time: str
):
    """Send booking reminder email task"""
    try:
        email_service = get_email_service()
        result = run_async(
            email_service.send_booking_reminder(
                to_email=to_email,
                customer_name=customer_name,
                service_name=service_name,
                date=date,
                time=time
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


@celery_app.task
def send_daily_reminders():
    """
    Periodic task to send reminders for tomorrow's bookings
    Runs every hour to catch all bookings
    """
    logger.info("Running daily reminder check...")
    # This would query the database for tomorrow's bookings
    # and trigger reminder emails/SMS for each
    # Implementation depends on direct DB access or API call
    return {"status": "completed", "message": "Daily reminders processed"}
