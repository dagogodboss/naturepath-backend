/**
 * natural-path-sdk - API Endpoints
 * 
 * All API calls are centralized here
 */

import { getApiClient } from './client';
import type {
  // Auth
  LoginRequest,
  RegisterRequest,
  AuthResponse,
  // User
  User,
  DiscoveryEligibility,
  UpdateProfileRequest,
  // Service
  Service,
  ServiceReview,
  CreateServiceRequest,
  UpdateServiceRequest,
  // Practitioner
  Practitioner,
  CreatePractitionerRequest,
  UpdatePractitionerRequest,
  // Availability
  AvailabilitySlot,
  GenerateSlotsRequest,
  // Booking
  Booking,
  InitiateBookingRequest,
  ServiceSlotWindow,
  LockSlotResponse,
  ConfirmBookingRequest,
  CancelBookingRequest,
  RescheduleBookingRequest,
  BookingConfirmationResponse,
  BookingPaymentStatusResponse,
  MarkPaidAtCounterRequest,
  ClientListResponse,
  ClientDetailResponse,
  // Notification
  Notification,
  // Admin
  AdminStats,
  BookingAnalytics,
  StoreFunnelAnalytics,
  RbacBaselineResponse,
  RbacPolicyOverride,
  RbacOverrideCreateRequest,
  // Health
  HealthCheck,
  // Store
  StoreProduct,
  StoreProductsResponse,
  StoreOrder,
  CreateStoreOrderRequest,
  BackfillRevelTransactionRequest,
  BackfillRevelTransactionResponse,
  ReconciliationReport,
  GoogleOAuthRequest,
  GoogleOAuthResponse,
  GoogleOAuthStatus,
  CompleteOAuthPhoneRequest,
  SendVerificationOtpRequest,
  VerifyEmailOtpRequest,
  StopRecurringResponse,
  ContentPost,
  ContentPostsResponse,
  CreateContentPostRequest,
  UpdateContentPostRequest,
  SignedUploadRequest,
  SignedUploadResponse,
  ReelsFeedResponse,
  ReelCommentsResponse,
  ContentComment,
  StorePaymentConfig,
} from '../types';

// ==================== Auth API ====================
export const authApi = {
  /**
   * Register a new user
   */
  register: async (data: RegisterRequest): Promise<AuthResponse> => {
    const response = await getApiClient().post<AuthResponse>('/api/auth/register', data);
    return response.data;
  },

  /**
   * Login with email and password
   */
  login: async (data: LoginRequest): Promise<AuthResponse> => {
    const response = await getApiClient().post<AuthResponse>('/api/auth/login', data);
    return response.data;
  },

  /**
   * Lightweight email recognition for checkout (rate-limited).
   */
  lookupEmail: async (email: string): Promise<{ exists: boolean; needs_password: boolean }> => {
    const response = await getApiClient().post<{ exists: boolean; needs_password: boolean }>(
      '/api/auth/lookup-email',
      { email },
    );
    return response.data;
  },

  /**
   * Exchange Google Identity Services / Firebase ID token for app JWTs.
   * When phone is missing, returns needs_phone + setup_token (no access/refresh).
   */
  oauthGoogle: async (data: GoogleOAuthRequest): Promise<GoogleOAuthResponse> => {
    const response = await getApiClient().post<GoogleOAuthResponse>(
      '/api/auth/oauth/google',
      data
    );
    return response.data;
  },

  /**
   * Finish Google OAuth by attaching a phone using the short-lived setup_token.
   */
  completeOAuthPhone: async (
    data: CompleteOAuthPhoneRequest
  ): Promise<GoogleOAuthResponse> => {
    const response = await getApiClient().post<GoogleOAuthResponse>(
      '/api/auth/oauth/complete-phone',
      data
    );
    return response.data;
  },

  /**
   * Whether Continue with Google is available (env-gated).
   */
  oauthGoogleStatus: async (): Promise<GoogleOAuthStatus> => {
    const response = await getApiClient().get<GoogleOAuthStatus>('/api/auth/oauth/google/status');
    return response.data;
  },

  /**
   * Send email verification OTP after signup.
   */
  sendVerificationOtp: async (
    data: SendVerificationOtpRequest
  ): Promise<{ message: string; provider?: string }> => {
    const response = await getApiClient().post<{ message: string; provider?: string }>(
      '/api/auth/send-verification-otp',
      data
    );
    return response.data;
  },

  /**
   * Verify email with OTP code.
   */
  verifyEmailOtp: async (
    data: VerifyEmailOtpRequest
  ): Promise<{ message: string }> => {
    const response = await getApiClient().post<{ message: string }>(
      '/api/auth/verify-email-otp',
      data
    );
    return response.data;
  },

  /**
   * Refresh access token
   */
  refreshToken: async (refreshToken: string): Promise<AuthResponse> => {
    const response = await getApiClient().post<AuthResponse>('/api/auth/refresh', {
      refresh_token: refreshToken,
    });
    return response.data;
  },
};

// ==================== User API ====================
export const userApi = {
  /**
   * Get current user profile
   */
  getProfile: async (): Promise<User> => {
    const response = await getApiClient().get<User>('/api/me');
    return response.data;
  },

  /**
   * Update current user profile
   */
  updateProfile: async (data: UpdateProfileRequest): Promise<User> => {
    const response = await getApiClient().patch<User>('/api/me', data);
    return response.data;
  },

  /**
   * Get current user's bookings
   */
  getMyBookings: async (): Promise<Booking[]> => {
    const response = await getApiClient().get<Booking[]>('/api/me/bookings');
    return response.data;
  },

  /**
   * Practitioner profile for the current user (practitioner or admin with profile)
   */
  getMyPractitioner: async (): Promise<Practitioner> => {
    const response = await getApiClient().get<Practitioner>('/api/me/practitioner');
    return response.data;
  },

  /**
   * Get current user's notifications
   */
  getNotifications: async (unreadOnly = false): Promise<Notification[]> => {
    const response = await getApiClient().get<Notification[]>('/api/me/notifications', {
      params: { unread_only: unreadOnly },
    });
    return response.data;
  },

  /**
   * Mark notification as read
   */
  markNotificationRead: async (notificationId: string): Promise<void> => {
    await getApiClient().post(`/api/me/notifications/${notificationId}/read`);
  },

  /**
   * Mark all notifications as read
   */
  markAllNotificationsRead: async (): Promise<{ marked_count: number }> => {
    const response = await getApiClient().post<{ marked_count: number }>('/api/me/notifications/read-all');
    return response.data;
  },

  /**
   * Get discovery booking eligibility for current user
   */
  getDiscoveryEligibility: async (): Promise<DiscoveryEligibility> => {
    const response = await getApiClient().get<DiscoveryEligibility>('/api/me/discovery-eligibility');
    return response.data;
  },
};

// ==================== Services API ====================
export const servicesApi = {
  /**
   * Get all active services
   */
  getAll: async (category?: string): Promise<Service[]> => {
    const response = await getApiClient().get<Service[]>('/api/services', {
      params: category ? { category } : undefined,
    });
    return response.data;
  },

  /**
   * Get featured services
   */
  getFeatured: async (): Promise<Service[]> => {
    const response = await getApiClient().get<Service[]>('/api/services/featured');
    return response.data;
  },

  /**
   * Get service by ID
   */
  getById: async (serviceId: string): Promise<Service> => {
    const response = await getApiClient().get<Service>(`/api/services/${serviceId}`);
    return response.data;
  },

  /**
   * Reviews for a service (same data is embedded on getById; use for refresh-only flows).
   */
  getReviews: async (serviceId: string): Promise<ServiceReview[]> => {
    const response = await getApiClient().get<ServiceReview[]>(`/api/services/${serviceId}/reviews`);
    return response.data;
  },

  /**
   * Create new service (Admin only)
   */
  create: async (data: CreateServiceRequest): Promise<Service> => {
    const response = await getApiClient().post<Service>('/api/services', data);
    return response.data;
  },

  /**
   * Update service (Admin only)
   */
  update: async (serviceId: string, data: UpdateServiceRequest): Promise<Service> => {
    const response = await getApiClient().patch<Service>(`/api/services/${serviceId}`, data);
    return response.data;
  },

  /**
   * Delete/deactivate service (Admin only)
   */
  delete: async (serviceId: string): Promise<void> => {
    await getApiClient().delete(`/api/services/${serviceId}`);
  },

  /**
   * Sync services with REVEL POS (Admin only)
   */
  syncWithRevel: async (): Promise<{ synced: number; total_revel_products: number }> => {
    const response = await getApiClient().post('/api/services/sync-revel');
    return response.data;
  },
};

// ==================== Practitioners API ====================
export const practitionersApi = {
  /**
   * Get all practitioners
   */
  getAll: async (): Promise<Practitioner[]> => {
    const response = await getApiClient().get<Practitioner[]>('/api/practitioners');
    return response.data;
  },

  /**
   * Get featured practitioners
   */
  getFeatured: async (): Promise<Practitioner[]> => {
    const response = await getApiClient().get<Practitioner[]>('/api/practitioners/featured');
    return response.data;
  },

  /**
   * Get practitioners by service
   */
  getByService: async (serviceId: string): Promise<Practitioner[]> => {
    const response = await getApiClient().get<Practitioner[]>(`/api/practitioners/by-service/${serviceId}`);
    return response.data;
  },

  /**
   * Get practitioner by ID
   */
  getById: async (practitionerId: string): Promise<Practitioner> => {
    const response = await getApiClient().get<Practitioner>(`/api/practitioners/${practitionerId}`);
    return response.data;
  },

  /**
   * Get practitioner availability for a specific date
   */
  getAvailability: async (practitionerId: string, date: string): Promise<AvailabilitySlot[]> => {
    const response = await getApiClient().get<AvailabilitySlot[]>(
      `/api/practitioners/${practitionerId}/availability`,
      { params: { date } }
    );
    return response.data;
  },

  /**
   * Create practitioner profile (Admin only)
   */
  create: async (data: CreatePractitionerRequest): Promise<Practitioner> => {
    const response = await getApiClient().post<Practitioner>('/api/practitioners', data);
    return response.data;
  },

  /**
   * Update practitioner profile
   */
  update: async (practitionerId: string, data: UpdatePractitionerRequest): Promise<Practitioner> => {
    const response = await getApiClient().patch<Practitioner>(`/api/practitioners/${practitionerId}`, data);
    return response.data;
  },

  /**
   * Generate availability slots (Admin only)
   */
  generateSlots: async (
    practitionerId: string,
    data: GenerateSlotsRequest
  ): Promise<{ generated_slots: number }> => {
    const response = await getApiClient().post(`/api/practitioners/${practitionerId}/generate-slots`, data);
    return response.data;
  },
};

// ==================== Booking API ====================
export const bookingApi = {
  /**
   * Step 1: Initiate a booking (creates draft)
   */
  initiate: async (data: InitiateBookingRequest): Promise<Booking> => {
    const response = await getApiClient().post<Booking>('/api/booking/initiate', data);
    return response.data;
  },

  /**
   * Slot windows available for a service/date across all practitioners.
   */
  getServiceSlots: async (serviceId: string, date: string): Promise<ServiceSlotWindow[]> => {
    const response = await getApiClient().get<ServiceSlotWindow[]>('/api/booking/service-slots', {
      params: { service_id: serviceId, date },
    });
    return response.data;
  },

  /**
   * Step 2: Lock the time slot
   */
  lockSlot: async (bookingId: string): Promise<LockSlotResponse> => {
    const response = await getApiClient().post<LockSlotResponse>(
      '/api/booking/lock-slot',
      null,
      { params: { booking_id: bookingId } }
    );
    return response.data;
  },

  /**
   * Step 3: Confirm booking and process payment
   */
  confirm: async (data: ConfirmBookingRequest): Promise<BookingConfirmationResponse> => {
    const response = await getApiClient().post<BookingConfirmationResponse>('/api/booking/confirm', data);
    return response.data;
  },

  resendInvoice: async (bookingId: string): Promise<{ booking_id: string; status: string; reused_link: boolean; link_id?: string }> => {
    const response = await getApiClient().post<{ booking_id: string; status: string; reused_link: boolean; link_id?: string }>(
      `/api/booking/${bookingId}/invoice/resend`
    );
    return response.data;
  },

  getPaymentStatus: async (bookingId: string): Promise<BookingPaymentStatusResponse> => {
    const response = await getApiClient().get<BookingPaymentStatusResponse>(
      `/api/booking/${bookingId}/payment/status`
    );
    return response.data;
  },

  markPaidAtCounter: async (
    bookingId: string,
    data: MarkPaidAtCounterRequest
  ): Promise<Booking> => {
    const response = await getApiClient().post<Booking>(
      `/api/booking/${bookingId}/mark-paid-at-counter`,
      data
    );
    return response.data;
  },

  /**
   * Get booking by ID
   */
  getById: async (bookingId: string): Promise<Booking> => {
    const response = await getApiClient().get<Booking>(`/api/booking/${bookingId}`);
    return response.data;
  },

  /**
   * Cancel a booking
   */
  cancel: async (data: CancelBookingRequest): Promise<Booking> => {
    const response = await getApiClient().post<Booking>('/api/booking/cancel', data);
    return response.data;
  },

  /**
   * Reschedule (customer)
   */
  reschedule: async (data: RescheduleBookingRequest): Promise<Booking> => {
    const response = await getApiClient().post<Booking>(
      `/api/booking/${data.booking_id}/reschedule`,
      data
    );
    return response.data;
  },

  /**
   * Bookings for the authenticated practitioner in a date range
   */
  getPractitionerCalendar: async (
    startDate: string,
    endDate: string
  ): Promise<Booking[]> => {
    const response = await getApiClient().get<Booking[]>('/api/booking/practitioner/calendar', {
      params: { start_date: startDate, end_date: endDate },
    });
    return response.data;
  },

  /**
   * Mark session completed (practitioner assigned to booking or admin with profile)
   */
  completePractitionerSession: async (bookingId: string): Promise<Booking> => {
    const response = await getApiClient().post<Booking>(
      `/api/booking/practitioner/${bookingId}/complete`
    );
    return response.data;
  },

  /**
   * Mark Discovery Call done for the customer (unlocks non-discovery services).
   */
  completeDiscoveryAsPractitioner: async (
    bookingId: string
  ): Promise<DiscoveryEligibility> => {
    const response = await getApiClient().post<DiscoveryEligibility>(
      `/api/booking/practitioner/${bookingId}/complete-discovery`
    );
    return response.data;
  },

  /**
   * Admin: mark Discovery Call done for a customer.
   */
  completeDiscoveryAsAdmin: async (
    bookingId: string
  ): Promise<DiscoveryEligibility> => {
    const response = await getApiClient().post<DiscoveryEligibility>(
      `/api/booking/admin/${bookingId}/complete-discovery`
    );
    return response.data;
  },

  /**
   * Stop monthly recurrence and cancel future series members only.
   */
  stopRecurring: async (bookingId: string): Promise<StopRecurringResponse> => {
    const response = await getApiClient().post<StopRecurringResponse>(
      `/api/booking/${bookingId}/stop-recurring`
    );
    return response.data;
  },

  /**
   * Download multi-VEVENT .ics for a booking (Apple / iCloud path).
   */
  downloadIcal: async (bookingId: string): Promise<Blob> => {
    const response = await getApiClient().get<Blob>(`/api/booking/${bookingId}/ical`, {
      responseType: 'blob',
    });
    return response.data;
  },

  /**
   * Reschedule (practitioner acting for their client)
   */
  rescheduleAsPractitioner: async (data: RescheduleBookingRequest): Promise<Booking> => {
    const response = await getApiClient().post<Booking>(
      `/api/booking/practitioner/${data.booking_id}/reschedule`,
      data
    );
    return response.data;
  },

  // ===== Admin endpoints =====

  /**
   * Get all bookings (Admin only)
   */
  getAll: async (status?: string): Promise<Booking[]> => {
    const response = await getApiClient().get<Booking[]>('/api/booking/admin/all', {
      params: status ? { status } : undefined,
    });
    return response.data;
  },

  /**
   * Get bookings by date range (Admin only)
   */
  getByDateRange: async (
    startDate: string,
    endDate: string,
    practitionerId?: string
  ): Promise<Booking[]> => {
    const response = await getApiClient().get<Booking[]>('/api/booking/admin/by-date', {
      params: {
        start_date: startDate,
        end_date: endDate,
        ...(practitionerId && { practitioner_id: practitionerId }),
      },
    });
    return response.data;
  },

  /**
   * Admin cancel booking (Admin only)
   */
  adminCancel: async (bookingId: string, reason?: string): Promise<Booking> => {
    const response = await getApiClient().post<Booking>(
      `/api/booking/admin/cancel/${bookingId}`,
      null,
      { params: reason ? { reason } : undefined }
    );
    return response.data;
  },
};

// ==================== Admin API ====================
export const adminApi = {
  /**
   * Get dashboard statistics
   */
  getStats: async (): Promise<AdminStats> => {
    const response = await getApiClient().get<AdminStats>('/api/admin/stats');
    return response.data;
  },

  /**
   * Get booking analytics
   */
  getBookingAnalytics: async (period: 'day' | 'week' | 'month' = 'week'): Promise<BookingAnalytics> => {
    const response = await getApiClient().get<BookingAnalytics>('/api/admin/analytics/bookings', {
      params: { period },
    });
    return response.data;
  },

  getStoreFunnelAnalytics: async (days = 7): Promise<StoreFunnelAnalytics> => {
    const response = await getApiClient().get<StoreFunnelAnalytics>('/api/admin/analytics/store-funnel', {
      params: { days },
    });
    return response.data;
  },

  /**
   * Get all customers
   */
  getCustomers: async (): Promise<User[]> => {
    const response = await getApiClient().get<User[]>('/api/admin/customers');
    return response.data;
  },

  /**
   * Get all users
   */
  getUsers: async (): Promise<User[]> => {
    const response = await getApiClient().get<User[]>('/api/admin/users');
    return response.data;
  },

  /**
   * Update user role
   */
  updateUserRole: async (userId: string, role: string): Promise<void> => {
    await getApiClient().patch(`/api/admin/users/${userId}/role`, null, {
      params: { role },
    });
  },

  /**
   * Update user status
   */
  updateUserStatus: async (userId: string, isActive: boolean): Promise<void> => {
    await getApiClient().patch(`/api/admin/users/${userId}/status`, null, {
      params: { is_active: isActive },
    });
  },

  getRbacBaseline: async (): Promise<RbacBaselineResponse> => {
    const response = await getApiClient().get<RbacBaselineResponse>('/api/admin/rbac/baseline');
    return response.data;
  },

  listRbacOverrides: async (): Promise<RbacPolicyOverride[]> => {
    const response = await getApiClient().get<RbacPolicyOverride[]>('/api/admin/rbac/overrides');
    return response.data;
  },

  createRbacOverride: async (body: RbacOverrideCreateRequest): Promise<RbacPolicyOverride> => {
    const response = await getApiClient().post<RbacPolicyOverride>('/api/admin/rbac/overrides', body);
    return response.data;
  },

  deleteRbacOverride: async (docId: string): Promise<void> => {
    await getApiClient().delete(`/api/admin/rbac/overrides/${docId}`);
  },

  reloadRbacPolicies: async (): Promise<{ reloaded: boolean }> => {
    const response = await getApiClient().post<{ reloaded: boolean }>('/api/admin/rbac/reload');
    return response.data;
  },

  listReconciliationReports: async (date?: string): Promise<{ items: ReconciliationReport[]; total: number }> => {
    const response = await getApiClient().get<{ items: ReconciliationReport[]; total: number }>(
      '/api/admin/reconciliation/reports',
      { params: date ? { date } : undefined }
    );
    return response.data;
  },

  resolveReconciliationReport: async (
    reportId: string,
    note?: string
  ): Promise<{ report_id: string; resolved: boolean; resolved_at: string }> => {
    const response = await getApiClient().post<{ report_id: string; resolved: boolean; resolved_at: string }>(
      `/api/admin/reconciliation/reports/${reportId}/resolve`,
      note ? { note } : {}
    );
    return response.data;
  },
};

// ==================== Health API ====================
export const healthApi = {
  /**
   * Check API health
   */
  check: async (): Promise<HealthCheck> => {
    const response = await getApiClient().get<HealthCheck>('/api/health');
    return response.data;
  },
};

// ==================== Store API ====================
export const storeApi = {
  getProducts: async (params?: {
    q?: string;
    category?: string;
    page?: number;
    page_size?: number;
  }): Promise<StoreProductsResponse> => {
    // Backend Query allows page_size le=75; clamp so callers never get 422.
    const safe = params ? { ...params } : undefined;
    if (safe?.page_size != null) {
      safe.page_size = Math.min(Math.max(1, safe.page_size), 75);
    }
    const response = await getApiClient().get<StoreProductsResponse>('/api/store/products', {
      params: safe,
    });
    return response.data;
  },

  getCategories: async (): Promise<{
    items: Array<{ slug: string; label: string; total: number }>;
  }> => {
    const response = await getApiClient().get<{
      items: Array<{ slug: string; label: string; total: number }>;
    }>('/api/store/categories');
    return response.data;
  },

  getAdminProducts: async (params?: {
    q?: string;
    category?: string;
    page?: number;
    page_size?: number;
    include_inactive?: boolean;
  }): Promise<StoreProductsResponse> => {
    const safe = params ? { ...params } : undefined;
    if (safe?.page_size != null) {
      safe.page_size = Math.min(Math.max(1, safe.page_size), 75);
    }
    const response = await getApiClient().get<StoreProductsResponse>('/api/store/admin/products', {
      params: safe,
    });
    return response.data;
  },

  getProductsByIds: async (productIds: string[]): Promise<{ items: StoreProduct[] }> => {
    const response = await getApiClient().post<{ items: StoreProduct[] }>('/api/store/products/by-ids', {
      product_ids: productIds,
    });
    return response.data;
  },

  syncRevelProducts: async (): Promise<{ success: boolean; synced: number }> => {
    const response = await getApiClient().post<{ success: boolean; synced: number }>(
      '/api/store/admin/sync-revel-products'
    );
    return response.data;
  },

  updateProduct: async (
    productId: string,
    data: Partial<StoreProduct>
  ): Promise<StoreProduct> => {
    const response = await getApiClient().patch<StoreProduct>(
      `/api/store/admin/products/${productId}`,
      data
    );
    return response.data;
  },

  createOrder: async (data: CreateStoreOrderRequest): Promise<StoreOrder> => {
    const response = await getApiClient().post<StoreOrder>('/api/store/checkout/orders', data);
    return response.data;
  },

  payOrder: async (
    orderId: string,
    paymentMethod: 'card' | 'wallet' | 'manual' = 'card',
    actionToken?: string
  ): Promise<StoreOrder> => {
    const response = await getApiClient().post<StoreOrder>(
      `/api/store/checkout/orders/${orderId}/pay`,
      null,
      { params: { payment_method: paymentMethod, ...(actionToken ? { action_token: actionToken } : {}) } }
    );
    return response.data;
  },

  resendSms: async (orderId: string, actionToken?: string): Promise<StoreOrder | { success?: boolean }> => {
    const response = await getApiClient().post<StoreOrder | { success?: boolean }>(
      `/api/store/checkout/orders/${orderId}/resend-sms`,
      null,
      { params: actionToken ? { action_token: actionToken } : undefined }
    );
    return response.data;
  },

  getOrder: async (orderId: string): Promise<StoreOrder> => {
    const response = await getApiClient().get<StoreOrder>(`/api/store/orders/${orderId}`);
    return response.data;
  },

  getOrderStatus: async (orderId: string, actionToken?: string): Promise<StoreOrder> => {
    const response = await getApiClient().get<StoreOrder>(`/api/store/orders/${orderId}/status`, {
      params: actionToken ? { action_token: actionToken } : undefined,
    });
    return response.data;
  },

  getPaymentConfig: async (): Promise<StorePaymentConfig> => {
    const response = await getApiClient().get<StorePaymentConfig>('/api/store/payment-config');
    return response.data;
  },

  getMyOrders: async (): Promise<StoreOrder[]> => {
    const response = await getApiClient().get<StoreOrder[]>('/api/store/orders/mine');
    return response.data;
  },

  getPractitionerOrders: async (status?: string): Promise<StoreOrder[]> => {
    const response = await getApiClient().get<StoreOrder[]>('/api/store/practitioner/orders', {
      params: status ? { status_filter: status } : undefined,
    });
    return response.data;
  },

  confirmOrder: async (orderId: string, reason?: string): Promise<StoreOrder> => {
    const response = await getApiClient().post<StoreOrder>(`/api/store/admin/orders/${orderId}/confirm`, {
      reason,
    });
    return response.data;
  },

  fulfillOrder: async (orderId: string, reason?: string): Promise<StoreOrder> => {
    const response = await getApiClient().post<StoreOrder>(`/api/store/admin/orders/${orderId}/fulfill`, {
      reason,
    });
    return response.data;
  },

  rejectOrder: async (orderId: string, reason: string): Promise<StoreOrder> => {
    const response = await getApiClient().post<StoreOrder>(`/api/store/admin/orders/${orderId}/reject`, {
      reason,
    });
    return response.data;
  },

  refundOrder: async (
    orderId: string,
    amount?: number,
    idempotencyKey?: string
  ): Promise<StoreOrder> => {
    const key =
      idempotencyKey ||
      `refund-${orderId}-${amount ?? 'full'}-${Math.random().toString(36).slice(2, 10)}`;
    const response = await getApiClient().post<StoreOrder>(
      `/api/store/admin/orders/${orderId}/refund`,
      { amount },
      { headers: { 'Idempotency-Key': key } }
    );
    return response.data;
  },

  sendInvoice: async (orderId: string): Promise<StoreOrder> => {
    const response = await getApiClient().post<StoreOrder>(`/api/store/admin/orders/${orderId}/invoice`);
    return response.data;
  },

  voidOrder: async (orderId: string): Promise<StoreOrder> => {
    const response = await getApiClient().post<StoreOrder>(`/api/store/admin/orders/${orderId}/void`);
    return response.data;
  },

  backfillRevelTransaction: async (
    orderId: string,
    data: BackfillRevelTransactionRequest
  ): Promise<BackfillRevelTransactionResponse> => {
    const response = await getApiClient().post<BackfillRevelTransactionResponse>(
      `/api/store/admin/orders/${orderId}/backfill-revel-tx`,
      data
    );
    return response.data;
  },
};

export const clientsApi = {
  list: async (q?: string): Promise<ClientListResponse> => {
    const response = await getApiClient().get<ClientListResponse>('/api/clients', {
      params: q ? { q } : undefined,
    });
    return response.data;
  },
  getById: async (clientId: string): Promise<ClientDetailResponse> => {
    const response = await getApiClient().get<ClientDetailResponse>(`/api/clients/${clientId}`);
    return response.data;
  },
};

// ==================== Content / Reels API ====================
export const contentApi = {
  getLatest: async (limit = 5): Promise<ContentPost[] | ContentPostsResponse> => {
    const response = await getApiClient().get<ContentPost[] | ContentPostsResponse>(
      '/api/content/posts/latest',
      { params: { limit } }
    );
    return response.data;
  },

  listPosts: async (params?: {
    type?: string;
    limit?: number;
  }): Promise<ContentPost[] | ContentPostsResponse> => {
    const response = await getApiClient().get<ContentPost[] | ContentPostsResponse>(
      '/api/content/posts',
      { params }
    );
    return response.data;
  },

  getBySlug: async (slug: string): Promise<ContentPost> => {
    const response = await getApiClient().get<ContentPost>(
      `/api/content/posts/${encodeURIComponent(slug)}`
    );
    return response.data;
  },

  getById: async (postId: string): Promise<ContentPost> => {
    const response = await getApiClient().get<ContentPost>(
      `/api/content/posts/id/${encodeURIComponent(postId)}`
    );
    return response.data;
  },

  adminList: async (params?: {
    type?: string;
    status?: string;
  }): Promise<ContentPost[] | ContentPostsResponse> => {
    const response = await getApiClient().get<ContentPost[] | ContentPostsResponse>(
      '/api/content/admin/posts',
      { params }
    );
    return response.data;
  },

  adminCreate: async (data: CreateContentPostRequest): Promise<ContentPost> => {
    const response = await getApiClient().post<ContentPost>('/api/content/admin/posts', data);
    return response.data;
  },

  adminUpdate: async (
    postId: string,
    data: UpdateContentPostRequest
  ): Promise<ContentPost> => {
    const response = await getApiClient().patch<ContentPost>(
      `/api/content/admin/posts/${encodeURIComponent(postId)}`,
      data
    );
    return response.data;
  },

  adminDelete: async (postId: string): Promise<void> => {
    await getApiClient().delete(`/api/content/admin/posts/${encodeURIComponent(postId)}`);
  },

  /**
   * Signed GCS PUT URL when GCS_BUCKET is configured.
   * public_url uses CDN_BASE_URL when set; otherwise a signed GET URL (PAP-safe).
   * Never anonymous storage.googleapis.com.
   */
  adminSignUpload: async (data: SignedUploadRequest): Promise<SignedUploadResponse> => {
    const response = await getApiClient().post<SignedUploadResponse>(
      '/api/content/admin/uploads/sign',
      data
    );
    return response.data;
  },

  getReelsFeed: async (limit = 30): Promise<ReelsFeedResponse> => {
    const response = await getApiClient().get<ReelsFeedResponse>('/api/content/reels', {
      params: { limit },
    });
    return response.data;
  },

  markReelSeen: async (postId: string): Promise<{ success: boolean; post_id: string }> => {
    const response = await getApiClient().post<{ success: boolean; post_id: string }>(
      `/api/content/reels/${encodeURIComponent(postId)}/seen`
    );
    return response.data;
  },

  likeReel: async (
    postId: string
  ): Promise<{ success: boolean; liked: boolean; like_count: number }> => {
    const response = await getApiClient().post<{
      success: boolean;
      liked: boolean;
      like_count: number;
    }>(`/api/content/reels/${encodeURIComponent(postId)}/like`);
    return response.data;
  },

  unlikeReel: async (
    postId: string
  ): Promise<{ success: boolean; liked: boolean; like_count: number }> => {
    const response = await getApiClient().delete<{
      success: boolean;
      liked: boolean;
      like_count: number;
    }>(`/api/content/reels/${encodeURIComponent(postId)}/like`);
    return response.data;
  },

  getReelComments: async (postId: string): Promise<ReelCommentsResponse> => {
    const response = await getApiClient().get<ReelCommentsResponse>(
      `/api/content/reels/${encodeURIComponent(postId)}/comments`
    );
    return response.data;
  },

  addReelComment: async (postId: string, body: string): Promise<ContentComment> => {
    const response = await getApiClient().post<ContentComment>(
      `/api/content/reels/${encodeURIComponent(postId)}/comments`,
      { body }
    );
    return response.data;
  },
};
