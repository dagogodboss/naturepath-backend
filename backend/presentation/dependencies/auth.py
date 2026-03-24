"""
API Dependencies - Presentation Layer
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional

from infrastructure.database import get_database
from infrastructure.repositories import (
    MongoUserRepository,
    MongoPractitionerRepository,
    MongoServiceRepository,
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

security = HTTPBearer()


# Repository dependencies
def get_user_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoUserRepository:
    return MongoUserRepository(db)


def get_practitioner_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoPractitionerRepository:
    return MongoPractitionerRepository(db)


def get_service_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoServiceRepository:
    return MongoServiceRepository(db)


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
    service_repo: MongoServiceRepository = Depends(get_service_repo)
) -> ServiceUseCase:
    cache = await get_cache_service()
    return ServiceUseCase(service_repo, cache)


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
    return current_user


async def get_current_admin(
    current_user: dict = Depends(get_current_active_user)
):
    """Get current admin user"""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


async def get_current_practitioner(
    current_user: dict = Depends(get_current_active_user),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo)
):
    """Get current practitioner user"""
    if current_user.get("role") not in ["practitioner", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Practitioner access required"
        )
    
    # Get practitioner profile
    practitioner = await practitioner_repo.get_by_user_id(current_user["user_id"])
    if not practitioner and current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practitioner profile not found"
        )
    
    return {"user": current_user, "practitioner": practitioner}


async def get_current_admin_or_practitioner(
    current_user: dict = Depends(get_current_active_user),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo),
):
    """
    Admin (no practitioner profile required) or practitioner with a linked profile.
    Used for creating services and generating availability as a practitioner.
    """
    role = current_user.get("role")
    if role == "admin":
        return {"user": current_user, "practitioner": None}
    if role == "practitioner":
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


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    auth_use_case: AuthUseCase = Depends(get_auth_use_case)
):
    """Get user if authenticated, None otherwise"""
    async def _get_user():
        if not credentials:
            return None
        try:
            return await auth_use_case.get_current_user(credentials.credentials)
        except ValueError:
            return None
    return _get_user
