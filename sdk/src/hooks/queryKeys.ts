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
  },

  // User
  user: {
    profile: ['user', 'profile'] as const,
    notifications: (unreadOnly?: boolean) => ['user', 'notifications', unreadOnly] as const,
  },

  // Admin
  admin: {
    stats: ['admin', 'stats'] as const,
    analytics: (period: string) => ['admin', 'analytics', period] as const,
    customers: ['admin', 'customers'] as const,
    users: ['admin', 'users'] as const,
  },

  // Health
  health: ['health'] as const,
} as const;

export type QueryKeys = typeof queryKeys;
