"""
Booking Use Cases - Application Layer
Handles the complete booking flow (OTC payment at counter; Revel is store/e-commerce only).
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from domain.entities import (
    Booking, BookingSlot, BookingStatus,
    generate_id, utc_now
)
from domain.events import (
    BookingCreatedEvent, BookingConfirmedEvent,
    BookingCancelledEvent, BookingRescheduledEvent,
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
from core.calendar_utils import (
    build_booking_ical,
    google_calendar_template_url,
    ical_to_base64,
    microsoft_calendar_template_url,
    outlook_office_calendar_template_url,
)
from core.money import Money
from infrastructure.cache import CacheService
from core.config import settings
from workers.notification_worker import (
    send_booking_confirmation_email,
    send_booking_confirmation_sms,
    send_cancellation_notification,
    send_practitioner_booking_notice_email,
)
from workers.booking_invoice_worker import issue_booking_invoice

logger = logging.getLogger(__name__)


class BookingUseCase:
    """Booking use cases (no Revel; e-commerce uses Revel separately)."""
    
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

    @staticmethod
    def _is_discovery_service(service: Optional[Dict[str, Any]]) -> bool:
        if not service:
            return False
        if service.get("is_discovery_entry") is True:
            return True
        name = str(service.get("name", "")).strip().lower()
        return "discovery call" in name

    @staticmethod
    def _slot_key(start_time: str, end_time: str) -> str:
        return f"{start_time}-{end_time}"

    @staticmethod
    def _weekly_hourly_windows(practitioner: Dict[str, Any], date: str) -> List[Dict[str, str]]:
        """Derive hourly slot windows from the practitioner's weekly availability profile."""
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        day_of_week = date_obj.weekday()
        windows: List[Dict[str, str]] = []
        for avail in practitioner.get("availability", []):
            if avail.get("day_of_week") != day_of_week or not avail.get("is_available", True):
                continue
            start_hour = int(str(avail["start_time"]).split(":")[0])
            end_hour = int(str(avail["end_time"]).split(":")[0])
            for hour in range(start_hour, end_hour):
                windows.append(
                    {
                        "start_time": f"{hour:02d}:00",
                        "end_time": f"{hour + 1:02d}:00",
                    }
                )
        return windows

    async def _candidate_slots_for_practitioner(
        self,
        practitioner: Dict[str, Any],
        date: str,
    ) -> List[Dict[str, str]]:
        """
        Return bookable slot windows for this practitioner on a given date.

        Merges (1) concrete Mongo rows with status=available and (2) hourly
        windows implied by weekly availability for any hour that does not yet
        have a concrete availability_slots row (any status). This avoids the
        trap where a single generated row for a day hid the rest of the weekly
        schedule from booking/discovery flows.
        """
        practitioner_id = practitioner["practitioner_id"]
        available = await self.slot_repo.get_available_slots(practitioner_id, date)
        concrete_for_date = await self.slot_repo.list_slot_windows_for_practitioner_date(
            practitioner_id, date
        )
        occupied_keys = {
            self._slot_key(s["start_time"], s["end_time"]) for s in concrete_for_date
        }

        merged: Dict[str, Dict[str, str]] = {}
        for s in available:
            k = self._slot_key(s["start_time"], s["end_time"])
            merged[k] = {"start_time": s["start_time"], "end_time": s["end_time"]}

        for w in self._weekly_hourly_windows(practitioner, date):
            k = self._slot_key(w["start_time"], w["end_time"])
            if k in merged or k in occupied_keys:
                continue
            merged[k] = w

        return sorted(merged.values(), key=lambda w: w["start_time"])

    async def _eligible_practitioners(self, service_id: str) -> List[Dict[str, Any]]:
        practitioners = await self.practitioner_repo.get_by_service(service_id)
        eligible: List[Dict[str, Any]] = []
        for practitioner in practitioners:
            user = await self.user_repo.get_by_id(practitioner["user_id"])
            if user and user.get("is_active", True):
                eligible.append(practitioner)
        return eligible

    async def get_service_available_slots(
        self,
        service_id: str,
        date: str,
    ) -> List[Dict[str, str]]:
        practitioners = await self._eligible_practitioners(service_id)
        if not practitioners:
            return []
        windows_map: Dict[str, Dict[str, str]] = {}
        for practitioner in practitioners:
            windows = await self._candidate_slots_for_practitioner(practitioner, date)
            for w in windows:
                windows_map[self._slot_key(w["start_time"], w["end_time"])] = {
                    "start_time": w["start_time"],
                    "end_time": w["end_time"],
                }
        return sorted(windows_map.values(), key=lambda w: w["start_time"])

    async def _select_practitioner_round_robin(
        self,
        service_id: str,
        date: str,
        start_time: str,
        end_time: str,
    ) -> Dict[str, Any]:
        """
        Pick a practitioner who is both service-eligible and slot-available.
        Round-robin cursor persists in Mongo collection booking_assignment_state.
        """
        practitioners = await self._eligible_practitioners(service_id)
        candidates: List[Dict[str, Any]] = []
        for practitioner in practitioners:
            windows = await self._candidate_slots_for_practitioner(practitioner, date)
            if any(
                w["start_time"] == start_time and w["end_time"] == end_time
                for w in windows
            ):
                candidates.append(practitioner)
        if not candidates:
            raise ValueError("No practitioner available for this time slot")

        candidates = sorted(candidates, key=lambda p: p["practitioner_id"])
        state_coll = self.booking_repo.collection.database.booking_assignment_state
        state_key = f"service:{service_id}"
        state = await state_coll.find_one({"state_key": state_key}, {"_id": 0})
        last_id = (state or {}).get("last_practitioner_id")
        chosen = candidates[0]
        if last_id:
            ids = [c["practitioner_id"] for c in candidates]
            if last_id in ids:
                chosen = candidates[(ids.index(last_id) + 1) % len(candidates)]
        return chosen

    async def _persist_assignment_cursor(self, service_id: str, practitioner_id: str) -> None:
        state_coll = self.booking_repo.collection.database.booking_assignment_state
        await state_coll.update_one(
            {"state_key": f"service:{service_id}"},
            {
                "$set": {
                    "state_key": f"service:{service_id}",
                    "last_practitioner_id": practitioner_id,
                    "updated_at": utc_now().isoformat(),
                }
            },
            upsert=True,
        )
    
    async def initiate_booking(
        self,
        customer_id: str,
        service_id: str,
        practitioner_id: Optional[str],
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

        # Enforce discovery-first booking on the backend for non-discovery services.
        if not self._is_discovery_service(service):
            eligibility = await self.get_discovery_eligibility(customer_id)
            if not eligibility.get("is_discovery_completed"):
                raise ValueError(
                    "Discovery call required before booking this service"
                )
        
        practitioner: Optional[Dict[str, Any]] = None
        # Backward-compatible path: explicit practitioner still accepted.
        if practitioner_id:
            practitioner = await self.practitioner_repo.get_by_id(practitioner_id)
            if not practitioner:
                raise ValueError("Practitioner not found")
            if service_id not in practitioner.get("services", []):
                raise ValueError("Practitioner does not offer this service")
            windows = await self._candidate_slots_for_practitioner(practitioner, date)
            if not any(w["start_time"] == start_time and w["end_time"] == end_time for w in windows):
                raise ValueError("Practitioner is not available for this time slot")
        else:
            practitioner = await self._select_practitioner_round_robin(
                service_id=service_id,
                date=date,
                start_time=start_time,
                end_time=end_time,
            )
            practitioner_id = practitioner["practitioner_id"]
        
        # Create booking in draft status
        price_money = Money.from_float(service.get("discount_price") or service["price"], "USD")
        booking = Booking(
            booking_id=generate_id(),
            customer_id=customer_id,
            practitioner_id=practitioner_id,
            service_id=service_id,
            slot=BookingSlot(date=date, start_time=start_time, end_time=end_time),
            status=BookingStatus.DRAFT,
            total_price=price_money.to_float(),
            payment_mode=None,
            payment_status="none",
            notes=notes
        )
        
        booking_dict = booking.model_dump()
        booking_dict["total_price_cents"] = price_money.to_cents()
        booking_dict["currency"] = "USD"
        booking_dict["created_at"] = booking_dict["created_at"].isoformat()
        booking_dict["updated_at"] = booking_dict["updated_at"].isoformat()
        booking_dict["slot"] = {
            "date": date,
            "start_time": start_time,
            "end_time": end_time
        }
        
        await self.booking_repo.create(booking_dict)
        await self._persist_assignment_cursor(service_id, practitioner_id)
        
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
        
        slot = booking["slot"]
        pid = booking["practitioner_id"]
        date = slot["date"]
        st = slot["start_time"]
        et = slot["end_time"]

        # Single upsert so concurrent lockers cannot create duplicate rows for the same window.
        new_slot_id = generate_id()
        await self.slot_repo.collection.update_one(
            {"practitioner_id": pid, "date": date, "start_time": st},
            {
                "$setOnInsert": {
                    "slot_id": new_slot_id,
                    "practitioner_id": pid,
                    "date": date,
                    "start_time": st,
                    "end_time": et,
                    "status": "available",
                    "created_at": utc_now().isoformat(),
                }
            },
            upsert=True,
        )
        target_slot = await self.slot_repo.collection.find_one(
            {"practitioner_id": pid, "date": date, "start_time": st},
            {"_id": 0},
        )
        if not target_slot:
            raise ValueError("Time slot not found")
        if target_slot.get("status") == "booked":
            raise ValueError("Time slot is no longer available")

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

    def _queue_booking_confirmation_notifications(
        self,
        booking_id: str,
        booking: Dict[str, Any],
        service: Dict[str, Any],
        customer: Dict[str, Any],
        practitioner: Dict[str, Any],
        practitioner_user: Dict[str, Any],
        pay_at_counter: bool,
    ) -> None:
        """Email + SMS customer; email practitioner; includes calendar URLs + .ics payload."""
        booking_view = {
            "booking_id": booking_id,
            "slot": booking["slot"],
            "service": service,
            "customer": customer,
            "practitioner": {**practitioner, "user": practitioner_user},
        }
        ics_b64 = ical_to_base64(build_booking_ical(booking_view))
        sk = booking["slot"]
        details_txt = f"Booking {booking_id[:8].upper()} — The Natural Path Spa"
        loc = "The Natural Path Spa"
        sn = service.get("name", "Appointment")
        g_url = google_calendar_template_url(
            sn, sk["date"], sk["start_time"], sk["end_time"], details=details_txt, location=loc
        )
        ms_url = microsoft_calendar_template_url(
            sn, sk["date"], sk["start_time"], sk["end_time"], body=details_txt, location=loc
        )
        mo_url = outlook_office_calendar_template_url(
            sn, sk["date"], sk["start_time"], sk["end_time"], body=details_txt, location=loc
        )
        slot = booking["slot"]
        pname = f"{practitioner_user['first_name']} {practitioner_user['last_name']}"
        try:
            send_booking_confirmation_email.delay(
                to_email=customer["email"],
                customer_name=f"{customer['first_name']} {customer['last_name']}",
                service_name=sn,
                practitioner_name=pname,
                date=slot["date"],
                time=slot["start_time"],
                booking_id=booking_id,
                pay_at_counter=pay_at_counter,
                google_calendar_url=g_url,
                outlook_live_url=ms_url,
                outlook_office_url=mo_url,
                ics_base64=ics_b64,
            )
            if practitioner_user.get("email"):
                send_practitioner_booking_notice_email.delay(
                    to_email=practitioner_user["email"],
                    practitioner_first_name=practitioner_user.get("first_name") or "there",
                    customer_name=f"{customer['first_name']} {customer['last_name']}",
                    service_name=sn,
                    date=slot["date"],
                    time=slot["start_time"],
                    booking_id=booking_id,
                    google_calendar_url=g_url,
                    outlook_live_url=ms_url,
                    outlook_office_url=mo_url,
                    ics_base64=ics_b64,
                )
            if customer.get("phone"):
                send_booking_confirmation_sms.delay(
                    to_phone=customer["phone"],
                    customer_name=customer["first_name"],
                    service_name=sn,
                    date=slot["date"],
                    time=slot["start_time"],
                )
        except Exception as e:
            logger.warning(f"Failed to queue notifications: {e}")
    
    async def confirm_booking(
        self,
        booking_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Confirm booking. Payment is always at the front desk (OTC); no online card or Revel charge here.
        """
        booking = await self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise ValueError("Booking not found")
        
        if booking["customer_id"] != user_id:
            raise ValueError("Unauthorized")
        
        if booking["status"] != "pending":
            raise ValueError(
                "Lock the slot before confirming — booking must be pending (use POST /booking/lock-slot first)"
            )
        
        service = await self.service_repo.get_by_id(booking["service_id"])
        customer = await self.user_repo.get_by_id(user_id)
        practitioner = await self.practitioner_repo.get_by_id(booking["practitioner_id"])
        practitioner_user = await self.user_repo.get_by_id(practitioner["user_id"])

        now = utc_now().isoformat()
        await self.booking_repo.update(
            booking_id,
            {
                "status": "confirmed",
                "confirmed_at": now,
                "payment_mode": "walk_in",
                "payment_status": "awaiting_counter",
            },
        )
        if self._is_discovery_service(service):
            await self.user_repo.update(user_id, {"is_discovery_completed": True})

        slot = booking["slot"]
        slots = await self.slot_repo.collection.find(
            {
                "practitioner_id": booking["practitioner_id"],
                "date": slot["date"],
                "start_time": slot["start_time"],
            },
            {"_id": 0},
        ).to_list(length=1)
        if slots:
            await self.slot_repo.update(
                slots[0]["slot_id"],
                {"status": "booked", "booking_id": booking_id},
            )

        confirm_event = BookingConfirmedEvent(
            booking_id=booking_id,
            customer_id=user_id,
            practitioner_id=booking["practitioner_id"],
            revel_order_id=None,
        )
        await self.event_repo.store_event(confirm_event.model_dump())

        updated = await self.booking_repo.get_by_id(booking_id)
        self._queue_booking_confirmation_notifications(
            booking_id, updated, service, customer, practitioner, practitioner_user, pay_at_counter=True
        )
        if settings.revel_enable_hosted_payments:
            # Durable marker so a reconciliation job can re-enqueue lost tasks.
            try:
                await self.booking_repo.update(
                    booking_id,
                    {
                        "payment_link_pending": True,
                        "payment_link_queued_at": utc_now().isoformat(),
                    },
                )
            except Exception as exc:
                logger.warning("Failed to mark invoice pending on %s: %s", booking_id, exc)
            try:
                issue_booking_invoice.delay(booking_id)
            except Exception as exc:
                logger.warning("Failed to queue booking invoice for %s: %s", booking_id, exc)
        logger.info("Booking confirmed (pay at counter): %s", booking_id)
        return {**updated, "payment": None, "revel_order": None}

    async def get_discovery_eligibility(self, customer_id: str) -> Dict[str, Any]:
        """
        Determine whether a user can book non-discovery services.
        Source of truth: booking history. Cache: user profile flag.
        """
        user = await self.user_repo.get_by_id(customer_id)
        has_flag = bool((user or {}).get("is_discovery_completed", False))

        bookings = await self.booking_repo.get_by_customer(customer_id)
        has_discovery_booking = False
        discovery_booking_id = None

        for booking in bookings:
            status = booking.get("status")
            if status not in {"confirmed", "completed", "in_progress"}:
                continue
            service = await self.service_repo.get_by_id(booking.get("service_id"))
            if self._is_discovery_service(service):
                has_discovery_booking = True
                discovery_booking_id = booking.get("booking_id")
                break

        # Keep cached flag in sync with booking-derived truth
        if has_discovery_booking and not has_flag:
            await self.user_repo.update(customer_id, {"is_discovery_completed": True})
            has_flag = True

        return {
            "is_discovery_completed": has_discovery_booking or has_flag,
            "has_discovery_booking": has_discovery_booking,
            "has_discovery_flag": has_flag,
            "discovery_booking_id": discovery_booking_id,
        }

    async def reschedule_booking(
        self,
        booking_id: str,
        user_id: str,
        new_date: str,
        new_start_time: str,
        new_end_time: str,
        *,
        as_practitioner: bool = False,
    ) -> Dict[str, Any]:
        """Move booking to a new slot (OTC only — no Revel)."""
        booking = await self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise ValueError("Booking not found")
        if as_practitioner:
            practitioner = await self.practitioner_repo.get_by_id(booking["practitioner_id"])
            if not practitioner or practitioner.get("user_id") != user_id:
                raise ValueError("Unauthorized")
            lock_user_id = user_id
        else:
            if booking["customer_id"] != user_id:
                raise ValueError("Unauthorized")
            lock_user_id = user_id
        if booking["status"] not in ("pending", "confirmed"):
            raise ValueError("Only pending or confirmed bookings can be rescheduled")

        old = booking["slot"]
        old_date = old["date"]
        old_start = old["start_time"]
        if old_date == new_date and old_start == new_start_time:
            return await self.booking_repo.get_by_id(booking_id)

        pid = booking["practitioner_id"]
        new_slot_id = generate_id()
        await self.slot_repo.collection.update_one(
            {"practitioner_id": pid, "date": new_date, "start_time": new_start_time},
            {
                "$setOnInsert": {
                    "slot_id": new_slot_id,
                    "practitioner_id": pid,
                    "date": new_date,
                    "start_time": new_start_time,
                    "end_time": new_end_time,
                    "status": "available",
                    "created_at": utc_now().isoformat(),
                }
            },
            upsert=True,
        )
        tgt = await self.slot_repo.collection.find_one(
            {"practitioner_id": pid, "date": new_date, "start_time": new_start_time},
            {"_id": 0},
        )
        if not tgt:
            raise ValueError("New slot not found")
        if tgt.get("status") == "booked" and tgt.get("booking_id") not in (None, booking_id):
            raise ValueError("New time slot is already booked")

        locked = await self.slot_repo.lock_slot(tgt["slot_id"], lock_user_id)
        if not locked:
            raise ValueError("New time slot is no longer available")

        old_docs = await self.slot_repo.collection.find(
            {
                "practitioner_id": pid,
                "date": old_date,
                "start_time": old_start,
            },
            {"_id": 0},
        ).to_list(length=1)
        if old_docs:
            await self.slot_repo.release_slot(old_docs[0]["slot_id"])

        if booking["status"] == "confirmed":
            await self.slot_repo.update(
                tgt["slot_id"],
                {
                    "status": "booked",
                    "booking_id": booking_id,
                    "locked_by": None,
                    "locked_until": None,
                },
            )

        await self.booking_repo.update(
            booking_id,
            {
                "slot": {
                    "date": new_date,
                    "start_time": new_start_time,
                    "end_time": new_end_time,
                },
                "updated_at": utc_now().isoformat(),
            },
        )

        ev = BookingRescheduledEvent(
            booking_id=booking_id,
            old_date=old_date,
            old_start_time=old_start,
            new_date=new_date,
            new_start_time=new_start_time,
        )
        await self.event_repo.store_event(ev.model_dump())

        if self.cache:
            await self.cache.delete(CacheService.availability_key(pid, old_date))
            await self.cache.delete(CacheService.availability_key(pid, new_date))

        logger.info("Booking rescheduled: %s -> %s %s", booking_id, new_date, new_start_time)
        return await self.booking_repo.get_by_id(booking_id)

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

    async def complete_booking_session(
        self,
        booking_id: str,
        practitioner_user_id: str,
    ) -> Dict[str, Any]:
        """Mark a booking completed for the practitioner who owns it."""
        booking = await self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise ValueError("Booking not found")
        practitioner = await self.practitioner_repo.get_by_id(booking["practitioner_id"])
        if not practitioner or practitioner["user_id"] != practitioner_user_id:
            raise ValueError("Unauthorized")
        st = booking.get("status")
        if st not in ("confirmed", "in_progress"):
            raise ValueError(f"Cannot complete booking in {st} status")
        slot = booking["slot"]
        now = utc_now().isoformat()
        await self.booking_repo.update(
            booking_id,
            {
                "status": "completed",
                "completed_at": now,
                "updated_at": now,
            },
        )
        if self.cache:
            await self.cache.delete(
                CacheService.availability_key(booking["practitioner_id"], slot["date"])
            )
        logger.info(f"Booking marked completed: {booking_id}")
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
