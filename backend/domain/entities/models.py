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
    STAFF = "staff"
    MANAGER = "manager"
    PRACTITIONER = "practitioner"
    ADMIN = "admin"
    OWNER = "owner"


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
    ORDER_PLACED = "order_placed"


# ==================== User Entity ====================
class User(BaseModel):
    """User aggregate root"""
    user_id: str = Field(default_factory=generate_id)
    email: EmailStr
    # Nullable for unclaimed guest-purchase accounts (claim via later register).
    password_hash: Optional[str] = None
    first_name: str
    last_name: str
    phone: Optional[str] = None
    role: UserRole = UserRole.CUSTOMER
    is_active: bool = True
    is_verified: bool = False
    is_discovery_completed: bool = False
    discovery_completed_at: Optional[datetime] = None
    discovery_completed_by: Optional[str] = None
    # Service id that was completed when the prerequisite gate was unlocked.
    prerequisite_completed_service_id: Optional[str] = None
    # password | guest_purchase | oauth
    auth_method: str = "password"
    account_claimed: bool = True
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
    # True for the single business-wide prerequisite service.
    is_prerequisite: bool = False
    # Legacy flag kept in sync with requires_prerequisite.
    requires_discovery: bool = True
    # On: customer must complete the current prerequisite service before booking.
    requires_prerequisite: bool = True
    # Multi-resource scheduling (Phase 1 scaffold; unused until flag + Phase 3).
    required_resource_id: Optional[str] = None
    customer_duration_minutes: Optional[int] = None  # synonym of duration_minutes when set
    prep_minutes: int = 0
    recovery_minutes: int = 0
    service_hours: Optional[List[PractitionerAvailability]] = None
    booking_window_days: Optional[int] = None
    min_notice_minutes: Optional[int] = None
    flags: dict = Field(default_factory=dict)
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
    education_topics: Optional[List[str]] = None
    cancellation_reason: Optional[str] = None
    revel_order_id: Optional[str] = None  # REVEL POS integration
    revel_transaction_id: Optional[str] = None
    payment_mode: Optional[str] = None  # card_online | walk_in
    payment_status: str = "none"  # none | awaiting_payment | awaiting_counter | captured | refunded
    payment_link_id: Optional[str] = None
    payment_link_url: Optional[str] = None
    payment_amount: Optional[float] = None
    receipt_id: Optional[str] = None
    paid_at: Optional[datetime] = None
    payment_reference_id: Optional[str] = None
    # Monthly series: parent holds recurrence; children share series_id.
    # Conflict policy on materialize: skip unavailable months + email note.
    recurrence: Optional[dict] = None  # { frequency: "monthly", active: bool, ... }
    series_id: Optional[str] = None
    series_parent_id: Optional[str] = None
    series_index: Optional[int] = None
    # Reminder idempotency: { "d3": true, "d1": true, "d0": true }
    reminders_sent: Optional[dict] = None
    # Multi-resource scheduling (Phase 1 scaffold; unused until cutover).
    resource_id: Optional[str] = None
    customer_start_time: Optional[str] = None  # HH:MM; defaults to slot.start_time
    customer_end_time: Optional[str] = None
    occupied_start_time: Optional[str] = None
    occupied_end_time: Optional[str] = None
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


# ==================== Multi-resource scheduling (Phase 1 scaffold) ====================
# Schema groundwork only. Booking open-dates and Outlook sync stay on the legacy
# practitioner-scoped paths until MULTI_RESOURCE_SCHEDULING is enabled in later phases.


class ResourceType(str, Enum):
    PRACTITIONER = "practitioner"
    ROOM = "room"


class ResourceSlotGrid(BaseModel):
    """Optional slot-offer grid. LOCKED Salt: anytime (seed uses fine increment, e.g. 15)."""
    start_increment_minutes: int = 60


class Resource(BaseModel):
    """Schedulable capacity unit (practitioner or room). Collection: resources."""
    resource_id: str = Field(default_factory=generate_id)
    type: ResourceType
    name: str
    timezone: str = "America/Chicago"
    active: bool = True
    weekly_hours: List[PractitionerAvailability] = Field(default_factory=list)
    linked_practitioner_id: Optional[str] = None
    linked_practitioner_user_id: Optional[str] = None
    slot_grid: Optional[ResourceSlotGrid] = None
    last_start_time: Optional[str] = None  # HH:MM; LOCKED Salt "17:00"
    capacity: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BusyIntervalSource(str, Enum):
    OUTLOOK = "outlook"
    BOOKING = "booking"
    MANUAL = "manual"


class ResourceBusyInterval(BaseModel):
    """Occupied span on a resource. Collection: resource_busy_intervals."""
    interval_id: str = Field(default_factory=generate_id)
    resource_id: str
    date: str  # YYYY-MM-DD clinic-local
    start_time: str  # HH:MM (or 24:00)
    end_time: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    source: BusyIntervalSource
    authoritative: bool = True
    connection_id: Optional[str] = None
    event_id: Optional[str] = None
    booking_id: Optional[str] = None
    category_name: Optional[str] = None
    show_as: str = "busy"
    is_cancelled: bool = False
    synced_at: Optional[datetime] = None


class ReviewQueueItemType(str, Enum):
    UNMAPPED_CATEGORY = "unmapped_category"
    SYNC_CONFLICT = "sync_conflict"
    SCHEDULE_CHANGE_IMPACT = "schedule_change_impact"
    MANUAL_OUTLOOK_RACE = "manual_outlook_race"


class ReviewQueueItemStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReviewQueueItem(BaseModel):
    """Scheduling review queue (not service star-reviews). Collection: review_queue."""
    review_id: str = Field(default_factory=generate_id)
    type: ReviewQueueItemType
    status: ReviewQueueItemStatus = ReviewQueueItemStatus.OPEN
    resource_id: Optional[str] = None
    connection_id: Optional[str] = None
    event_id: Optional[str] = None
    booking_id: Optional[str] = None
    category_name: Optional[str] = None
    message: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: Optional[datetime] = None


class OutlookCategoryMap(BaseModel):
    """Category → resource map entry stored on an Outlook mailbox connection."""
    category_name: str
    resource_ids: List[str] = Field(default_factory=list)
    blocks_all_authoritative: Optional[bool] = None


class OutlookMailboxConnectionFields(BaseModel):
    """
    Multi-resource fields for outlook_calendar_connections (extend existing docs).

    Not wired into OAuth callback / sync yet — scaffold for Phase 2.
    """
    mailbox_email: Optional[str] = None
    linked_practitioner_id: Optional[str] = None
    authoritative_for_resource_ids: List[str] = Field(default_factory=list)
    visibility_only: bool = False
    category_maps: List[OutlookCategoryMap] = Field(default_factory=list)
