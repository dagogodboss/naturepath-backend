"""
Data Transfer Objects (DTOs) - Application Layer
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field
from domain.entities import UserRole, BookingStatus, ServiceCategory, SlotStatus


# ==================== Auth DTOs ====================
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    phone: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class SendVerificationOtpRequest(BaseModel):
    email: EmailStr


class VerifyEmailOtpRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=8)


# ==================== User DTOs ====================
class UserResponse(BaseModel):
    user_id: str
    email: str
    first_name: str
    last_name: str
    phone: Optional[str]
    role: str
    is_active: bool
    is_verified: bool
    profile_image_url: Optional[str]
    created_at: str


class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    profile_image_url: Optional[str] = None


# ==================== Practitioner DTOs ====================
class PractitionerSpecialtyDTO(BaseModel):
    name: str
    description: Optional[str] = None
    years_experience: int = 0


class PractitionerAvailabilityDTO(BaseModel):
    day_of_week: int  # 0=Monday, 6=Sunday
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    is_available: bool = True


class CreatePractitionerRequest(BaseModel):
    user_id: str
    bio: str
    philosophy: Optional[str] = None
    specialties: List[PractitionerSpecialtyDTO] = []
    certifications: List[str] = []
    services: List[str] = []
    availability: List[PractitionerAvailabilityDTO] = []
    hourly_rate: float = 0.0
    is_featured: bool = False


class PractitionerResponse(BaseModel):
    practitioner_id: str
    user_id: str
    bio: str
    philosophy: Optional[str]
    specialties: List[dict]
    certifications: List[str]
    services: List[str]
    availability: List[dict]
    hourly_rate: float
    is_featured: bool
    rating: float
    total_reviews: int
    created_at: str
    # Populated fields
    user: Optional[UserResponse] = None


class UpdatePractitionerRequest(BaseModel):
    bio: Optional[str] = None
    philosophy: Optional[str] = None
    specialties: Optional[List[PractitionerSpecialtyDTO]] = None
    certifications: Optional[List[str]] = None
    services: Optional[List[str]] = None
    availability: Optional[List[PractitionerAvailabilityDTO]] = None
    hourly_rate: Optional[float] = None
    is_featured: Optional[bool] = None


# ==================== Service DTOs ====================
class CreateServiceRequest(BaseModel):
    name: str
    description: str
    category: ServiceCategory
    duration_minutes: int
    price: float
    discount_price: Optional[float] = None
    image_url: Optional[str] = None
    is_featured: bool = False
    max_capacity: int = 1
    revel_product_id: Optional[str] = None
    benefits: List[str] = Field(default_factory=list)
    warning_copy: Optional[str] = None
    is_discovery_entry: bool = False


class ServiceReviewResponse(BaseModel):
    review_id: str
    service_id: str
    author_name: str
    rating: int
    body: str
    created_at: str


class ServiceResponse(BaseModel):
    service_id: str
    name: str
    description: str
    category: str
    duration_minutes: int
    price: float
    discount_price: Optional[float]
    image_url: Optional[str]
    is_featured: bool
    is_active: bool
    max_capacity: int
    revel_product_id: Optional[str]
    benefits: List[str] = []
    warning_copy: Optional[str] = None
    rating_average: float = 0.0
    rating_count: int = 0
    created_at: str
    reviews: List[ServiceReviewResponse] = Field(default_factory=list)


class UpdateServiceRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[ServiceCategory] = None
    duration_minutes: Optional[int] = None
    price: Optional[float] = None
    discount_price: Optional[float] = None
    image_url: Optional[str] = None
    is_featured: Optional[bool] = None
    is_active: Optional[bool] = None
    max_capacity: Optional[int] = None
    benefits: Optional[List[str]] = None
    warning_copy: Optional[str] = None
    is_discovery_entry: Optional[bool] = None


# ==================== Booking DTOs ====================
class BookingSlotDTO(BaseModel):
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str  # HH:MM


class InitiateBookingRequest(BaseModel):
    service_id: str
    practitioner_id: Optional[str] = None
    slot: BookingSlotDTO
    notes: Optional[str] = None


class LockSlotRequest(BaseModel):
    practitioner_id: str
    date: str
    start_time: str


class ConfirmBookingRequest(BaseModel):
    booking_id: str
    payment_method: Optional[str] = "card"


class BookingResponse(BaseModel):
    booking_id: str
    customer_id: str
    practitioner_id: str
    service_id: str
    slot: dict
    status: str
    total_price: float
    notes: Optional[str]
    cancellation_reason: Optional[str]
    revel_order_id: Optional[str]
    payment_reference_id: Optional[str]
    created_at: str
    confirmed_at: Optional[str]
    completed_at: Optional[str]
    # Populated fields
    service: Optional[ServiceResponse] = None
    practitioner: Optional[PractitionerResponse] = None
    customer: Optional[UserResponse] = None


class CancelBookingRequest(BaseModel):
    booking_id: str
    reason: Optional[str] = None


class RescheduleBookingRequest(BaseModel):
    booking_id: str
    new_slot: BookingSlotDTO


# ==================== Availability DTOs ====================
class AvailabilitySlotResponse(BaseModel):
    slot_id: str
    practitioner_id: str
    date: str
    start_time: str
    end_time: str
    status: str


class GetAvailabilityRequest(BaseModel):
    practitioner_id: str
    date: str


class GenerateSlotsRequest(BaseModel):
    practitioner_id: str
    start_date: str
    end_date: str
    start_hour: int = 9
    end_hour: int = 18


# ==================== Payment DTOs ====================
class PaymentResponse(BaseModel):
    payment_id: str
    booking_id: str
    customer_id: str
    amount: float
    currency: str
    status: str
    revel_transaction_id: Optional[str]
    revel_order_id: Optional[str]
    payment_method: Optional[str]
    created_at: str
    completed_at: Optional[str]


# ==================== Notification DTOs ====================
class NotificationResponse(BaseModel):
    notification_id: str
    user_id: str
    type: str
    title: str
    message: str
    is_read: bool
    created_at: str


# ==================== Admin DTOs ====================
class AdminStatsResponse(BaseModel):
    total_customers: int
    total_practitioners: int
    total_services: int
    total_bookings: int
    bookings_today: int
    bookings_this_week: int
    bookings_this_month: int
    revenue_today: float
    revenue_this_week: float
    revenue_this_month: float


class BookingInsight(BaseModel):
    date: str
    count: int
    revenue: float


class BookingAnalyticsResponse(BaseModel):
    period: str
    total_bookings: int
    total_revenue: float
    average_booking_value: float
    top_services: List[dict]
    top_practitioners: List[dict]
    booking_trends: List[BookingInsight]
