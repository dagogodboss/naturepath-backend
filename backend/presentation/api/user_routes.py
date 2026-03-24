"""
User API Routes - Customer Portal
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from application.dto import UserResponse, UpdateProfileRequest
from presentation.dependencies import (
    get_current_active_user,
    get_user_repo,
    get_booking_use_case,
    get_notification_repo,
    get_practitioner_repo,
)
from infrastructure.repositories import (
    MongoUserRepository,
    MongoNotificationRepository,
    MongoPractitionerRepository,
)
from application.use_cases import BookingUseCase

router = APIRouter(prefix="/me", tags=["User Profile"])


@router.get("", response_model=dict)
async def get_profile(
    current_user: dict = Depends(get_current_active_user)
):
    """Get current user profile"""
    return current_user


@router.get("/practitioner", response_model=dict)
async def get_my_practitioner_profile(
    current_user: dict = Depends(get_current_active_user),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo),
):
    """Return practitioner profile for the logged-in practitioner (or admin with a linked profile)."""
    if current_user.get("role") not in ("practitioner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Practitioner or admin role required",
        )
    practitioner = await practitioner_repo.get_by_user_id(current_user["user_id"])
    if not practitioner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practitioner profile not found",
        )
    return practitioner


@router.patch("", response_model=dict)
async def update_profile(
    request: UpdateProfileRequest,
    current_user: dict = Depends(get_current_active_user),
    user_repo: MongoUserRepository = Depends(get_user_repo)
):
    """Update current user profile"""
    updates = request.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        return current_user
    
    updated = await user_repo.update(current_user["user_id"], updates)
    if updated:
        updated.pop("password_hash", None)
    return updated


@router.get("/bookings", response_model=List[dict])
async def get_my_bookings(
    current_user: dict = Depends(get_current_active_user),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case)
):
    """Get current user's bookings"""
    return await booking_use_case.get_customer_bookings(current_user["user_id"])


@router.get("/notifications", response_model=List[dict])
async def get_my_notifications(
    unread_only: bool = False,
    current_user: dict = Depends(get_current_active_user),
    notification_repo: MongoNotificationRepository = Depends(get_notification_repo)
):
    """Get current user's notifications"""
    return await notification_repo.get_by_user(current_user["user_id"], unread_only)


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_active_user),
    notification_repo: MongoNotificationRepository = Depends(get_notification_repo)
):
    """Mark a notification as read"""
    notification = await notification_repo.get_by_id(notification_id)
    if not notification or notification["user_id"] != current_user["user_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    
    await notification_repo.mark_as_read(notification_id)
    return {"success": True}


@router.post("/notifications/read-all")
async def mark_all_notifications_read(
    current_user: dict = Depends(get_current_active_user),
    notification_repo: MongoNotificationRepository = Depends(get_notification_repo)
):
    """Mark all notifications as read"""
    count = await notification_repo.mark_all_as_read(current_user["user_id"])
    return {"success": True, "marked_count": count}
