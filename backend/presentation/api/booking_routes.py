"""
Booking API Routes - Complete Booking Flow
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from application.dto import (
    InitiateBookingRequest, LockSlotRequest, ConfirmBookingRequest,
    BookingResponse, CancelBookingRequest, RescheduleBookingRequest
)
from application.use_cases import BookingUseCase
from presentation.dependencies import (
    get_booking_use_case,
    get_current_active_user,
    get_current_admin,
    get_current_practitioner,
)

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
    Step 3: Confirm booking and process payment through REVEL POS
    
    This finalizes the booking, processes payment through REVEL POS,
    and sends confirmation notifications.
    """
    try:
        return await booking_use_case.confirm_booking(
            booking_id=request.booking_id,
            user_id=current_user["user_id"],
            payment_method=request.payment_method
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{booking_id}", response_model=dict)
async def get_booking(
    booking_id: str,
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """Get a specific booking by ID"""
    try:
        is_admin = current_user.get("role") == "admin"
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
        is_admin = current_user.get("role") == "admin"
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
