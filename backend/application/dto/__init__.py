"""Application DTOs Package"""
from .schemas import (
    # Auth
    RegisterRequest, LoginRequest, TokenResponse, RefreshTokenRequest,
    # User
    UserResponse, UpdateProfileRequest,
    # Practitioner
    PractitionerSpecialtyDTO, PractitionerAvailabilityDTO,
    CreatePractitionerRequest, PractitionerResponse, UpdatePractitionerRequest,
    # Service
    CreateServiceRequest, ServiceResponse, UpdateServiceRequest,
    # Booking
    BookingSlotDTO, InitiateBookingRequest, LockSlotRequest,
    ConfirmBookingRequest, BookingResponse, CancelBookingRequest, RescheduleBookingRequest,
    # Availability
    AvailabilitySlotResponse, GetAvailabilityRequest, GenerateSlotsRequest,
    # Payment
    PaymentResponse,
    # Notification
    NotificationResponse,
    # Admin
    AdminStatsResponse, BookingInsight, BookingAnalyticsResponse
)

__all__ = [
    "RegisterRequest", "LoginRequest", "TokenResponse", "RefreshTokenRequest",
    "UserResponse", "UpdateProfileRequest",
    "PractitionerSpecialtyDTO", "PractitionerAvailabilityDTO",
    "CreatePractitionerRequest", "PractitionerResponse", "UpdatePractitionerRequest",
    "CreateServiceRequest", "ServiceResponse", "UpdateServiceRequest",
    "BookingSlotDTO", "InitiateBookingRequest", "LockSlotRequest",
    "ConfirmBookingRequest", "BookingResponse", "CancelBookingRequest", "RescheduleBookingRequest",
    "AvailabilitySlotResponse", "GetAvailabilityRequest", "GenerateSlotsRequest",
    "PaymentResponse",
    "NotificationResponse",
    "AdminStatsResponse", "BookingInsight", "BookingAnalyticsResponse"
]
