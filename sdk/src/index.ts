/**
 * natural-path-sdk
 * 
 * React TypeScript SDK for The Natural Path Spa Management System
 * 
 * @example
 * ```tsx
 * import { NaturalPathProvider, useServices, useBookingFlow } from 'natural-path-sdk';
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

// Re-export common react-query hooks so apps can import from one package
// and avoid dual @tanstack/react-query copies when the SDK is linked locally.
export {
  useQuery,
  useMutation,
  useInfiniteQuery,
  keepPreviousData,
} from '@tanstack/react-query';

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
  DiscoveryEligibility,
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
  ServiceReview,
  CreateServiceRequest,
  UpdateServiceRequest,
  // Availability
  AvailabilitySlot,
  GenerateSlotsRequest,
  // Booking
  Booking,
  BookingSlot,
  BookingPaymentStatusResponse,
  MarkPaidAtCounterRequest,
  InitiateBookingRequest,
  ServiceSlotWindow,
  LockSlotResponse,
  ConfirmBookingRequest,
  CancelBookingRequest,
  RescheduleBookingRequest,
  BookingConfirmationResponse,
  ClientListItem,
  ClientListResponse,
  ClientDetailAppointment,
  ClientDetailResponse,
  // Store
  StorePaymentMethod,
  StorePaymentMode,
  StorePaymentState,
  StoreFulfillmentState,
  StoreProduct,
  StoreAddress,
  StoreOrderItem,
  CreateStoreOrderRequest,
  StoreOrder,
  StoreProductsResponse,
  BackfillRevelTransactionRequest,
  BackfillRevelTransactionResponse,
  StorePaymentConfig,
  // Content / Reels
  ContentType,
  ContentStatus,
  ContentPost,
  ReelItem,
  ContentComment,
  ContentPostsResponse,
  ReelsFeedResponse,
  ReelCommentsResponse,
  CreateContentPostRequest,
  UpdateContentPostRequest,
  SignedUploadRequest,
  SignedUploadResponse,
  // Auth extras
  LookupEmailRequest,
  LookupEmailResponse,
  GoogleOAuthRequest,
  GoogleOAuthResponse,
  GoogleOAuthStatus,
  CompleteOAuthPhoneRequest,
  SendVerificationOtpRequest,
  VerifyEmailOtpRequest,
  BookingRecurrence,
  StopRecurringResponse,
  // Payment
  Payment,
  RevelOrder,
  // Notification
  Notification,
  // Admin
  AdminStats,
  BookingInsight,
  BookingAnalytics,
  StoreFunnelAnalytics,
  RbacBaselineResponse,
  RbacPolicyOverride,
  RbacOverrideCreateRequest,
  ReconciliationReport,
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
  useBookingPaymentStatus,
  useResendBookingInvoice,
  useMarkBookingPaidAtCounter,
  useAllBookings,
  useBookingsByDateRange,
  useAdminCancelBooking,
  usePractitionerCalendar,
  useServiceAvailability,
  useCompletePractitionerSession,
  useCompleteDiscoveryAsPractitioner,
  useStopRecurring,
  // User
  useProfile,
  useDiscoveryEligibility,
  useMyPractitioner,
  useUpdateProfile,
  useNotifications,
  useMarkNotificationRead,
  useMarkAllNotificationsRead,
  // Admin
  useAdminStats,
  useBookingAnalytics,
  useStoreFunnelAnalytics,
  useCustomers,
  useUsers,
  useUpdateUserRole,
  useUpdateUserStatus,
  useRbacBaseline,
  useRbacOverrides,
  useCreateRbacOverride,
  useDeleteRbacOverride,
  useReloadRbacPolicies,
  useReconciliationReports,
  useResolveReconciliationReport,
  // WebSocket
  useRealtimeAvailability,
  useRealtimeNotifications,
  useWebSocket,
  // Health
  useHealthCheck,
  // Store
  useStoreProducts,
  useStoreOrder,
  useStoreOrderStatus,
  useMyStoreOrders,
  usePractitionerStoreOrders,
  useSyncStoreProducts,
  useUpdateStoreProduct,
  useCreateStoreOrder,
  usePayStoreOrder,
  useStoreOrderOps,
  // Content / Reels
  useReelsFeed,
  useContentPosts,
  useContentPostById,
  useMarkReelSeen,
  useLikeReel,
  useUnlikeReel,
  useReelComments,
  useAddReelComment,
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
  storeApi,
  clientsApi,
  contentApi,
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
  buildNotificationsEndpoint,
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
  formatMoney,
  formatDuration,
  isToday,
  isPastDate,
  generateTimeSlots,
  sleep,
  debounce,
  discoveryState,
  discoveryMessagingKey,
  discoveryBannerCopy,
  isDiscoveryUnlocked,
  previewMediaSrc,
  reelPreviewSrc,
  embedIframeSrc,
  buildCalendarLinks,
  linksFromBooking,
  downloadBookingIcal,
} from './utils';

export type {
  DiscoveryState,
  DiscoveryMessagingKey,
  CalendarLinkInput,
  CalendarLinks,
} from './utils';
