"""Application DTOs Package"""
from .schemas import (
    # Auth
    RegisterRequest, LoginRequest, TokenResponse, RefreshTokenRequest,
    GoogleOAuthRequest, CompleteOAuthPhoneRequest,
    SendVerificationOtpRequest, VerifyEmailOtpRequest,
    LookupEmailRequest, LookupEmailResponse,
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
    "GoogleOAuthRequest", "CompleteOAuthPhoneRequest",
    "SendVerificationOtpRequest", "VerifyEmailOtpRequest",
    "LookupEmailRequest", "LookupEmailResponse",
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
