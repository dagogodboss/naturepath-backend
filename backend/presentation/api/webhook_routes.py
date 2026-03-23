"""
REVEL POS Webhook Handler
"""
from fastapi import APIRouter, Request, HTTPException, status, BackgroundTasks
import logging
import hashlib
import hmac
from typing import Dict, Any
from core.config import settings
from infrastructure.database import get_database
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


async def process_revel_webhook(event_type: str, data: Dict[str, Any]):
    """Process REVEL webhook event"""
    db = get_database()
    booking_repo = MongoBookingRepository(db)
    payment_repo = MongoPaymentRepository(db)
    
    logger.info(f"Processing REVEL webhook: {event_type}")
    
    if event_type == "order.paid":
        # Update booking status when order is paid
        order_id = data.get("order_id")
        if order_id:
            bookings = await booking_repo.collection.find(
                {"revel_order_id": order_id},
                {"_id": 0}
            ).to_list(length=1)
            
            if bookings:
                booking = bookings[0]
                await booking_repo.update(booking["booking_id"], {"status": "confirmed"})
                logger.info(f"Booking {booking['booking_id']} confirmed via REVEL webhook")
    
    elif event_type == "order.refunded":
        # Handle refund
        order_id = data.get("order_id")
        if order_id:
            payment = await payment_repo.collection.find_one(
                {"revel_order_id": order_id},
                {"_id": 0}
            )
            if payment:
                await payment_repo.update(payment["payment_id"], {"status": "refunded"})
                logger.info(f"Payment {payment['payment_id']} refunded via REVEL webhook")
    
    elif event_type == "order.cancelled":
        # Handle cancellation
        order_id = data.get("order_id")
        if order_id:
            bookings = await booking_repo.collection.find(
                {"revel_order_id": order_id},
                {"_id": 0}
            ).to_list(length=1)
            
            if bookings:
                booking = bookings[0]
                await booking_repo.update(booking["booking_id"], {
                    "status": "cancelled",
                    "cancellation_reason": "Cancelled via REVEL POS"
                })
                logger.info(f"Booking {booking['booking_id']} cancelled via REVEL webhook")


@router.post("/revel")
async def revel_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Handle REVEL POS webhooks
    
    Supported events:
    - order.paid
    - order.refunded
    - order.cancelled
    """
    # Get raw body for signature verification
    body = await request.body()
    
    # Verify signature (in production)
    signature = request.headers.get("X-Revel-Signature", "")
    if settings.app_env == "production" and not verify_revel_signature(body, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature"
        )
    
    # Parse payload
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")
    
    event_type = payload.get("event_type")
    data = payload.get("data", {})
    
    if not event_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing event_type")
    
    # Process webhook in background
    background_tasks.add_task(process_revel_webhook, event_type, data)
    
    logger.info(f"REVEL webhook received: {event_type}")
    return {"status": "received", "event_type": event_type}


@router.post("/revel/test")
async def test_revel_webhook():
    """Test endpoint for REVEL webhook (development only)"""
    if settings.app_env == "production":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    
    return {
        "status": "ok",
        "message": "REVEL webhook endpoint is working",
        "supported_events": ["order.paid", "order.refunded", "order.cancelled"]
    }
