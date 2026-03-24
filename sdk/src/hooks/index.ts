/**
 * @natural-path/sdk - Hooks Module
 */

// Query Keys
export { queryKeys } from './queryKeys';

// Auth Hooks
export { useAuth, useCurrentUser, useIsAuthenticated } from './useAuth';

// Service Hooks
export {
  useServices,
  useFeaturedServices,
  useService,
  useCreateService,
  useUpdateService,
  useDeleteService,
  useSyncServicesWithRevel,
} from './useServices';

// Practitioner Hooks
export {
  usePractitioners,
  useFeaturedPractitioners,
  usePractitionersByService,
  usePractitioner,
  useAvailability,
  useCreatePractitioner,
  useUpdatePractitioner,
  useGenerateSlots,
} from './usePractitioners';

// Booking Hooks
export {
  useUserBookings,
  useBooking,
  useCreateBooking,
  useLockSlot,
  useConfirmBooking,
  useCancelBooking,
  useBookingFlow,
  useAllBookings,
  useBookingsByDateRange,
  useAdminCancelBooking,
  usePractitionerCalendar,
} from './useBookings';

// User Hooks
export {
  useProfile,
  useMyPractitioner,
  useUpdateProfile,
  useNotifications,
  useMarkNotificationRead,
  useMarkAllNotificationsRead,
} from './useUser';

// Admin Hooks
export {
  useAdminStats,
  useBookingAnalytics,
  useCustomers,
  useUsers,
  useUpdateUserRole,
  useUpdateUserStatus,
} from './useAdmin';

// WebSocket Hooks
export {
  useRealtimeAvailability,
  useRealtimeNotifications,
  useWebSocket,
} from './useWebSocket';

// Health Hook
export { useHealthCheck } from './useHealth';
