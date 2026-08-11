/**
 * natural-path-sdk - Type Definitions
 * 
 * Core types matching the backend API DTOs
 */

// ==================== Enums ====================
export type UserRole = 'customer' | 'staff' | 'manager' | 'practitioner' | 'admin' | 'owner';

export type BookingStatus = 
  | 'draft' 
  | 'pending' 
  | 'confirmed' 
  | 'in_progress' 
  | 'completed' 
  | 'cancelled' 
  | 'no_show';

export type PaymentStatus = 
  | 'pending' 
  | 'processing' 
  | 'completed' 
  | 'failed' 
  | 'refunded';

export type SlotStatus = 'available' | 'locked' | 'booked' | 'blocked';

export type ServiceCategory = 
  | 'massage' 
  | 'facial' 
  | 'body_treatment' 
  | 'wellness' 
  | 'holistic' 
  | 'package';

export type NotificationType =
  | 'booking_confirmation'
  | 'booking_reminder'
  | 'booking_cancellation'
  | 'booking_rescheduled'
  | 'payment_received'
  | 'welcome';

// ==================== User Types ====================
export interface User {
  user_id: string;
  email: string;
  first_name: string;
  last_name: string;
  phone?: string | null;
  role: UserRole;
  is_active: boolean;
  is_verified: boolean;
  is_discovery_completed?: boolean;
  profile_image_url?: string | null;
  created_at: string;
  updated_at: string;
  last_login?: string | null;
}

export interface RegisterRequest {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  phone: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LookupEmailRequest {
  email: string;
}

export interface LookupEmailResponse {
  exists: boolean;
  needs_password: boolean;
}

export interface GoogleOAuthRequest {
  id_token: string;
  phone?: string | null;
}

export interface CompleteOAuthPhoneRequest {
  setup_token: string;
  phone: string;
}

export interface GoogleOAuthStatus {
  enabled: boolean;
  client_id?: string | null;
}

/**
 * OAuth exchange: full JWTs when phone is present; otherwise needs_phone +
 * short-lived setup_token (no access/refresh until /oauth/complete-phone).
 */
export interface GoogleOAuthResponse {
  needs_phone?: boolean;
  setup_token?: string;
  setup_token_expires_in?: number;
  access_token?: string;
  refresh_token?: string;
  token_type?: string;
  expires_in?: number;
  user?: AuthResponse['user'] & {
    phone?: string | null;
    is_discovery_completed?: boolean;
  };
  email?: string;
  first_name?: string;
  last_name?: string;
}

export interface SendVerificationOtpRequest {
  email: string;
}

export interface VerifyEmailOtpRequest {
  email: string;
  code: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: {
    user_id: string;
    email: string;
    first_name: string;
    last_name: string;
    role: UserRole;
  };
}

export interface UpdateProfileRequest {
  first_name?: string;
  last_name?: string;
  phone?: string;
  profile_image_url?: string;
}

export interface DiscoveryEligibility {
  state: 'none' | 'scheduled' | 'pending_completion' | 'completed';
  is_discovery_completed: boolean;
  has_discovery_booking: boolean;
  has_discovery_flag: boolean;
  discovery_booking_id?: string | null;
  discovery_slot?: { date: string; start_time: string } | null;
  messaging_key: 'please_book' | 'scheduled' | 'pending' | 'unlocked';
}

// ==================== Practitioner Types ====================
export interface PractitionerSpecialty {
  name: string;
  description?: string | null;
  years_experience: number;
}

export interface PractitionerAvailability {
  day_of_week: number; // 0=Monday, 6=Sunday
  start_time: string; // HH:MM
  end_time: string; // HH:MM
  is_available: boolean;
}

export interface Practitioner {
  practitioner_id: string;
  user_id: string;
  bio: string;
  philosophy?: string | null;
  specialties: PractitionerSpecialty[];
  certifications: string[];
  services: string[];
  availability: PractitionerAvailability[];
  hourly_rate: number;
  is_featured: boolean;
  rating: number;
  total_reviews: number;
  created_at: string;
  updated_at: string;
  user?: User;
}

export interface CreatePractitionerRequest {
  user_id: string;
  bio: string;
  philosophy?: string;
  specialties?: PractitionerSpecialty[];
  certifications?: string[];
  services?: string[];
  availability?: PractitionerAvailability[];
  hourly_rate?: number;
  is_featured?: boolean;
}

export interface UpdatePractitionerRequest {
  bio?: string;
  philosophy?: string;
  specialties?: PractitionerSpecialty[];
  certifications?: string[];
  services?: string[];
  availability?: PractitionerAvailability[];
  hourly_rate?: number;
  is_featured?: boolean;
}

// ==================== Service Types ====================
export interface ServiceReview {
  review_id: string;
  service_id: string;
  author_name: string;
  rating: number;
  body: string;
  created_at: string;
}

export interface Service {
  service_id: string;
  name: string;
  description: string;
  category: ServiceCategory;
  duration_minutes: number;
  price: number;
  discount_price?: number | null;
  image_url?: string | null;
  is_featured: boolean;
  is_active: boolean;
  max_capacity: number;
  revel_product_id?: string | null;
  benefits?: string[];
  warning_copy?: string | null;
  is_discovery_entry?: boolean;
  requires_discovery?: boolean;
  /** True when caller may view but not book (pre-discovery / guest gate). */
  booking_locked?: boolean;
  rating_average?: number;
  rating_count?: number;
  reviews?: ServiceReview[];
  created_at: string;
  updated_at: string;
}

export interface CreateServiceRequest {
  name: string;
  description: string;
  category: ServiceCategory;
  duration_minutes: number;
  price: number;
  discount_price?: number;
  image_url?: string;
  is_featured?: boolean;
  max_capacity?: number;
  revel_product_id?: string;
  benefits?: string[];
  warning_copy?: string | null;
  is_discovery_entry?: boolean;
  requires_discovery?: boolean;
}

export interface UpdateServiceRequest {
  name?: string;
  description?: string;
  category?: ServiceCategory;
  duration_minutes?: number;
  price?: number;
  discount_price?: number;
  image_url?: string;
  is_featured?: boolean;
  is_active?: boolean;
  max_capacity?: number;
  benefits?: string[];
  warning_copy?: string | null;
  is_discovery_entry?: boolean;
  requires_discovery?: boolean;
}

// ==================== Availability Types ====================
export interface AvailabilitySlot {
  slot_id: string;
  practitioner_id: string;
  date: string; // YYYY-MM-DD
  start_time: string; // HH:MM
  end_time: string; // HH:MM
  status: SlotStatus;
  booking_id?: string | null;
  locked_by?: string | null;
  locked_until?: string | null;
  created_at: string;
}

export interface GenerateSlotsRequest {
  /** Optional; URL path id is authoritative when omitted. */
  practitioner_id?: string;
  start_date: string;
  end_date: string;
  start_hour?: number;
  end_hour?: number;
}

// ==================== Booking Types ====================
export interface BookingSlot {
  date: string; // YYYY-MM-DD
  start_time: string; // HH:MM
  end_time: string; // HH:MM
}

export interface BookingRecurrence {
  frequency?: string;
  active?: boolean;
  horizon_months?: number;
  series_id?: string;
  stopped_at?: string | null;
  [key: string]: unknown;
}

export interface Booking {
  booking_id: string;
  customer_id: string;
  practitioner_id: string;
  service_id: string;
  slot: BookingSlot;
  status: BookingStatus;
  total_price: number;
  notes?: string | null;
  cancellation_reason?: string | null;
  revel_order_id?: string | null;
  revel_transaction_id?: string | null;
  payment_mode?: 'card_online' | 'walk_in' | null;
  payment_status?: string | null;
  payment_link_id?: string | null;
  payment_link_url?: string | null;
  payment_amount?: number | null;
  receipt_id?: string | null;
  paid_at?: string | null;
  payment_reference_id?: string | null;
  /** Monthly series id shared by parent + materialised children. */
  series_id?: string | null;
  series_parent_id?: string | null;
  recurrence?: BookingRecurrence | null;
  created_at: string;
  updated_at: string;
  confirmed_at?: string | null;
  completed_at?: string | null;
  // Populated fields
  service?: Service;
  practitioner?: Practitioner;
  customer?: User;
}

export interface StopRecurringResponse extends Booking {
  cancelled_future?: string[];
  series_id?: string | null;
}

export interface BookingPaymentStatusResponse {
  booking_id: string;
  payment_status?: string | null;
  payment_mode?: 'card_online' | 'walk_in' | null;
  payment_amount?: number | null;
  payment_link_url?: string | null;
  revel_transaction_id?: string | null;
  receipt_id?: string | null;
  paid_at?: string | null;
}

export interface MarkPaidAtCounterRequest {
  amount: number;
  revel_receipt_id: string;
  notes?: string;
}

export interface InitiateBookingRequest {
  service_id: string;
  practitioner_id?: string;
  slot: BookingSlot;
  notes?: string;
  /** Opt-in monthly recurrence after discovery unlock (default false). */
  enable_monthly_recurrence?: boolean;
}

export interface ServiceSlotWindow {
  start_time: string;
  end_time: string;
}

export interface LockSlotResponse {
  booking_id: string;
  slot_id: string;
  locked_until: string;
  status: string;
}

export interface ConfirmBookingRequest {
  booking_id: string;
}

export interface CancelBookingRequest {
  booking_id: string;
  reason?: string;
}

export interface RescheduleBookingRequest {
  booking_id: string;
  new_slot: BookingSlot;
}

/** Practitioner client directory */
export interface ClientListItem {
  client_id: string;
  name: string;
  email?: string;
  phone?: string;
  total_sessions: number;
  last_visit_date?: string | null;
}

export interface ClientListResponse {
  items: ClientListItem[];
  total: number;
}

export interface ClientDetailAppointment {
  booking_id: string;
  status?: string;
  service_name: string;
  date?: string;
  start_time?: string;
  end_time?: string;
}

export interface ClientDetailResponse {
  client_id: string;
  name: string;
  email?: string;
  phone?: string;
  join_date?: string;
  appointments: ClientDetailAppointment[];
  store_orders: Array<{
    order_id: string;
    total?: number;
    payment_status?: string;
    created_at?: string;
  }>;
}

// ==================== Payment Types ====================
export interface Payment {
  payment_id: string;
  booking_id: string;
  customer_id: string;
  amount: number;
  currency: string;
  status: PaymentStatus;
  revel_transaction_id?: string | null;
  revel_order_id?: string | null;
  payment_method?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface RevelOrder {
  order_id: string;
  establishment_id: number;
  customer_id?: string;
  items: Array<{
    product_id: string;
    name: string;
    quantity: number;
    price: number;
  }>;
  subtotal: number;
  tax: number;
  total: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface BookingConfirmationResponse extends Booking {
  payment?: Payment | null;
  revel_order?: RevelOrder | null;
}

// ==================== Notification Types ====================
export interface Notification {
  notification_id: string;
  user_id: string;
  type: NotificationType;
  title: string;
  message: string;
  is_read: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
}

// ==================== Admin Types ====================
export interface AdminStats {
  total_customers: number;
  total_practitioners: number;
  total_services: number;
  total_bookings: number;
  bookings_today: number;
  bookings_this_week: number;
  bookings_this_month: number;
  revenue_today: number;
  revenue_this_week: number;
  revenue_this_month: number;
}

export interface BookingInsight {
  date: string;
  count: number;
  revenue: number;
}

export interface BookingAnalytics {
  period: string;
  start_date: string;
  end_date: string;
  total_bookings: number;
  total_revenue: number;
  average_booking_value: number;
  top_services: Array<{
    service_id: string;
    name: string;
    count: number;
    revenue: number;
  }>;
  top_practitioners: Array<{
    practitioner_id: string;
    count: number;
    revenue: number;
  }>;
  booking_trends: BookingInsight[];
}

export interface StoreFunnelAnalytics {
  period_days: number;
  unique_sessions: number;
  funnel: {
    product_list_viewed: number;
    add_to_cart: number;
    checkout_started: number;
    order_placed: number;
    payment_success: number;
    payment_failed: number;
    checkout_failed: number;
  };
  rates: {
    checkout_to_order_pct: number;
    payment_success_pct: number;
  };
  payment_method_split: Record<
    string,
    {
      order_placed: number;
      payment_success: number;
      payment_failed: number;
    }
  >;
}

// ==================== API Response Types ====================
export interface ApiError {
  detail: string;
  status_code?: number;
}

export interface HealthCheck {
  status: string;
  service: string;
  version: string;
}

// ==================== Store / Commerce Types ====================
export type StorePaymentMethod = 'prepaid_online' | 'pay_on_delivery' | 'manual_backoffice';
export type StorePaymentState =
  | 'pending'
  | 'processing'
  | 'awaiting_payment'
  | 'awaiting_counter'
  | 'authorized'
  | 'captured'
  | 'failed'
  | 'manual_due'
  | 'refunded'
  | 'partial_refunded'
  | 'voided'
  | 'expired'
  | 'none';
export type StoreFulfillmentState =
  | 'placed'
  | 'confirmed'
  | 'preparing'
  | 'fulfilled'
  | 'delivered'
  | 'rejected'
  | 'refunded';

export interface StoreProduct {
  product_id: string;
  revel_product_id: string;
  name: string;
  category: string;
  price: number;
  discount_price?: number | null;
  stock_qty?: number;
  is_active: boolean;
  is_active_web: boolean;
  image_url?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface StoreAddress {
  full_name: string;
  phone: string;
  email: string;
  line1: string;
  line2?: string | null;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  delivery_notes?: string | null;
}

export interface StoreOrderItem {
  product_id: string;
  quantity: number;
  name?: string;
  unit_price?: number;
  line_total?: number;
}

export type StorePaymentMode = 'card_online' | 'walk_in';

export interface CreateStoreOrderRequest {
  items: StoreOrderItem[];
  address: StoreAddress;
  payment_mode?: StorePaymentMode;
  payment_method: StorePaymentMethod;
  customer_note?: string;
}

export interface StoreOrder {
  order_id: string;
  customer_id?: string | null;
  items: StoreOrderItem[];
  address: StoreAddress;
  payment_mode?: StorePaymentMode;
  payment_method: StorePaymentMethod;
  payment_status: StorePaymentState;
  fulfillment_status: StoreFulfillmentState;
  subtotal: number;
  tax: number;
  total: number;
  currency: string;
  customer_note?: string | null;
  payment_link_url?: string | null;
  invoice_id?: string | null;
  created_at: string;
  updated_at: string;
  revel_transaction_id?: string | null;
  revel_order_id?: string | null;
  allowed_actions?: {
    refund: boolean;
    reject: boolean;
    confirm: boolean;
    fulfill: boolean;
  };
}

export interface BackfillRevelTransactionRequest {
  revel_transaction_id: string;
}

export interface BackfillRevelTransactionResponse {
  order_id: string;
  revel_transaction_id: string;
  payment_status: string;
  updated_at?: string;
}

export interface StoreProductsResponse {
  items: StoreProduct[];
  page: number;
  page_size: number;
  total: number;
}

// ==================== Admin RBAC ====================
export interface RbacBaselineResponse {
  permissions: string[];
  role_hints: Record<string, string[]>;
  override_help: Record<string, string>;
}

export interface RbacPolicyOverride {
  _id: string;
  ptype: 'p' | 'g';
  v0: string;
  v1: string;
  v2?: string;
  created_at?: string;
}

export interface RbacOverrideCreateRequest {
  ptype: 'p' | 'g';
  v0: string;
  v1: string;
  v2?: string | null;
}

export interface ReconciliationReport {
  report_id: string;
  date: string;
  ref_type: string;
  ref_id: string;
  revel_order_id?: string | null;
  drift_type: string;
  our_value?: unknown;
  revel_value?: unknown;
  resolved: boolean;
  resolved_by?: string;
  resolved_at?: string;
  created_at: string;
}

// ==================== Content / Reels Types ====================
export type ContentType = 'blog' | 'vlog';
export type ContentStatus = 'draft' | 'published';

export interface ContentPost {
  post_id: string;
  type: ContentType;
  title: string;
  slug?: string;
  body?: string | null;
  caption?: string | null;
  cover_url?: string | null;
  media_url?: string | null;
  /**
   * Optional Phase G native 1-min preview clip URL (CDN or GCS).
   * When absent, clients should use interim `#t=0,preview_seconds` on media_url.
   * Server composes public URLs from CDN_BASE_URL when set to a real front door;
   * otherwise signed GET URLs (never anonymous storage.googleapis.com under PAP).
   * Phase G server-side preview clips are not generated yet — clients use
   * preview_clip_url when present, else media fragment helpers.
   */
  preview_clip_url?: string | null;
  embed_url?: string | null;
  status: ContentStatus;
  aspect_ratio?: '4:5' | '3:4' | null;
  published_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface ReelItem extends ContentPost {
  seen?: boolean;
  like_count?: number;
  comment_count?: number;
  liked_by_me?: boolean;
  /** Interim preview window in seconds when preview_clip_url is absent. */
  preview_seconds?: number;
}

export interface ContentComment {
  comment_id: string;
  post_id: string;
  user_id: string;
  author_name?: string;
  body: string;
  created_at: string;
  updated_at?: string;
}

export interface ContentPostsResponse {
  items: ContentPost[];
}

export interface ReelsFeedResponse {
  items: ReelItem[];
}

export interface ReelCommentsResponse {
  items: ContentComment[];
}

export interface CreateContentPostRequest {
  type: ContentType;
  title: string;
  body?: string | null;
  caption?: string | null;
  cover_url?: string | null;
  media_url?: string | null;
  /** GCS object key for native video (Phase G preview pipeline). */
  media_object_name?: string | null;
  embed_url?: string | null;
  status?: ContentStatus;
  aspect_ratio?: '4:5' | '3:4' | null;
}

export type UpdateContentPostRequest = Partial<CreateContentPostRequest>;

export interface SignedUploadRequest {
  filename: string;
  content_type: string;
  kind?: 'image' | 'video';
}

export interface SignedUploadResponse {
  upload_url?: string;
  public_url?: string;
  object_name?: string;
  content_type?: string;
  /** When GCS is unset, API may instruct embed/media_url only. */
  message?: string;
  gcs_enabled?: boolean;
}

export interface StorePaymentConfig {
  sms_pay_link?: boolean;
  [key: string]: unknown;
}

// ==================== WebSocket Types ====================
export interface WebSocketMessage<T = unknown> {
  type: string;
  data?: T;
  timestamp: string;
}

export interface AvailabilityUpdate {
  practitioner_id: string;
  date: string;
  slots: AvailabilitySlot[];
}

export interface SlotLockedEvent {
  practitioner_id: string;
  date: string;
  slot_id: string;
}

export interface SlotReleasedEvent {
  practitioner_id: string;
  date: string;
  slot_id: string;
}
