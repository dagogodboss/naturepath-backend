"""
API Dependencies - Presentation Layer
"""
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional

from infrastructure.database import get_database
from infrastructure.repositories import (
    MongoUserRepository,
    MongoPractitionerRepository,
    MongoServiceRepository,
    MongoServiceReviewRepository,
    MongoBookingRepository,
    MongoAvailabilitySlotRepository,
    MongoPaymentRepository,
    MongoNotificationRepository,
    MongoEventRepository
)
from infrastructure.cache import get_cache_service, CacheService
from application.use_cases import (
    AuthUseCase,
    BookingUseCase,
    ServiceUseCase,
    PractitionerUseCase
)
from core.rbac import Permission, has_permission, normalize_role

async def _audit_authorization(
    db: AsyncIOMotorDatabase,
    *,
    user_id: str | None,
    role: str | None,
    permission: Permission,
    allowed: bool,
    path: str,
    method: str,
):
    await db.authorization_audit.insert_one(
        {
            "user_id": user_id,
            "role": role,
            "permission": permission.value,
            "allowed": allowed,
            "path": path,
            "method": method,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


security = HTTPBearer()


# Repository dependencies
def get_user_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoUserRepository:
    return MongoUserRepository(db)


def get_practitioner_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoPractitionerRepository:
    return MongoPractitionerRepository(db)


def get_service_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoServiceRepository:
    return MongoServiceRepository(db)


def get_service_review_repo(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> MongoServiceReviewRepository:
    return MongoServiceReviewRepository(db)


def get_booking_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoBookingRepository:
    return MongoBookingRepository(db)


def get_slot_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoAvailabilitySlotRepository:
    return MongoAvailabilitySlotRepository(db)


def get_payment_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoPaymentRepository:
    return MongoPaymentRepository(db)


def get_notification_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoNotificationRepository:
    return MongoNotificationRepository(db)


def get_event_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoEventRepository:
    return MongoEventRepository(db)


# Use case dependencies
def get_auth_use_case(
    user_repo: MongoUserRepository = Depends(get_user_repo)
) -> AuthUseCase:
    return AuthUseCase(user_repo)


async def get_service_use_case(
    service_repo: MongoServiceRepository = Depends(get_service_repo),
    review_repo: MongoServiceReviewRepository = Depends(get_service_review_repo),
) -> ServiceUseCase:
    cache = await get_cache_service()
    return ServiceUseCase(service_repo, review_repo, cache)


async def get_practitioner_use_case(
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo),
    user_repo: MongoUserRepository = Depends(get_user_repo),
    slot_repo: MongoAvailabilitySlotRepository = Depends(get_slot_repo)
) -> PractitionerUseCase:
    cache = await get_cache_service()
    return PractitionerUseCase(practitioner_repo, user_repo, slot_repo, cache)


async def get_booking_use_case(
    booking_repo: MongoBookingRepository = Depends(get_booking_repo),
    slot_repo: MongoAvailabilitySlotRepository = Depends(get_slot_repo),
    service_repo: MongoServiceRepository = Depends(get_service_repo),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo),
    user_repo: MongoUserRepository = Depends(get_user_repo),
    payment_repo: MongoPaymentRepository = Depends(get_payment_repo),
    event_repo: MongoEventRepository = Depends(get_event_repo)
) -> BookingUseCase:
    cache = await get_cache_service()
    return BookingUseCase(
        booking_repo, slot_repo, service_repo, practitioner_repo,
        user_repo, payment_repo, event_repo, cache
    )


# Authentication dependencies
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth_use_case: AuthUseCase = Depends(get_auth_use_case)
):
    """Get current authenticated user"""
    try:
        token = credentials.credentials
        user = await auth_use_case.get_current_user(token)
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )


async def get_current_active_user(
    current_user: dict = Depends(get_current_user)
):
    """Get current active user"""
    if not current_user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    current_user["role"] = normalize_role(current_user.get("role"))
    return current_user


def require_permission(permission: Permission):
    async def _require_permission(
        request: Request,
        current_user: dict = Depends(get_current_active_user),
        db: AsyncIOMotorDatabase = Depends(get_database),
    ):
        allowed = has_permission(current_user.get("role"), permission)
        await _audit_authorization(
            db,
            user_id=current_user.get("user_id"),
            role=current_user.get("role"),
            permission=permission,
            allowed=allowed,
            path=request.url.path,
            method=request.method,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission.value}",
            )
        return current_user

    return _require_permission


async def get_current_admin(
    request: Request,
    current_user: dict = Depends(get_current_active_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Get current elevated user (admin/practitioner/manager with user-role-manage permission)."""
    allowed = has_permission(current_user.get("role"), Permission.USER_ROLE_MANAGE)
    await _audit_authorization(
        db,
        user_id=current_user.get("user_id"),
        role=current_user.get("role"),
        permission=Permission.USER_ROLE_MANAGE,
        allowed=allowed,
        path=request.url.path,
        method=request.method,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin-level access required"
        )
    return current_user


async def get_current_practitioner(
    request: Request,
    current_user: dict = Depends(get_current_active_user),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Get current practitioner user"""
    allowed = has_permission(current_user.get("role"), Permission.PRACTITIONER_PROFILE_MANAGE)
    await _audit_authorization(
        db,
        user_id=current_user.get("user_id"),
        role=current_user.get("role"),
        permission=Permission.PRACTITIONER_PROFILE_MANAGE,
        allowed=allowed,
        path=request.url.path,
        method=request.method,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Practitioner access required"
        )
    
    # Get practitioner profile
    practitioner = await practitioner_repo.get_by_user_id(current_user["user_id"])
    if not practitioner and not has_permission(current_user.get("role"), Permission.USER_ROLE_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practitioner profile not found"
        )
    
    return {"user": current_user, "practitioner": practitioner}


async def get_current_admin_or_practitioner(
    request: Request,
    current_user: dict = Depends(get_current_active_user),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Admin (no practitioner profile required) or practitioner with a linked profile.
    Used for creating services and generating availability as a practitioner.
    """
    role = current_user.get("role")
    if has_permission(role, Permission.USER_ROLE_MANAGE):
        await _audit_authorization(
            db,
            user_id=current_user.get("user_id"),
            role=role,
            permission=Permission.USER_ROLE_MANAGE,
            allowed=True,
            path=request.url.path,
            method=request.method,
        )
        return {"user": current_user, "practitioner": None}
    if has_permission(role, Permission.PRACTITIONER_PROFILE_MANAGE):
        await _audit_authorization(
            db,
            user_id=current_user.get("user_id"),
            role=role,
            permission=Permission.PRACTITIONER_PROFILE_MANAGE,
            allowed=True,
            path=request.url.path,
            method=request.method,
        )
        practitioner = await practitioner_repo.get_by_user_id(current_user["user_id"])
        if not practitioner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Practitioner profile not found",
            )
        return {"user": current_user, "practitioner": practitioner}
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin or practitioner role required",
    )


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    auth_use_case: AuthUseCase = Depends(get_auth_use_case),
):
    """Return the current user when a valid Bearer token is sent; otherwise None."""
    if not credentials:
        return None
    try:
        user = await auth_use_case.get_current_user(credentials.credentials)
        user["role"] = normalize_role(user.get("role"))
        return user
    except ValueError:
        return None
