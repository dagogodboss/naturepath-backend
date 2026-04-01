/**
 * @natural-path/sdk - Query Keys
 * 
 * Centralized query keys for React Query cache management
 */

export const queryKeys = {
  // Services
  services: {
    all: ['services'] as const,
    featured: ['services', 'featured'] as const,
    byCategory: (category: string) => ['services', 'category', category] as const,
    detail: (id: string) => ['services', 'detail', id] as const,
  },

  // Practitioners
  practitioners: {
    all: ['practitioners'] as const,
    featured: ['practitioners', 'featured'] as const,
    byService: (serviceId: string) => ['practitioners', 'service', serviceId] as const,
    detail: (id: string) => ['practitioners', 'detail', id] as const,
    availability: (practitionerId: string, date: string) =>
      ['practitioners', 'availability', practitionerId, date] as const,
  },

  // Bookings
  bookings: {
    all: ['bookings'] as const,
    mine: ['bookings', 'mine'] as const,
    detail: (id: string) => ['bookings', 'detail', id] as const,
    byStatus: (status: string) => ['bookings', 'status', status] as const,
    byDateRange: (start: string, end: string, practitionerId?: string) =>
      ['bookings', 'dateRange', start, end, practitionerId] as const,
    serviceSlots: (serviceId: string, date: string) =>
      ['bookings', 'serviceSlots', serviceId, date] as const,
    practitionerCalendar: (start: string, end: string) =>
      ['bookings', 'practitionerCalendar', start, end] as const,
  },

  // User
  user: {
    profile: ['user', 'profile'] as const,
    myPractitioner: ['user', 'myPractitioner'] as const,
    discoveryEligibility: ['user', 'discoveryEligibility'] as const,
    notifications: (unreadOnly?: boolean) => ['user', 'notifications', unreadOnly] as const,
  },

  // Admin
  admin: {
    stats: ['admin', 'stats'] as const,
    analytics: (period: string) => ['admin', 'analytics', period] as const,
    storeFunnel: (days: number) => ['admin', 'analytics', 'store-funnel', days] as const,
    customers: ['admin', 'customers'] as const,
    users: ['admin', 'users'] as const,
    rbacBaseline: ['admin', 'rbac', 'baseline'] as const,
    rbacOverrides: ['admin', 'rbac', 'overrides'] as const,
  },

  // Health
  health: ['health'] as const,

  // Store / Commerce
  store: {
    products: (params?: string) => ['store', 'products', params || 'default'] as const,
    myOrders: ['store', 'orders', 'mine'] as const,
    orderDetail: (orderId: string) => ['store', 'orders', orderId] as const,
    practitionerOrders: (status?: string) =>
      ['store', 'practitioner', 'orders', status || 'all'] as const,
  },
} as const;

export type QueryKeys = typeof queryKeys;
