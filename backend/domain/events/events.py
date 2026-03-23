"""
Domain Events - Event-Driven Architecture
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid


def generate_event_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainEvent(BaseModel):
    """Base class for all domain events"""
    event_id: str = Field(default_factory=generate_event_id)
    event_type: str
    timestamp: datetime = Field(default_factory=utc_now)
    metadata: Dict[str, Any] = {}


# ==================== Booking Events ====================
class BookingCreatedEvent(DomainEvent):
    """Event fired when a booking is created"""
    event_type: str = "booking.created"
    booking_id: str
    customer_id: str
    practitioner_id: str
    service_id: str
    date: str
    start_time: str
    total_price: float


class BookingConfirmedEvent(DomainEvent):
    """Event fired when a booking is confirmed"""
    event_type: str = "booking.confirmed"
    booking_id: str
    customer_id: str
    practitioner_id: str
    revel_order_id: Optional[str] = None


class BookingCancelledEvent(DomainEvent):
    """Event fired when a booking is cancelled"""
    event_type: str = "booking.cancelled"
    booking_id: str
    customer_id: str
    practitioner_id: str
    cancellation_reason: Optional[str] = None


class BookingCompletedEvent(DomainEvent):
    """Event fired when a booking is completed"""
    event_type: str = "booking.completed"
    booking_id: str
    customer_id: str
    practitioner_id: str


class BookingRescheduledEvent(DomainEvent):
    """Event fired when a booking is rescheduled"""
    event_type: str = "booking.rescheduled"
    booking_id: str
    old_date: str
    old_start_time: str
    new_date: str
    new_start_time: str


# ==================== Payment Events ====================
class PaymentInitiatedEvent(DomainEvent):
    """Event fired when payment is initiated"""
    event_type: str = "payment.initiated"
    payment_id: str
    booking_id: str
    amount: float


class PaymentConfirmedEvent(DomainEvent):
    """Event fired when payment is confirmed"""
    event_type: str = "payment.confirmed"
    payment_id: str
    booking_id: str
    revel_transaction_id: Optional[str] = None


class PaymentFailedEvent(DomainEvent):
    """Event fired when payment fails"""
    event_type: str = "payment.failed"
    payment_id: str
    booking_id: str
    error_message: str


# ==================== Notification Events ====================
class NotificationTriggeredEvent(DomainEvent):
    """Event fired when a notification should be sent"""
    event_type: str = "notification.triggered"
    user_id: str
    notification_type: str
    title: str
    message: str
    send_email: bool = True
    send_sms: bool = False
    metadata: Dict[str, Any] = {}


# ==================== Slot Events ====================
class SlotLockedEvent(DomainEvent):
    """Event fired when a slot is locked"""
    event_type: str = "slot.locked"
    slot_id: str
    practitioner_id: str
    locked_by: str
    locked_until: datetime


class SlotReleasedEvent(DomainEvent):
    """Event fired when a slot is released"""
    event_type: str = "slot.released"
    slot_id: str
    practitioner_id: str
