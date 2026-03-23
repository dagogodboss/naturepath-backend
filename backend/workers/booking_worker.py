"""
Booking Worker - Celery Background Tasks
"""
import asyncio
import logging
from infrastructure.queue.celery_config import celery_app
from infrastructure.external.revel_service import get_revel_service

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
def process_booking_payment(
    self,
    booking_id: str,
    order_id: str,
    amount: float,
    payment_method: str = "card"
):
    """Process booking payment through REVEL POS"""
    try:
        revel_service = get_revel_service()
        result = run_async(
            revel_service.process_payment(
                order_id=order_id,
                amount=amount,
                payment_method=payment_method
            )
        )
        logger.info(f"Payment processed for booking {booking_id}: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to process payment for booking {booking_id}: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def create_revel_order(
    self,
    booking_id: str,
    customer_id: str,
    service_id: str,
    service_name: str,
    price: float
):
    """Create order in REVEL POS"""
    try:
        revel_service = get_revel_service()
        result = run_async(
            revel_service.create_order(
                customer_id=customer_id,
                items=[{
                    "product_id": service_id,
                    "name": service_name,
                    "quantity": 1,
                    "price": price
                }]
            )
        )
        logger.info(f"REVEL order created for booking {booking_id}: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to create REVEL order for booking {booking_id}: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def sync_customer_to_revel(
    self,
    customer_id: str,
    email: str,
    name: str,
    phone: str = None
):
    """Sync customer data to REVEL POS"""
    try:
        revel_service = get_revel_service()
        result = run_async(
            revel_service.sync_customer({
                "customer_id": customer_id,
                "email": email,
                "name": name,
                "phone": phone
            })
        )
        logger.info(f"Customer synced to REVEL: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to sync customer to REVEL: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_refund(
    self,
    booking_id: str,
    transaction_id: str,
    amount: float = None
):
    """Process refund through REVEL POS"""
    try:
        revel_service = get_revel_service()
        result = run_async(
            revel_service.refund_payment(
                transaction_id=transaction_id,
                amount=amount
            )
        )
        logger.info(f"Refund processed for booking {booking_id}: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to process refund for booking {booking_id}: {e}")
        self.retry(exc=e, countdown=60)
