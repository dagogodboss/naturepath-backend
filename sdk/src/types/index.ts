/**
 * @natural-path/sdk - Type Definitions
 * 
 * Core types matching the backend API DTOs
 */

// ==================== Enums ====================
export type UserRole = 'customer' | 'practitioner' | 'admin';

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
  phone?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
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
  is_discovery_completed: boolean;
  has_discovery_booking: boolean;
  has_discovery_flag: boolean;
  discovery_booking_id?: string | null;
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
  practitioner_id: string;
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
  payment_reference_id?: string | null;
  created_at: string;
  updated_at: string;
  confirmed_at?: string | null;
  completed_at?: string | null;
  // Populated fields
  service?: Service;
  practitioner?: Practitioner;
  customer?: User;
}

export interface InitiateBookingRequest {
  service_id: string;
  practitioner_id: string;
  slot: BookingSlot;
  notes?: string;
}

export interface LockSlotResponse {
  booking_id: string;
  slot_id: string;
  locked_until: string;
  status: string;
}

export interface ConfirmBookingRequest {
  booking_id: string;
  payment_method?: string;
}

export interface CancelBookingRequest {
  booking_id: string;
  reason?: string;
}

export interface RescheduleBookingRequest {
  booking_id: string;
  new_slot: BookingSlot;
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
  payment: Payment;
  revel_order: RevelOrder;
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
