/**
 * @natural-path/sdk - API Endpoints
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
  BookingConfirmationResponse,
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
    data: Omit<GenerateSlotsRequest, 'practitioner_id'>
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
    // Backend Query allows page_size le=48; clamp so callers never get 422.
    const safe = params ? { ...params } : undefined;
    if (safe?.page_size != null) {
      safe.page_size = Math.min(Math.max(1, safe.page_size), 48);
    }
    const response = await getApiClient().get<StoreProductsResponse>('/api/store/products', {
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

  sendSmsPayLink: async (
    orderId: string,
    actionToken?: string
  ): Promise<{ success: boolean; order_id: string; payment_link_url: string }> => {
    const response = await getApiClient().post<{
      success: boolean;
      order_id: string;
      payment_link_url: string;
    }>(`/api/store/checkout/orders/${orderId}/sms-pay-link`, null, {
      params: actionToken ? { action_token: actionToken } : undefined,
    });
    return response.data;
  },

  getOrder: async (orderId: string): Promise<StoreOrder> => {
    const response = await getApiClient().get<StoreOrder>(`/api/store/orders/${orderId}`);
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

  refundOrder: async (orderId: string, amount?: number): Promise<StoreOrder> => {
    const response = await getApiClient().post<StoreOrder>(`/api/store/admin/orders/${orderId}/refund`, {
      amount,
    });
    return response.data;
  },

  sendInvoice: async (orderId: string): Promise<StoreOrder> => {
    const response = await getApiClient().post<StoreOrder>(`/api/store/admin/orders/${orderId}/invoice`);
    return response.data;
  },
};
