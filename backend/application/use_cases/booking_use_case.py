"""
Booking Use Cases - Application Layer
Handles the complete booking flow with REVEL POS integration
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from domain.entities import (
    Booking, BookingSlot, BookingStatus,
    PaymentReference, PaymentStatus,
    generate_id, utc_now
)
from domain.events import (
    BookingCreatedEvent, BookingConfirmedEvent,
    BookingCancelledEvent, BookingRescheduledEvent,
    PaymentInitiatedEvent, PaymentConfirmedEvent
)
from infrastructure.repositories import (
    MongoBookingRepository,
    MongoAvailabilitySlotRepository,
    MongoServiceRepository,
    MongoPractitionerRepository,
    MongoUserRepository,
    MongoPaymentRepository,
    MongoEventRepository
)
from infrastructure.external import get_revel_service
from infrastructure.cache import CacheService
from workers.notification_worker import (
    send_booking_confirmation_email,
    send_booking_confirmation_sms,
    send_cancellation_notification
)
from workers.booking_worker import create_revel_order, process_booking_payment

logger = logging.getLogger(__name__)


class BookingUseCase:
    """Booking use cases with REVEL POS integration"""
    
    def __init__(
        self,
        booking_repo: MongoBookingRepository,
        slot_repo: MongoAvailabilitySlotRepository,
        service_repo: MongoServiceRepository,
        practitioner_repo: MongoPractitionerRepository,
        user_repo: MongoUserRepository,
        payment_repo: MongoPaymentRepository,
        event_repo: MongoEventRepository,
        cache: Optional[CacheService] = None
    ):
        self.booking_repo = booking_repo
        self.slot_repo = slot_repo
        self.service_repo = service_repo
        self.practitioner_repo = practitioner_repo
        self.user_repo = user_repo
        self.payment_repo = payment_repo
        self.event_repo = event_repo
        self.cache = cache
        self.revel_service = get_revel_service()
    
    async def initiate_booking(
        self,
        customer_id: str,
        service_id: str,
        practitioner_id: str,
        date: str,
        start_time: str,
        end_time: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Initiate a booking (Step 1 of booking flow)
        Creates a draft booking without locking slots yet
        """
        # Validate service exists and is active
        service = await self.service_repo.get_by_id(service_id)
        if not service or not service.get("is_active"):
            raise ValueError("Service not found or inactive")
        
        # Validate practitioner exists
        practitioner = await self.practitioner_repo.get_by_id(practitioner_id)
        if not practitioner:
            raise ValueError("Practitioner not found")
        
        # Validate practitioner offers this service
        if service_id not in practitioner.get("services", []):
            raise ValueError("Practitioner does not offer this service")
        
        # Validate with REVEL POS if service has revel_product_id
        if service.get("revel_product_id"):
            revel_product = await self.revel_service.validate_service(service["revel_product_id"])
            if not revel_product:
                logger.warning(f"Service {service_id} not found in REVEL POS")
        
        # Create booking in draft status
        booking = Booking(
            booking_id=generate_id(),
            customer_id=customer_id,
            practitioner_id=practitioner_id,
            service_id=service_id,
            slot=BookingSlot(date=date, start_time=start_time, end_time=end_time),
            status=BookingStatus.DRAFT,
            total_price=service.get("discount_price") or service["price"],
            notes=notes
        )
        
        booking_dict = booking.model_dump()
        booking_dict["created_at"] = booking_dict["created_at"].isoformat()
        booking_dict["updated_at"] = booking_dict["updated_at"].isoformat()
        booking_dict["slot"] = {
            "date": date,
            "start_time": start_time,
            "end_time": end_time
        }
        
        await self.booking_repo.create(booking_dict)
        
        # Fetch the booking from DB (to avoid _id mutation issue)
        created_booking = await self.booking_repo.get_by_id(booking.booking_id)
        
        # Store event
        event = BookingCreatedEvent(
            booking_id=booking.booking_id,
            customer_id=customer_id,
            practitioner_id=practitioner_id,
            service_id=service_id,
            date=date,
            start_time=start_time,
            total_price=booking.total_price
        )
        await self.event_repo.store_event(event.model_dump())
        
        logger.info(f"Booking initiated: {booking.booking_id}")
        
        return {
            **created_booking,
            "service": service,
            "practitioner": practitioner
        }
    
    async def lock_slot(
        self,
        booking_id: str,
        user_id: str,
        lock_duration_seconds: int = 300
    ) -> Dict[str, Any]:
        """
        Lock a time slot for booking (Step 2 of booking flow)
        Prevents race conditions during checkout
        """
        booking = await self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise ValueError("Booking not found")
        
        if booking["customer_id"] != user_id:
            raise ValueError("Unauthorized")
        
        if booking["status"] != "draft":
            raise ValueError("Booking is not in draft status")
        
        # Find or create availability slot
        slot = booking["slot"]
        slots = await self.slot_repo.get_available_slots(
            booking["practitioner_id"],
            slot["date"]
        )
        
        # Find matching slot
        target_slot = None
        for s in slots:
            if s["start_time"] == slot["start_time"]:
                target_slot = s
                break
        
        if not target_slot:
            # Check if slot exists but is not available
            all_slots = await self.slot_repo.collection.find({
                "practitioner_id": booking["practitioner_id"],
                "date": slot["date"],
                "start_time": slot["start_time"]
            }, {"_id": 0}).to_list(length=1)
            
            if all_slots:
                raise ValueError("Time slot is no longer available")
            
            # Create the slot if it doesn't exist
            target_slot = {
                "slot_id": generate_id(),
                "practitioner_id": booking["practitioner_id"],
                "date": slot["date"],
                "start_time": slot["start_time"],
                "end_time": slot["end_time"],
                "status": "available",
                "created_at": utc_now().isoformat()
            }
            await self.slot_repo.create(target_slot)
        
        # Lock the slot
        locked = await self.slot_repo.lock_slot(
            target_slot["slot_id"],
            user_id,
            lock_duration_seconds
        )
        
        if not locked:
            raise ValueError("Failed to lock slot - may already be locked")
        
        # Update booking status
        await self.booking_repo.update(booking_id, {"status": "pending"})
        
        # Invalidate cache
        if self.cache:
            await self.cache.delete(
                CacheService.availability_key(booking["practitioner_id"], slot["date"])
            )
        
        logger.info(f"Slot locked for booking: {booking_id}")
        
        return {
            "booking_id": booking_id,
            "slot_id": target_slot["slot_id"],
            "locked_until": (utc_now() + timedelta(seconds=lock_duration_seconds)).isoformat(),
            "status": "pending"
        }
    
    async def confirm_booking(
        self,
        booking_id: str,
        user_id: str,
        payment_method: str = "card"
    ) -> Dict[str, Any]:
        """
        Confirm booking and process payment through REVEL POS (Step 3 of booking flow)
        """
        booking = await self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise ValueError("Booking not found")
        
        if booking["customer_id"] != user_id:
            raise ValueError("Unauthorized")
        
        if booking["status"] not in ["draft", "pending"]:
            raise ValueError(f"Cannot confirm booking in {booking['status']} status")
        
        # Get related data
        service = await self.service_repo.get_by_id(booking["service_id"])
        customer = await self.user_repo.get_by_id(user_id)
        practitioner = await self.practitioner_repo.get_by_id(booking["practitioner_id"])
        practitioner_user = await self.user_repo.get_by_id(practitioner["user_id"])
        
        # Create REVEL order
        revel_order = await self.revel_service.create_order(
            customer_id=user_id,
            items=[{
                "product_id": service.get("revel_product_id", service["service_id"]),
                "name": service["name"],
                "quantity": 1,
                "price": booking["total_price"]
            }]
        )
        
        # Process payment through REVEL
        payment_result = await self.revel_service.process_payment(
            order_id=revel_order["order_id"],
            amount=revel_order["total"],
            payment_method=payment_method
        )
        
        if not payment_result.get("success"):
            # Release the slot if payment fails
            slot = booking["slot"]
            slots = await self.slot_repo.collection.find({
                "practitioner_id": booking["practitioner_id"],
                "date": slot["date"],
                "start_time": slot["start_time"]
            }, {"_id": 0}).to_list(length=1)
            if slots:
                await self.slot_repo.release_slot(slots[0]["slot_id"])
            
            raise ValueError(f"Payment failed: {payment_result.get('message')}")
        
        # Create payment reference
        payment_ref = PaymentReference(
            payment_id=generate_id(),
            booking_id=booking_id,
            customer_id=user_id,
            amount=revel_order["total"],
            status=PaymentStatus.COMPLETED,
            revel_transaction_id=payment_result["transaction_id"],
            revel_order_id=revel_order["order_id"],
            payment_method=payment_method,
            completed_at=utc_now()
        )
        
        payment_dict = payment_ref.model_dump()
        payment_dict["created_at"] = payment_dict["created_at"].isoformat()
        payment_dict["updated_at"] = payment_dict["updated_at"].isoformat()
        payment_dict["completed_at"] = payment_dict["completed_at"].isoformat()
        
        await self.payment_repo.create(payment_dict.copy())  # Use copy to avoid _id mutation
        
        # Fetch the payment from DB to get clean data
        created_payment = await self.payment_repo.get_by_id(payment_ref.payment_id)
        
        # Update booking
        now = utc_now()
        await self.booking_repo.update(booking_id, {
            "status": "confirmed",
            "revel_order_id": revel_order["order_id"],
            "payment_reference_id": payment_ref.payment_id,
            "confirmed_at": now.isoformat()
        })
        
        # Update slot status
        slot = booking["slot"]
        slots = await self.slot_repo.collection.find({
            "practitioner_id": booking["practitioner_id"],
            "date": slot["date"],
            "start_time": slot["start_time"]
        }, {"_id": 0}).to_list(length=1)
        if slots:
            await self.slot_repo.update(slots[0]["slot_id"], {
                "status": "booked",
                "booking_id": booking_id
            })
        
        # Store events
        confirm_event = BookingConfirmedEvent(
            booking_id=booking_id,
            customer_id=user_id,
            practitioner_id=booking["practitioner_id"],
            revel_order_id=revel_order["order_id"]
        )
        await self.event_repo.store_event(confirm_event.model_dump())
        
        payment_event = PaymentConfirmedEvent(
            payment_id=payment_ref.payment_id,
            booking_id=booking_id,
            revel_transaction_id=payment_result["transaction_id"]
        )
        await self.event_repo.store_event(payment_event.model_dump())
        
        # Send notifications (async via Celery)
        try:
            send_booking_confirmation_email.delay(
                to_email=customer["email"],
                customer_name=f"{customer['first_name']} {customer['last_name']}",
                service_name=service["name"],
                practitioner_name=f"{practitioner_user['first_name']} {practitioner_user['last_name']}",
                date=slot["date"],
                time=slot["start_time"],
                booking_id=booking_id
            )
            
            if customer.get("phone"):
                send_booking_confirmation_sms.delay(
                    to_phone=customer["phone"],
                    customer_name=customer["first_name"],
                    service_name=service["name"],
                    date=slot["date"],
                    time=slot["start_time"]
                )
        except Exception as e:
            logger.warning(f"Failed to queue notifications: {e}")
        
        logger.info(f"Booking confirmed: {booking_id}")
        
        # Return updated booking
        updated_booking = await self.booking_repo.get_by_id(booking_id)
        return {
            **updated_booking,
            "payment": created_payment,
            "revel_order": revel_order
        }
    
    async def cancel_booking(
        self,
        booking_id: str,
        user_id: str,
        reason: Optional[str] = None,
        is_admin: bool = False
    ) -> Dict[str, Any]:
        """Cancel a booking"""
        booking = await self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise ValueError("Booking not found")
        
        # Check authorization
        if not is_admin and booking["customer_id"] != user_id:
            raise ValueError("Unauthorized")
        
        if booking["status"] in ["cancelled", "completed"]:
            raise ValueError(f"Cannot cancel booking in {booking['status']} status")
        
        # Get customer and service info for notifications
        customer = await self.user_repo.get_by_id(booking["customer_id"])
        service = await self.service_repo.get_by_id(booking["service_id"])
        
        # Process refund if payment was made
        if booking.get("payment_reference_id"):
            payment = await self.payment_repo.get_by_id(booking["payment_reference_id"])
            if payment and payment.get("revel_transaction_id"):
                refund_result = await self.revel_service.refund_payment(
                    payment["revel_transaction_id"]
                )
                await self.payment_repo.update(payment["payment_id"], {
                    "status": "refunded"
                })
                logger.info(f"Refund processed: {refund_result}")
        
        # Release the slot
        slot = booking["slot"]
        slots = await self.slot_repo.collection.find({
            "practitioner_id": booking["practitioner_id"],
            "date": slot["date"],
            "start_time": slot["start_time"]
        }, {"_id": 0}).to_list(length=1)
        if slots:
            await self.slot_repo.release_slot(slots[0]["slot_id"])
        
        # Update booking
        await self.booking_repo.update(booking_id, {
            "status": "cancelled",
            "cancellation_reason": reason
        })
        
        # Store event
        event = BookingCancelledEvent(
            booking_id=booking_id,
            customer_id=booking["customer_id"],
            practitioner_id=booking["practitioner_id"],
            cancellation_reason=reason
        )
        await self.event_repo.store_event(event.model_dump())
        
        # Send notification
        try:
            send_cancellation_notification.delay(
                to_email=customer["email"],
                to_phone=customer.get("phone"),
                customer_name=f"{customer['first_name']} {customer['last_name']}",
                service_name=service["name"],
                date=slot["date"],
                time=slot["start_time"]
            )
        except Exception as e:
            logger.warning(f"Failed to queue cancellation notification: {e}")
        
        # Invalidate cache
        if self.cache:
            await self.cache.delete(
                CacheService.availability_key(booking["practitioner_id"], slot["date"])
            )
        
        logger.info(f"Booking cancelled: {booking_id}")
        
        return await self.booking_repo.get_by_id(booking_id)
    
    async def get_customer_bookings(
        self,
        customer_id: str,
        include_details: bool = True
    ) -> List[Dict[str, Any]]:
        """Get all bookings for a customer"""
        bookings = await self.booking_repo.get_by_customer(customer_id)
        
        if include_details:
            for booking in bookings:
                booking["service"] = await self.service_repo.get_by_id(booking["service_id"])
                practitioner = await self.practitioner_repo.get_by_id(booking["practitioner_id"])
                if practitioner:
                    practitioner_user = await self.user_repo.get_by_id(practitioner["user_id"])
                    booking["practitioner"] = {
                        **practitioner,
                        "user": practitioner_user
                    }
        
        return bookings

    async def get_practitioner_bookings(
        self,
        practitioner_id: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict[str, Any]]:
        """Bookings for a practitioner in a date range, with service + customer."""
        bookings = await self.booking_repo.get_by_date_range(
            start_date, end_date, practitioner_id
        )
        for booking in bookings:
            booking["service"] = await self.service_repo.get_by_id(booking["service_id"])
            customer = await self.user_repo.get_by_id(booking["customer_id"])
            if customer:
                customer.pop("password_hash", None)
            booking["customer"] = customer
        return bookings
    
    async def get_booking_by_id(
        self,
        booking_id: str,
        user_id: str,
        is_admin: bool = False
    ) -> Dict[str, Any]:
        """Get a specific booking with details"""
        booking = await self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise ValueError("Booking not found")
        
        # Check authorization
        if not is_admin and booking["customer_id"] != user_id:
            # Check if user is the practitioner
            practitioner = await self.practitioner_repo.get_by_id(booking["practitioner_id"])
            if not practitioner or practitioner["user_id"] != user_id:
                raise ValueError("Unauthorized")
        
        # Add details
        booking["service"] = await self.service_repo.get_by_id(booking["service_id"])
        booking["customer"] = await self.user_repo.get_by_id(booking["customer_id"])
        if booking["customer"]:
            booking["customer"].pop("password_hash", None)
        
        practitioner = await self.practitioner_repo.get_by_id(booking["practitioner_id"])
        if practitioner:
            practitioner_user = await self.user_repo.get_by_id(practitioner["user_id"])
            if practitioner_user:
                practitioner_user.pop("password_hash", None)
            booking["practitioner"] = {
                **practitioner,
                "user": practitioner_user
            }
        
        return booking
