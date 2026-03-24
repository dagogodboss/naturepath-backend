/**
 * @natural-path/sdk
 * 
 * React TypeScript SDK for The Natural Path Spa Management System
 * 
 * @example
 * ```tsx
 * import { NaturalPathProvider, useServices, useBookingFlow } from '@natural-path/sdk';
 * 
 * function App() {
 *   return (
 *     <NaturalPathProvider baseUrl="https://api.thenaturalpath.com">
 *       <BookingPage />
 *     </NaturalPathProvider>
 *   );
 * }
 * 
 * function BookingPage() {
 *   const { data: services } = useServices();
 *   const { initiateBooking, lockSlot, confirmBooking } = useBookingFlow();
 *   // ...
 * }
 * ```
 */

// ==================== Provider ====================
export {
  NaturalPathProvider,
  useNaturalPath,
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from './providers';
export type { NaturalPathProviderProps, NaturalPathContextValue } from './providers';

// ==================== Types ====================
export type {
  // Enums
  UserRole,
  BookingStatus,
  PaymentStatus,
  SlotStatus,
  ServiceCategory,
  NotificationType,
  // User
  User,
  RegisterRequest,
  LoginRequest,
  AuthResponse,
  UpdateProfileRequest,
  // Practitioner
  Practitioner,
  PractitionerSpecialty,
  PractitionerAvailability,
  CreatePractitionerRequest,
  UpdatePractitionerRequest,
  // Service
  Service,
  CreateServiceRequest,
  UpdateServiceRequest,
  // Availability
  AvailabilitySlot,
  GenerateSlotsRequest,
  // Booking
  Booking,
  BookingSlot,
  InitiateBookingRequest,
  LockSlotResponse,
  ConfirmBookingRequest,
  CancelBookingRequest,
  RescheduleBookingRequest,
  BookingConfirmationResponse,
  // Payment
  Payment,
  RevelOrder,
  // Notification
  Notification,
  // Admin
  AdminStats,
  BookingInsight,
  BookingAnalytics,
  // API
  ApiError,
  HealthCheck,
  // WebSocket
  WebSocketMessage,
  AvailabilityUpdate,
  SlotLockedEvent,
  SlotReleasedEvent,
} from './types';

// ==================== Hooks ====================
export {
  // Query Keys
  queryKeys,
  // Auth
  useAuth,
  useCurrentUser,
  useIsAuthenticated,
  // Services
  useServices,
  useFeaturedServices,
  useService,
  useCreateService,
  useUpdateService,
  useDeleteService,
  useSyncServicesWithRevel,
  // Practitioners
  usePractitioners,
  useFeaturedPractitioners,
  usePractitionersByService,
  usePractitioner,
  useAvailability,
  useCreatePractitioner,
  useUpdatePractitioner,
  useGenerateSlots,
  // Bookings
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
  // User
  useProfile,
  useMyPractitioner,
  useUpdateProfile,
  useNotifications,
  useMarkNotificationRead,
  useMarkAllNotificationsRead,
  // Admin
  useAdminStats,
  useBookingAnalytics,
  useCustomers,
  useUsers,
  useUpdateUserRole,
  useUpdateUserStatus,
  // WebSocket
  useRealtimeAvailability,
  useRealtimeNotifications,
  useWebSocket,
  // Health
  useHealthCheck,
} from './hooks';

// ==================== API (for advanced usage) ====================
export {
  authApi,
  userApi,
  servicesApi,
  practitionersApi,
  bookingApi,
  adminApi,
  healthApi,
} from './api/endpoints';

export {
  initializeSDK,
  getConfig,
  getApiClient,
  resetApiClient,
} from './api/client';

export type { NaturalPathConfig, TokenStorage } from './api/client';

// ==================== WebSocket (for advanced usage) ====================
export {
  NaturalPathWebSocket,
  createWebSocket,
} from './websocket';

export type { WebSocketConfig, WebSocketEventType, WebSocketEventHandler } from './websocket/manager';

// ==================== Utilities ====================
export {
  formatDate,
  formatTime,
  parseDate,
  getDayOfWeek,
  addDays,
  getWeekRange,
  getMonthRange,
  formatCurrency,
  formatDuration,
  isToday,
  isPastDate,
  generateTimeSlots,
  sleep,
  debounce,
} from './utils';
