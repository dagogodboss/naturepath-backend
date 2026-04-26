"""
Booking API Routes - Complete Booking Flow
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response
from pymongo.errors import DuplicateKeyError

from core.calendar_utils import build_booking_ical
from core.config import settings
from core.money import Money
from core.money_fields import read_amount_cents_first
from pydantic import BaseModel, Field

from application.dto import (
    InitiateBookingRequest, LockSlotRequest, ConfirmBookingRequest,
    BookingResponse, CancelBookingRequest, RescheduleBookingRequest
)


class MarkPaidAtCounterRequest(BaseModel):
    # amount kept as float at the DTO boundary for backward compat; normalized
    # to Decimal (2dp) in the handler. Full migration to Decimal cents lands in F1/F2.
    amount: float = Field(gt=0)
    revel_receipt_id: str = Field(min_length=1, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=300)


def _two_dp(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
from application.use_cases import BookingUseCase
from infrastructure.database import get_database
from infrastructure.external import get_email_service, get_payment_link_provider
from infrastructure.payment_events import record_payment_event
from presentation.dependencies import (
    get_booking_use_case,
    get_current_active_user,
    get_current_admin,
    get_current_practitioner,
)
from core.rbac import Permission, has_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/booking", tags=["Booking"])


@router.post("/initiate", response_model=dict, status_code=status.HTTP_201_CREATED)
async def initiate_booking(
    request: InitiateBookingRequest,
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """
    Step 1: Initiate a booking (creates draft)
    
    This creates a booking in draft status. The time slot is not yet locked.
    """
    try:
        return await booking_use_case.initiate_booking(
            customer_id=current_user["user_id"],
            service_id=request.service_id,
            practitioner_id=request.practitioner_id,
            date=request.slot.date,
            start_time=request.slot.start_time,
            end_time=request.slot.end_time,
            notes=request.notes
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/service-slots", response_model=List[dict])
async def get_service_slots(
    service_id: str,
    date: str,
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case),
):
    """
    Available slot windows for a service on a date.
    Practitioner is chosen server-side during initiate.
    """
    return await booking_use_case.get_service_available_slots(service_id=service_id, date=date)


@router.post("/lock-slot", response_model=dict)
async def lock_booking_slot(
    booking_id: str,
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """
    Step 2: Lock the time slot for booking
    
    This locks the slot for 5 minutes to prevent race conditions during checkout.
    The booking status changes from 'draft' to 'pending'.
    """
    try:
        return await booking_use_case.lock_slot(
            booking_id=booking_id,
            user_id=current_user["user_id"]
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/confirm", response_model=dict)
async def confirm_booking(
    request: ConfirmBookingRequest,
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """
    Step 3: Confirm booking.

    Payment is **at the counter** (OTC); no online card or Revel charge in this flow.
    Sends confirmation email (with calendar links) and queues notifications.
    """
    try:
        return await booking_use_case.confirm_booking(
            booking_id=request.booking_id,
            user_id=current_user["user_id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


INVOICE_RESEND_COOLDOWN_SECONDS = 30


async def _assert_booking_invoice_authz(booking: dict, current_user: dict, db) -> None:
    """Allow: (a) the assigned practitioner or (b) a user with BOOKING_MANAGE."""
    if has_permission(current_user, Permission.BOOKING_MANAGE):
        return
    practitioner = await db.practitioners.find_one(
        {"user_id": current_user.get("user_id")},
        {"_id": 0, "practitioner_id": 1},
    )
    pid = (practitioner or {}).get("practitioner_id")
    if pid and booking.get("practitioner_id") == pid:
        return
    raise HTTPException(status_code=403, detail="Not allowed")


async def _release_invoice_claim(
    db, booking_id: str, *, restore_resend_at
) -> None:
    update: dict = {"$set": {"payment_link_issue_in_progress": False, "updated_at": datetime.now(timezone.utc)}}
    if restore_resend_at is None:
        update["$unset"] = {"last_invoice_resend_at": ""}
    else:
        update["$set"]["last_invoice_resend_at"] = restore_resend_at
    await db.bookings.update_one({"booking_id": booking_id}, update)


async def _release_claim_flag(db, booking_id: str, at: datetime) -> None:
    await db.bookings.update_one(
        {"booking_id": booking_id},
        {"$set": {"payment_link_issue_in_progress": False, "updated_at": at}},
    )


async def _cancel_stale_link(db, provider, booking_id: str, link_doc: dict, at: datetime) -> None:
    await db.payment_links.update_one(
        {"link_id": link_doc["link_id"]},
        {
            "$set": {"status": "pending_cancel", "updated_at": at},
            "$inc": {"cancel_attempts": 1},
        },
    )
    await db.bookings.update_one(
        {"booking_id": booking_id},
        {
            "$unset": {"payment_link_id": "", "payment_link_url": ""},
            "$set": {"updated_at": at},
        },
    )
    try:
        await provider.cancel_link(link_doc["link_id"])
        await db.payment_links.update_one(
            {"link_id": link_doc["link_id"]},
            {"$set": {"status": "cancelled", "updated_at": at}},
        )
    except Exception as exc:
        logger.warning(
            "Remote cancel failed for link %s (booking %s): %s",
            link_doc["link_id"], booking_id, exc,
        )
        await db.payment_links.update_one(
            {"link_id": link_doc["link_id"]},
            {"$set": {"last_cancel_error_at": at}},
        )


async def _enqueue_invoice_worker(db, booking_id: str, at: datetime, prior_resend_at) -> None:
    """Release the in-progress flag then enqueue the worker. Rolls back cooldown on broker failure."""
    await _release_claim_flag(db, booking_id, at)
    try:
        from workers.booking_invoice_worker import issue_booking_invoice
        issue_booking_invoice.delay(booking_id)
    except Exception as exc:
        logger.warning("Failed to queue invoice resend for %s: %s", booking_id, exc)
        await _release_invoice_claim(db, booking_id, restore_resend_at=prior_resend_at)
        raise HTTPException(
            status_code=503,
            detail="Could not queue invoice resend; try again shortly",
        ) from exc


async def _resend_existing_email(db, booking: dict, link_doc: dict, at: datetime) -> None:
    customer = await db.users.find_one(
        {"user_id": booking.get("customer_id")},
        {"_id": 0, "email": 1, "first_name": 1, "last_name": 1},
    ) or {}
    email = customer.get("email")
    if not email:
        raise HTTPException(status_code=409, detail="Customer has no email on file")
    service = await db.services.find_one(
        {"service_id": booking.get("service_id")},
        {"_id": 0, "name": 1},
    ) or {}
    slot = booking.get("slot") or {}
    customer_name = (
        f"{customer.get('first_name') or ''} {customer.get('last_name') or ''}".strip()
        or "there"
    )
    email_service = get_email_service()
    try:
        await email_service.send_booking_invoice(
            to_email=email,
            customer_name=customer_name,
            service_name=service.get("name") or "Appointment",
            date=slot.get("date") or "",
            time=slot.get("start_time") or "",
            booking_id=booking.get("booking_id"),
            amount=read_amount_cents_first(
                link_doc,
                cents_field="amount_cents",
                legacy_field="amount",
                default_currency=str(booking.get("currency") or "USD"),
            )
            or read_amount_cents_first(
                booking,
                cents_field="payment_amount_cents",
                legacy_field="payment_amount",
                default_currency=str(booking.get("currency") or "USD"),
            ),
            pay_link_url=link_doc["hosted_url"],
            expires_at=link_doc.get("expires_at"),
        )
    finally:
        await _release_claim_flag(db, booking.get("booking_id"), at)


@router.post("/{booking_id}/invoice/resend", response_model=dict)
async def resend_booking_invoice(
    booking_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """
    Reissue the booking invoice email.

    - Reuses an active, unexpired hosted pay link (just re-sends the email).
    - Otherwise cancels the stale link and queues a fresh one through the
      idempotent worker.
    - Throttled with a per-booking cooldown to prevent email spam.
    """
    if not settings.revel_enable_hosted_payments:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hosted payments are not enabled",
        )
    booking = await db.bookings.find_one({"booking_id": booking_id}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.get("status") not in {"confirmed", "in_progress"}:
        raise HTTPException(status_code=409, detail="Booking is not in an invoiceable state")
    await _assert_booking_invoice_authz(booking, current_user, db)

    now = datetime.now(timezone.utc)
    cooldown_cutoff = now - timedelta(seconds=INVOICE_RESEND_COOLDOWN_SECONDS)
    prior_resend_at = booking.get("last_invoice_resend_at")

    # Atomic CAS: only one resend can hold the in-progress flag, and the
    # cooldown is enforced at claim time. Both conditions are coupled in a
    # single conditional update so neither can leak.
    claim_before = await db.bookings.find_one_and_update(
        {
            "booking_id": booking_id,
            "status": {"$in": ["confirmed", "in_progress"]},
            "payment_link_issue_in_progress": {"$ne": True},
            "$or": [
                {"last_invoice_resend_at": {"$exists": False}},
                {"last_invoice_resend_at": {"$lt": cooldown_cutoff}},
            ],
        },
        {
            "$set": {
                "payment_link_issue_in_progress": True,
                "last_invoice_resend_at": now,
                "updated_at": now,
            }
        },
        return_document=False,
        projection={"_id": 0, "payment_link_issue_in_progress": 1, "last_invoice_resend_at": 1},
    )
    if not claim_before:
        latest = await db.bookings.find_one(
            {"booking_id": booking_id},
            {"_id": 0, "payment_link_issue_in_progress": 1, "last_invoice_resend_at": 1},
        ) or {}
        if latest.get("payment_link_issue_in_progress"):
            raise HTTPException(status_code=409, detail="Another invoice operation is in progress")
        raise HTTPException(
            status_code=429,
            detail=f"Please wait at least {INVOICE_RESEND_COOLDOWN_SECONDS}s between resends",
        )

    try:
        link_id = booking.get("payment_link_id")
        link_doc = (
            await db.payment_links.find_one({"link_id": link_id}, {"_id": 0})
            if link_id
            else None
        )

        needs_new_link = True
        if link_doc and link_doc.get("status") == "active":
            exp = _parse_iso(link_doc.get("expires_at"))
            if not exp or exp > now:
                needs_new_link = False

        provider = get_payment_link_provider()
        if needs_new_link and link_doc:
            await _cancel_stale_link(db, provider, booking_id, link_doc, now)
            await _enqueue_invoice_worker(db, booking_id, now, prior_resend_at)
            return {"booking_id": booking_id, "status": "queued", "reused_link": False}

        if not link_doc:
            await _enqueue_invoice_worker(db, booking_id, now, prior_resend_at)
            return {"booking_id": booking_id, "status": "queued", "reused_link": False}

        await _resend_existing_email(db, booking, link_doc, now)
        return {
            "booking_id": booking_id,
            "status": "resent",
            "reused_link": True,
            "link_id": link_doc["link_id"],
        }
    except HTTPException:
        raise
    except Exception:
        await _release_claim_flag(db, booking_id, now)
        raise


def _validate_counter_amount(booking: dict, submitted_amount: float) -> Decimal:
    expected = _two_dp(
        read_amount_cents_first(
            booking,
            cents_field="payment_amount_cents",
            legacy_field="payment_amount",
            default_currency=str(booking.get("currency") or "USD"),
        )
        or read_amount_cents_first(
            booking,
            cents_field="total_price_cents",
            legacy_field="total_price",
            default_currency=str(booking.get("currency") or "USD"),
        )
    )
    if expected <= Decimal("0"):
        raise HTTPException(
            status_code=409,
            detail="Booking has no server-side price to validate against",
        )
    submitted = _two_dp(submitted_amount)
    if abs(submitted - expected) > Decimal("0.01"):
        raise HTTPException(
            status_code=400,
            detail=f"Amount does not match expected {expected}",
        )
    return expected


async def _assert_receipt_unique(db, booking_id: str, revel_receipt_id: str) -> None:
    conflict = await db.bookings.find_one(
        {
            "receipt_id": revel_receipt_id,
            "payment_status": "captured",
            "booking_id": {"$ne": booking_id},
        },
        {"_id": 0, "booking_id": 1},
    )
    if conflict:
        raise HTTPException(
            status_code=409,
            detail="This Revel receipt id has already been used for another booking",
        )


async def _capture_booking_at_counter(
    db, booking_id: str, body: "MarkPaidAtCounterRequest", user_id: str, amount: float, now: datetime
) -> bool:
    money = Money.from_float(amount, "USD")
    try:
        claim = await db.bookings.update_one(
            {
                "booking_id": booking_id,
                "payment_status": {"$in": ["none", "awaiting_counter", "awaiting_payment", None]},
            },
            {
                "$set": {
                    "payment_status": "captured",
                    "payment_mode": "walk_in",
                    "payment_amount": money.to_float(),
                    "payment_amount_cents": money.to_cents(),
                    "currency": "USD",
                    "receipt_id": body.revel_receipt_id,
                    "paid_at": now,
                    "counter_payment_by": user_id,
                    "counter_payment_notes": body.notes,
                    "updated_at": now,
                },
                "$push": {
                    "payment_events": {
                        "action": "manual_paid",
                        "amount": amount,
                        "receipt_id": body.revel_receipt_id,
                        "by_user_id": user_id,
                        "at": now,
                    }
                },
            },
        )
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=409,
            detail="This Revel receipt id has already been used for another booking",
        ) from exc
    return bool(claim.matched_count)


async def _cancel_link_after_capture(db, booking_id: str, link_id: str, now: datetime) -> None:
    try:
        provider = get_payment_link_provider()
        await provider.cancel_link(link_id)
        await db.payment_links.update_one(
            {"link_id": link_id},
            {"$set": {"status": "cancelled", "updated_at": now}},
        )
        await db.bookings.update_one(
            {"booking_id": booking_id},
            {"$unset": {"payment_link_id": "", "payment_link_url": ""}},
        )
    except Exception as exc:
        logger.warning(
            "Failed to cancel hosted pay link after counter capture for %s: %s",
            booking_id, exc,
        )
        await db.payment_links.update_one(
            {"link_id": link_id},
            {
                "$set": {"status": "pending_cancel", "last_cancel_error_at": now},
                "$inc": {"cancel_attempts": 1},
            },
        )


@router.get("/{booking_id}/payment/status", response_model=dict)
async def get_booking_payment_status(
    booking_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """H1: reconciled payment-status view for a booking."""
    booking = await db.bookings.find_one({"booking_id": booking_id}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    is_owner = booking.get("customer_id") == current_user.get("user_id")
    is_ops = has_permission(current_user, Permission.BOOKING_MANAGE)
    if not (is_owner or is_ops):
        # Allow assigned practitioner too.
        p = await db.practitioners.find_one(
            {"user_id": current_user.get("user_id")}, {"_id": 0, "practitioner_id": 1}
        )
        if not p or booking.get("practitioner_id") != p.get("practitioner_id"):
            raise HTTPException(status_code=403, detail="Not allowed")

    # Deliberately a pure read view: webhook / reconciliation job own
    # transitions. The SDK interceptor polls this endpoint and stops as
    # soon as payment_status leaves the pending set.
    return {
        "booking_id": booking["booking_id"],
        "payment_status": booking.get("payment_status"),
        "payment_mode": booking.get("payment_mode"),
        "payment_amount": read_amount_cents_first(
            booking,
            cents_field="payment_amount_cents",
            legacy_field="payment_amount",
            default_currency=str(booking.get("currency") or "USD"),
        ),
        "payment_link_url": booking.get("payment_link_url"),
        "revel_transaction_id": booking.get("revel_transaction_id"),
        "receipt_id": booking.get("receipt_id"),
        "paid_at": booking.get("paid_at"),
    }


@router.post("/{booking_id}/mark-paid-at-counter", response_model=dict)
async def mark_booking_paid_at_counter(
    booking_id: str,
    body: MarkPaidAtCounterRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """
    Practitioner/ops stamp a walk-in payment for a booking.
    Receipt email is sent asynchronously so POS UX stays snappy.
    """
    booking = await db.bookings.find_one({"booking_id": booking_id}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.get("status") not in {"confirmed", "in_progress", "completed"}:
        raise HTTPException(status_code=409, detail="Booking is not in a payable state")
    await _assert_booking_invoice_authz(booking, current_user, db)
    if booking.get("payment_status") == "captured":
        return booking

    expected = _validate_counter_amount(booking, body.amount)
    await _assert_receipt_unique(db, booking_id, body.revel_receipt_id)

    now = datetime.now(timezone.utc)
    amount = float(expected)
    if not await _capture_booking_at_counter(
        db, booking_id, body, current_user.get("user_id"), amount, now
    ):
        latest = await db.bookings.find_one(
            {"booking_id": booking_id}, {"_id": 0, "payment_status": 1}
        ) or {}
        if latest.get("payment_status") == "captured":
            return await db.bookings.find_one({"booking_id": booking_id}, {"_id": 0})
        raise HTTPException(
            status_code=409,
            detail="Booking payment state not eligible for counter capture",
        )

    link_id = booking.get("payment_link_id")
    if link_id:
        await _cancel_link_after_capture(db, booking_id, link_id, now)

    await record_payment_event(
        db,
        ref_type="booking",
        ref_id=booking_id,
        action="manual_paid",
        amount=amount,
        source="manual_at_counter",
        external_id=body.revel_receipt_id,
        metadata={"by_user_id": current_user.get("user_id"), "notes": body.notes},
    )
    from .webhook_routes import _send_booking_receipt_if_new
    background_tasks.add_task(
        _send_booking_receipt_if_new, db, booking_id, "counter_capture"
    )
    return await db.bookings.find_one({"booking_id": booking_id}, {"_id": 0})


@router.post("/{booking_id}/reschedule", response_model=dict)
async def reschedule_booking(
    booking_id: str,
    request: RescheduleBookingRequest,
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case),
):
    """Reschedule to a new slot (OTC; no payment provider)."""
    if request.booking_id != booking_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="booking_id in body must match URL",
        )
    try:
        return await booking_use_case.reschedule_booking(
            booking_id=booking_id,
            user_id=current_user["user_id"],
            new_date=request.new_slot.date,
            new_start_time=request.new_slot.start_time,
            new_end_time=request.new_slot.end_time,
            as_practitioner=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{booking_id}/ical")
async def download_booking_ical(
    booking_id: str,
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case),
):
    """
    Download an iCalendar (.ics) file for a booking (add to Apple/Google/Outlook calendar).
    """
    try:
        is_admin = has_permission(current_user, Permission.BOOKING_READ_ALL)
        booking = await booking_use_case.get_booking_by_id(
            booking_id=booking_id,
            user_id=current_user["user_id"],
            is_admin=is_admin,
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    body = build_booking_ical(booking)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="booking-{booking_id}.ics"'
        },
    )


@router.get("/{booking_id}", response_model=dict)
async def get_booking(
    booking_id: str,
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """Get a specific booking by ID"""
    try:
        is_admin = has_permission(current_user, Permission.BOOKING_READ_ALL)
        return await booking_use_case.get_booking_by_id(
            booking_id=booking_id,
            user_id=current_user["user_id"],
            is_admin=is_admin
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/cancel", response_model=dict)
async def cancel_booking(
    request: CancelBookingRequest,
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """Cancel a booking"""
    try:
        is_admin = has_permission(current_user, Permission.BOOKING_MANAGE)
        return await booking_use_case.cancel_booking(
            booking_id=request.booking_id,
            user_id=current_user["user_id"],
            reason=request.reason,
            is_admin=is_admin
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/practitioner/calendar", response_model=List[dict])
async def get_practitioner_calendar(
    start_date: str,
    end_date: str,
    ctx: dict = Depends(get_current_practitioner),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case),
):
    """List bookings for the authenticated practitioner (or admin with practitioner profile)."""
    practitioner = ctx.get("practitioner")
    if not practitioner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practitioner profile required",
        )
    pid = practitioner["practitioner_id"]
    return await booking_use_case.get_practitioner_bookings(
        practitioner_id=pid,
        start_date=start_date,
        end_date=end_date,
    )


@router.post("/practitioner/{booking_id}/complete", response_model=dict)
async def complete_practitioner_session(
    booking_id: str,
    ctx: dict = Depends(get_current_practitioner),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case),
):
    """Mark a booking completed (assigned practitioner or admin with profile)."""
    user = ctx["user"]
    if not has_permission(user, Permission.BOOKING_COMPLETE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: booking:complete",
        )
    try:
        return await booking_use_case.complete_booking_session(
            booking_id=booking_id,
            practitioner_user_id=user["user_id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/practitioner/{booking_id}/reschedule", response_model=dict)
async def reschedule_booking_as_practitioner(
    booking_id: str,
    request: RescheduleBookingRequest,
    ctx: dict = Depends(get_current_practitioner),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case),
):
    """Reschedule a client's booking (assigned practitioner)."""
    if request.booking_id != booking_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="booking_id in body must match URL",
        )
    user = ctx["user"]
    try:
        return await booking_use_case.reschedule_booking(
            booking_id=booking_id,
            user_id=user["user_id"],
            new_date=request.new_slot.date,
            new_start_time=request.new_slot.start_time,
            new_end_time=request.new_slot.end_time,
            as_practitioner=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Admin routes
@router.get("/admin/all", response_model=List[dict])
async def get_all_bookings(
    status: str = None,
    current_admin: dict = Depends(get_current_admin),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """Get all bookings (Admin only)"""
    if status:
        return await booking_use_case.booking_repo.get_by_status(status)
    return await booking_use_case.booking_repo.list_all()


@router.get("/admin/by-date", response_model=List[dict])
async def get_bookings_by_date_range(
    start_date: str,
    end_date: str,
    practitioner_id: str = None,
    current_admin: dict = Depends(get_current_admin),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """Get bookings by date range (Admin only)"""
    return await booking_use_case.booking_repo.get_by_date_range(
        start_date=start_date,
        end_date=end_date,
        practitioner_id=practitioner_id
    )


@router.post("/admin/cancel/{booking_id}", response_model=dict)
async def admin_cancel_booking(
    booking_id: str,
    reason: str = None,
    current_admin: dict = Depends(get_current_admin),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """Cancel any booking (Admin only)"""
    try:
        return await booking_use_case.cancel_booking(
            booking_id=booking_id,
            user_id=current_admin["user_id"],
            reason=reason,
            is_admin=True
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
