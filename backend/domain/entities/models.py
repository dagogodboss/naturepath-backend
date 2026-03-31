"""
Domain Entities - The Natural Path Spa Management System
"""
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, EmailStr
import uuid


def generate_id() -> str:
    """Generate a unique ID"""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Get current UTC time"""
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    CUSTOMER = "customer"
    PRACTITIONER = "practitioner"
    ADMIN = "admin"


class BookingStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class SlotStatus(str, Enum):
    AVAILABLE = "available"
    LOCKED = "locked"
    BOOKED = "booked"
    BLOCKED = "blocked"


class NotificationType(str, Enum):
    BOOKING_CONFIRMATION = "booking_confirmation"
    BOOKING_REMINDER = "booking_reminder"
    BOOKING_CANCELLATION = "booking_cancellation"
    BOOKING_RESCHEDULED = "booking_rescheduled"
    PAYMENT_RECEIVED = "payment_received"
    WELCOME = "welcome"


# ==================== User Entity ====================
class User(BaseModel):
    """User aggregate root"""
    user_id: str = Field(default_factory=generate_id)
    email: EmailStr
    password_hash: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    role: UserRole = UserRole.CUSTOMER
    is_active: bool = True
    is_verified: bool = False
    is_discovery_completed: bool = False
    profile_image_url: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_login: Optional[datetime] = None
    
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


# ==================== Practitioner Entity ====================
class PractitionerSpecialty(BaseModel):
    """Value Object for practitioner specialty"""
    name: str
    description: Optional[str] = None
    years_experience: int = 0


class PractitionerAvailability(BaseModel):
    """Value Object for practitioner availability"""
    day_of_week: int  # 0=Monday, 6=Sunday
    start_time: str  # HH:MM format
    end_time: str  # HH:MM format
    is_available: bool = True


class Practitioner(BaseModel):
    """Practitioner aggregate root"""
    practitioner_id: str = Field(default_factory=generate_id)
    user_id: str
    bio: str
    philosophy: Optional[str] = None
    specialties: List[PractitionerSpecialty] = []
    certifications: List[str] = []
    services: List[str] = []  # List of service_ids
    availability: List[PractitionerAvailability] = []
    hourly_rate: float = 0.0
    is_featured: bool = False
    rating: float = 5.0
    total_reviews: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


# ==================== Service Entity ====================
class ServiceCategory(str, Enum):
    MASSAGE = "massage"
    FACIAL = "facial"
    BODY_TREATMENT = "body_treatment"
    WELLNESS = "wellness"
    HOLISTIC = "holistic"
    PACKAGE = "package"


class Service(BaseModel):
    """Service aggregate root"""
    service_id: str = Field(default_factory=generate_id)
    name: str
    description: str
    category: ServiceCategory
    duration_minutes: int
    price: float
    discount_price: Optional[float] = None
    image_url: Optional[str] = None
    is_featured: bool = False
    is_active: bool = True
    max_capacity: int = 1
    revel_product_id: Optional[str] = None  # REVEL POS integration
    benefits: List[str] = Field(default_factory=list)
    warning_copy: Optional[str] = None
    rating_average: float = 0.0
    rating_count: int = 0
    # True for the entry-point discovery offering (visible to guests / pre-unlock customers).
    is_discovery_entry: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ServiceReview(BaseModel):
    """Customer review shown on service detail (stored in service_reviews collection)."""
    review_id: str = Field(default_factory=generate_id)
    service_id: str
    author_name: str
    rating: int = Field(ge=1, le=5)
    body: str
    created_at: datetime = Field(default_factory=utc_now)


# ==================== Booking Entity ====================
class BookingSlot(BaseModel):
    """Value Object for booking time slot"""
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str  # HH:MM


class Booking(BaseModel):
    """Booking aggregate root"""
    booking_id: str = Field(default_factory=generate_id)
    customer_id: str
    practitioner_id: str
    service_id: str
    slot: BookingSlot
    status: BookingStatus = BookingStatus.DRAFT
    total_price: float
    notes: Optional[str] = None
    cancellation_reason: Optional[str] = None
    revel_order_id: Optional[str] = None  # REVEL POS integration
    payment_reference_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    confirmed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ==================== Availability Slot Entity ====================
class AvailabilitySlot(BaseModel):
    """Availability slot entity for real-time scheduling"""
    slot_id: str = Field(default_factory=generate_id)
    practitioner_id: str
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    status: SlotStatus = SlotStatus.AVAILABLE
    booking_id: Optional[str] = None
    locked_by: Optional[str] = None  # user_id who locked the slot
    locked_until: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)


# ==================== Payment Reference Entity ====================
class PaymentReference(BaseModel):
    """Payment reference entity for REVEL POS integration"""
    payment_id: str = Field(default_factory=generate_id)
    booking_id: str
    customer_id: str
    amount: float
    currency: str = "USD"
    status: PaymentStatus = PaymentStatus.PENDING
    revel_transaction_id: Optional[str] = None
    revel_order_id: Optional[str] = None
    payment_method: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: Optional[datetime] = None


# ==================== Notification Entity ====================
class Notification(BaseModel):
    """Notification entity"""
    notification_id: str = Field(default_factory=generate_id)
    user_id: str
    type: NotificationType
    title: str
    message: str
    is_read: bool = False
    metadata: dict = {}
    sent_email: bool = False
    sent_sms: bool = False
    created_at: datetime = Field(default_factory=utc_now)
