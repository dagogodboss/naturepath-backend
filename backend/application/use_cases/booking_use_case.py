"""
Booking Use Cases - Application Layer
Handles the complete booking flow (OTC payment at counter; Revel is store/e-commerce only).
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from dateutil.relativedelta import relativedelta
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
    booking_calendar_links,
    ical_to_base64,
)
from application.service_policy import service_requires_discovery
from application.outlook_calendar import subtract_busy_intervals
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

        windows = sorted(merged.values(), key=lambda w: w["start_time"])
        collection = getattr(self.booking_repo, "collection", None)
        db = getattr(collection, "database", None)
        outlook_collection = getattr(db, "outlook_calendar_events", None)
        if outlook_collection is not None:
            outlook_events = await outlook_collection.find(
                {
                    "practitioner_id": practitioner_id,
                    "date": date,
                    "is_cancelled": {"$ne": True},
                    "show_as": {"$ne": "free"},
                },
                {"_id": 0, "start_time": 1, "end_time": 1, "show_as": 1, "is_cancelled": 1},
            ).to_list(length=500)
            windows = subtract_busy_intervals(windows, outlook_events)
        return windows

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
        notes: Optional[str] = None,
        enable_monthly_recurrence: bool = False,
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
        discovery_unlocked = False
        if service_requires_discovery(service):
            eligibility = await self.get_discovery_eligibility(customer_id)
            if eligibility.get("state") != "completed":
                raise ValueError(
                    "Discovery call required before booking this service"
                )
            discovery_unlocked = True
        
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
        
        # After discovery unlock: monthly recurrence only with explicit opt-in.
        # Children are materialized on confirm (see _materialize_monthly_series).
        recurrence = (
            {"frequency": "monthly", "active": True}
            if discovery_unlocked and enable_monthly_recurrence
            else None
        )

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
            notes=notes,
            recurrence=recurrence,
            reminders_sent={},
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
        loc = "100 Sabal Palms Row, Suite 2, Youngsville, LA 70592"
        sn = service.get("name", "Appointment")
        links = booking_calendar_links(
            sn, sk["date"], sk["start_time"], sk["end_time"], details=details_txt, location=loc
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
                google_calendar_url=links["google"],
                yahoo_calendar_url=links["yahoo"],
                outlook_live_url=links["outlook_live"],
                outlook_office_url=links["outlook_office"],
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
                    google_calendar_url=links["google"],
                    yahoo_calendar_url=links["yahoo"],
                    outlook_live_url=links["outlook_live"],
                    outlook_office_url=links["outlook_office"],
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
        # Discovery unlock is staff-only via mark_discovery_completed — never auto on confirm.

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

        # Materialize monthly series children after the parent is confirmed.
        series_meta = None
        recurrence = updated.get("recurrence") or {}
        if recurrence.get("active") and recurrence.get("frequency") == "monthly":
            try:
                series_meta = await self._materialize_monthly_series(
                    parent=updated,
                    service=service,
                    customer=customer,
                    months=3,
                )
                updated = await self.booking_repo.get_by_id(booking_id)
            except Exception as exc:
                logger.exception(
                    "Series materialization failed for %s: %s", booking_id, exc
                )

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
        result = {**updated, "payment": None, "revel_order": None}
        if series_meta:
            result["series"] = series_meta
        return result

    async def _materialize_monthly_series(
        self,
        parent: Dict[str, Any],
        service: Dict[str, Any],
        customer: Optional[Dict[str, Any]],
        months: int = 3,
    ) -> Dict[str, Any]:
        """
        Create the next `months` monthly child bookings for a confirmed parent.

        Conflict policy (documented choice):
          - Prefer the same weekday/time on the monthly anniversary date.
          - If that exact slot is unavailable for the assigned practitioner,
            skip that month (do not soft-book a conflicting slot).
          - Collect skipped months and email the customer a short note so they
            can reschedule those months manually.
        """
        parent_id = parent["booking_id"]
        series_id = parent.get("series_id") or parent_id
        slot = parent.get("slot") or {}
        base_date_s = slot.get("date")
        start_time = slot.get("start_time")
        end_time = slot.get("end_time")
        if not (base_date_s and start_time and end_time):
            return {"series_id": series_id, "created": [], "skipped": []}

        try:
            base_date = datetime.strptime(base_date_s, "%Y-%m-%d").date()
        except ValueError:
            return {"series_id": series_id, "created": [], "skipped": []}

        # Promote parent to series root.
        recurrence = dict(parent.get("recurrence") or {})
        recurrence["active"] = True
        recurrence["frequency"] = "monthly"
        recurrence["horizon_months"] = months
        await self.booking_repo.update(
            parent_id,
            {
                "series_id": series_id,
                "series_parent_id": None,
                "series_index": 0,
                "recurrence": recurrence,
            },
        )

        practitioner = await self.practitioner_repo.get_by_id(parent["practitioner_id"])
        created: List[str] = []
        skipped: List[Dict[str, str]] = []
        price = parent.get("total_price")
        price_cents = parent.get("total_price_cents")
        currency = parent.get("currency") or "USD"

        for i in range(1, months + 1):
            target = base_date + relativedelta(months=i)
            target_s = target.isoformat()
            available = False
            if practitioner:
                windows = await self._candidate_slots_for_practitioner(
                    practitioner, target_s
                )
                available = any(
                    w["start_time"] == start_time and w["end_time"] == end_time
                    for w in windows
                )
            if not available:
                skipped.append(
                    {
                        "date": target_s,
                        "start_time": start_time,
                        "reason": "slot_unavailable",
                    }
                )
                continue

            child_id = generate_id()
            now = utc_now().isoformat()
            child = {
                "booking_id": child_id,
                "customer_id": parent["customer_id"],
                "practitioner_id": parent["practitioner_id"],
                "service_id": parent["service_id"],
                "slot": {
                    "date": target_s,
                    "start_time": start_time,
                    "end_time": end_time,
                },
                "status": "confirmed",
                "total_price": price,
                "total_price_cents": price_cents,
                "currency": currency,
                "payment_mode": "walk_in",
                "payment_status": "awaiting_counter",
                "notes": parent.get("notes"),
                "series_id": series_id,
                "series_parent_id": parent_id,
                "series_index": i,
                "recurrence": {
                    "frequency": "monthly",
                    "active": True,
                    "series_id": series_id,
                },
                "reminders_sent": {},
                "confirmed_at": now,
                "created_at": now,
                "updated_at": now,
            }
            await self.booking_repo.create(child)

            # Reserve slot row when possible (best-effort).
            try:
                new_slot_id = generate_id()
                await self.slot_repo.collection.update_one(
                    {
                        "practitioner_id": parent["practitioner_id"],
                        "date": target_s,
                        "start_time": start_time,
                        "end_time": end_time,
                        "status": {"$in": ["available", "locked"]},
                    },
                    {
                        "$set": {
                            "status": "booked",
                            "booking_id": child_id,
                            "updated_at": now,
                        },
                        "$setOnInsert": {
                            "slot_id": new_slot_id,
                            "practitioner_id": parent["practitioner_id"],
                            "date": target_s,
                            "start_time": start_time,
                            "end_time": end_time,
                            "created_at": now,
                        },
                    },
                    upsert=True,
                )
            except Exception as exc:
                logger.warning(
                    "Could not lock series slot %s %s: %s", target_s, start_time, exc
                )
            created.append(child_id)

        if skipped and customer and customer.get("email"):
            await self._notify_series_skips(
                customer=customer,
                service=service,
                parent_id=parent_id,
                skipped=skipped,
            )

        logger.info(
            "Series %s: created %d children, skipped %d",
            series_id,
            len(created),
            len(skipped),
        )
        return {
            "series_id": series_id,
            "created": created,
            "skipped": skipped,
        }

    async def _notify_series_skips(
        self,
        customer: Dict[str, Any],
        service: Dict[str, Any],
        parent_id: str,
        skipped: List[Dict[str, str]],
    ) -> None:
        """Queue email about months that could not be reserved (non-blocking)."""
        try:
            from workers.notification_worker import send_generic_email

            service_name = (service or {}).get("name") or "your service"
            rows = "".join(
                f"<li>{s['date']} at {s['start_time']}</li>" for s in skipped
            )
            html = (
                f"<p>Hi {customer.get('first_name') or 'there'},</p>"
                f"<p>We reserved your monthly {service_name} series, but these "
                f"months were unavailable at your usual time and were skipped:</p>"
                f"<ul>{rows}</ul>"
                f"<p>Please open the app to pick alternate times for those months. "
                f"(Booking {parent_id})</p>"
            )
            text = (
                f"Some months in your {service_name} series were skipped due to "
                f"unavailable slots: "
                + ", ".join(f"{s['date']} {s['start_time']}" for s in skipped)
            )
            send_generic_email.delay(
                to_email=customer["email"],
                subject=f"Monthly series — {len(skipped)} month(s) need a new time",
                html_content=html,
                text_content=text,
            )
        except Exception as exc:
            logger.warning("Failed to queue series skip note: %s", exc)

    @staticmethod
    def _parse_slot_start(slot: Optional[Dict[str, Any]]) -> Optional[datetime]:
        """Interpret booking slot date+time in the clinic timezone."""
        if not slot:
            return None
        date_s = slot.get("date")
        time_s = (slot.get("start_time") or "00:00")[:5]
        if not date_s:
            return None
        from core.time_utils import parse_clinic_slot

        return parse_clinic_slot(date_s, time_s)

    async def get_discovery_eligibility(self, customer_id: str) -> Dict[str, Any]:
        """
        Four-state discovery gate for non-discovery booking unlock.

        States:
          none — no active discovery booking
          scheduled — discovery confirmed/pending with future slot
          pending_completion — slot passed or session ended, staff not yet marked done
          completed — is_discovery_completed set by staff only
        """
        user = await self.user_repo.get_by_id(customer_id)
        has_flag = bool((user or {}).get("is_discovery_completed", False))

        if has_flag:
            return {
                "state": "completed",
                "is_discovery_completed": True,
                "has_discovery_booking": True,
                "has_discovery_flag": True,
                "discovery_booking_id": (user or {}).get("discovery_completed_booking_id"),
                "discovery_slot": None,
                "messaging_key": "unlocked",
            }

        bookings = await self.booking_repo.get_by_customer(customer_id)
        discovery_candidates: List[Dict[str, Any]] = []
        for booking in bookings:
            status = booking.get("status")
            if status in {"draft", "cancelled"}:
                continue
            service = await self.service_repo.get_by_id(booking.get("service_id"))
            if self._is_discovery_service(service):
                discovery_candidates.append(booking)

        if not discovery_candidates:
            return {
                "state": "none",
                "is_discovery_completed": False,
                "has_discovery_booking": False,
                "has_discovery_flag": False,
                "discovery_booking_id": None,
                "discovery_slot": None,
                "messaging_key": "please_book",
            }

        # Prefer the most relevant: future scheduled first, else most recent past/active.
        from core.time_utils import clinic_now

        now = clinic_now()
        scheduled: List[Dict[str, Any]] = []
        pending: List[Dict[str, Any]] = []
        for booking in discovery_candidates:
            status = booking.get("status")
            slot = booking.get("slot") or {}
            start = self._parse_slot_start(slot)
            slot_payload = {
                "date": slot.get("date"),
                "start_time": slot.get("start_time"),
            }
            if status in {"completed", "in_progress", "no_show"}:
                pending.append({**booking, "_slot_payload": slot_payload, "_start": start})
                continue
            if status in {"confirmed", "pending"}:
                if start is not None and start > now:
                    scheduled.append({**booking, "_slot_payload": slot_payload, "_start": start})
                else:
                    pending.append({**booking, "_slot_payload": slot_payload, "_start": start})

        if scheduled:
            scheduled.sort(key=lambda b: b.get("_start") or now)
            chosen = scheduled[0]
            return {
                "state": "scheduled",
                "is_discovery_completed": False,
                "has_discovery_booking": True,
                "has_discovery_flag": False,
                "discovery_booking_id": chosen.get("booking_id"),
                "discovery_slot": chosen.get("_slot_payload"),
                "messaging_key": "scheduled",
            }

        if pending:
            pending.sort(key=lambda b: b.get("_start") or now, reverse=True)
            chosen = pending[0]
            return {
                "state": "pending_completion",
                "is_discovery_completed": False,
                "has_discovery_booking": True,
                "has_discovery_flag": False,
                "discovery_booking_id": chosen.get("booking_id"),
                "discovery_slot": chosen.get("_slot_payload"),
                "messaging_key": "pending",
            }

        return {
            "state": "none",
            "is_discovery_completed": False,
            "has_discovery_booking": False,
            "has_discovery_flag": False,
            "discovery_booking_id": None,
            "discovery_slot": None,
            "messaging_key": "please_book",
        }

    async def mark_discovery_completed(
        self,
        booking_id: str,
        staff_user_id: str,
        *,
        as_admin: bool = False,
    ) -> Dict[str, Any]:
        """Staff marks Discovery Call done — unlocks non-discovery bookings for the customer."""
        booking = await self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise ValueError("Booking not found")
        service = await self.service_repo.get_by_id(booking.get("service_id"))
        if not self._is_discovery_service(service):
            raise ValueError("Booking is not a Discovery Call")
        if booking.get("status") in {"draft", "cancelled"}:
            raise ValueError("Cannot complete discovery for this booking status")

        if not as_admin:
            practitioner = await self.practitioner_repo.get_by_id(booking["practitioner_id"])
            if not practitioner or practitioner.get("user_id") != staff_user_id:
                raise ValueError("Unauthorized")

        customer_id = booking["customer_id"]
        now = utc_now().isoformat()
        await self.user_repo.update(
            customer_id,
            {
                "is_discovery_completed": True,
                "discovery_completed_at": now,
                "discovery_completed_by": staff_user_id,
                "discovery_completed_booking_id": booking_id,
            },
        )
        # Ensure session is marked completed if still open.
        if booking.get("status") in {"confirmed", "pending", "in_progress"}:
            await self.booking_repo.update(
                booking_id,
                {"status": "completed", "completed_at": now, "updated_at": now},
            )
        logger.info(
            "Discovery completed for customer %s via booking %s by %s",
            customer_id,
            booking_id,
            staff_user_id,
        )
        return await self.get_discovery_eligibility(customer_id)

    async def stop_recurring(
        self,
        booking_id: str,
        user_id: str,
        *,
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """
        Stop monthly recurrence: deactivate flag on the series and cancel
        *future* series members only (past/today stay intact).
        """
        booking = await self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise ValueError("Booking not found")
        if not is_admin and booking["customer_id"] != user_id:
            raise ValueError("Unauthorized")

        series_id = booking.get("series_id") or booking_id
        recurrence = dict(booking.get("recurrence") or {})
        now = utc_now()
        today = now.date().isoformat()
        stopped_at = now.isoformat()

        # Deactivate recurrence on the touched booking and series root.
        recurrence["active"] = False
        recurrence["stopped_at"] = stopped_at
        await self.booking_repo.update(booking_id, {"recurrence": recurrence})

        # Find all series members (parent + children).
        members = await self.booking_repo.collection.find(
            {
                "$or": [
                    {"series_id": series_id},
                    {"booking_id": series_id},
                    {"series_parent_id": series_id},
                ]
            },
            {"_id": 0},
        ).to_list(length=100)

        cancelled_ids: List[str] = []
        for member in members:
            mid = member["booking_id"]
            # Always clear active flag on every series member.
            m_rec = dict(member.get("recurrence") or {})
            m_rec["active"] = False
            m_rec["stopped_at"] = stopped_at
            await self.booking_repo.update(mid, {"recurrence": m_rec})

            slot_date = (member.get("slot") or {}).get("date") or ""
            status = member.get("status")
            if slot_date > today and status in {"confirmed", "pending", "draft"}:
                await self.booking_repo.update(
                    mid,
                    {
                        "status": "cancelled",
                        "cancellation_reason": "Recurring series stopped",
                        "updated_at": stopped_at,
                    },
                )
                cancelled_ids.append(mid)
                # Free reserved slots best-effort.
                try:
                    mslot = member.get("slot") or {}
                    await self.slot_repo.collection.update_many(
                        {
                            "booking_id": mid,
                            "status": "booked",
                        },
                        {
                            "$set": {
                                "status": "available",
                                "booking_id": None,
                                "updated_at": stopped_at,
                            }
                        },
                    )
                except Exception:
                    pass

        logger.info(
            "Recurrence stopped for series %s by %s; cancelled future=%s",
            series_id,
            user_id,
            cancelled_ids,
        )
        result = await self.get_booking_by_id(
            booking_id=booking_id, user_id=user_id, is_admin=is_admin
        )
        result["series_cancelled_future"] = cancelled_ids
        return result

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

    async def list_series_bookings(
        self,
        series_id: str,
        user_id: str,
        *,
        is_admin: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return all bookings in a series (for .ics multi-instance export)."""
        rows = await self.booking_repo.collection.find(
            {"series_id": series_id},
            {"_id": 0},
        ).to_list(length=50)
        if not rows:
            return []
        # Authz: any member must belong to user (or admin).
        sample = rows[0]
        if not is_admin and sample.get("customer_id") != user_id:
            practitioner = await self.practitioner_repo.get_by_id(
                sample.get("practitioner_id")
            )
            if not practitioner or practitioner.get("user_id") != user_id:
                raise ValueError("Unauthorized")
        service = await self.service_repo.get_by_id(sample.get("service_id"))
        customer = await self.user_repo.get_by_id(sample.get("customer_id"))
        if customer:
            customer = {**customer}
            customer.pop("password_hash", None)
        practitioner = await self.practitioner_repo.get_by_id(sample.get("practitioner_id"))
        enriched = []
        for row in sorted(
            rows, key=lambda r: ((r.get("slot") or {}).get("date") or "", r.get("series_index") or 0)
        ):
            enriched.append(
                {
                    **row,
                    "service": service,
                    "customer": customer,
                    "practitioner": practitioner,
                }
            )
        return enriched
