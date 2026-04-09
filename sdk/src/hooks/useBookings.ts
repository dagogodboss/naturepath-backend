/**
 * natural-path-sdk - Booking Hooks
 * 
 * Complete booking flow support with multi-step mutations
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { bookingApi, userApi } from '../api/endpoints';
import { queryKeys } from './queryKeys';
import type {
  Booking,
  InitiateBookingRequest,
  ConfirmBookingRequest,
  CancelBookingRequest,
  BookingStatus,
} from '../types';

/**
 * Hook to fetch user's bookings
 * 
 * @example
 * ```tsx
 * const { data: bookings } = useUserBookings();
 * ```
 */
export function useUserBookings() {
  return useQuery({
    queryKey: queryKeys.bookings.mine,
    queryFn: () => userApi.getMyBookings(),
    staleTime: 1 * 60 * 1000,
  });
}

/**
 * Practitioner calendar: bookings assigned to the current practitioner in a date range.
 */
export function usePractitionerCalendar(
  startDate: string | undefined,
  endDate: string | undefined,
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.bookings.practitionerCalendar(startDate || '', endDate || ''),
    queryFn: () => bookingApi.getPractitionerCalendar(startDate!, endDate!),
    enabled: enabled && !!startDate && !!endDate,
    staleTime: 30 * 1000,
  });
}

export function useServiceAvailability(
  serviceId: string | undefined,
  date: string | undefined,
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.bookings.serviceSlots(serviceId || '', date || ''),
    queryFn: () => bookingApi.getServiceSlots(serviceId!, date!),
    enabled: enabled && !!serviceId && !!date,
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000,
  });
}

/**
 * Mark a practitioner's booking session as completed (confirmed or in progress).
 */
export function useCompletePractitionerSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (bookingId: string) => bookingApi.completePractitionerSession(bookingId),
    onSuccess: (booking) => {
      queryClient.setQueryData(queryKeys.bookings.detail(booking.booking_id), booking);
      queryClient.invalidateQueries({
        predicate: (q) =>
          Array.isArray(q.queryKey) &&
          q.queryKey[0] === 'bookings' &&
          q.queryKey[1] === 'practitionerCalendar',
      });
    },
  });
}

/**
 * Hook to fetch a single booking by ID
 * 
 * @example
 * ```tsx
 * const { data: booking } = useBooking('booking-id');
 * ```
 */
export function useBooking(bookingId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.bookings.detail(bookingId || ''),
    queryFn: () => bookingApi.getById(bookingId!),
    enabled: !!bookingId,
    staleTime: 30 * 1000,
  });
}

/**
 * Hook to create/initiate a new booking (Step 1)
 * 
 * @example
 * ```tsx
 * const { mutate: createBooking, data: booking } = useCreateBooking();
 * createBooking({
 *   service_id: 'service-id',
 *   practitioner_id: 'practitioner-id',
 *   slot: { date: '2026-03-25', start_time: '10:00', end_time: '11:00' }
 * });
 * ```
 */
export function useCreateBooking() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: InitiateBookingRequest) => bookingApi.initiate(data),
    onSuccess: (newBooking) => {
      queryClient.setQueryData(queryKeys.bookings.detail(newBooking.booking_id), newBooking);
    },
  });
}

/**
 * Hook to lock a booking slot (Step 2)
 * 
 * @example
 * ```tsx
 * const { mutate: lockSlot } = useLockSlot();
 * lockSlot('booking-id');
 * ```
 */
export function useLockSlot() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (bookingId: string) => bookingApi.lockSlot(bookingId),
    onSuccess: (_, bookingId) => {
      // Update the booking status in cache
      queryClient.setQueryData(queryKeys.bookings.detail(bookingId), (old: Booking | undefined) => {
        if (!old) return old;
        return { ...old, status: 'pending' as BookingStatus };
      });
      
      // Invalidate availability
      queryClient.invalidateQueries({
        predicate: (query) =>
          (query.queryKey[0] === 'practitioners' && query.queryKey[1] === 'availability') ||
          (query.queryKey[0] === 'bookings' && query.queryKey[1] === 'serviceSlots'),
      });
    },
  });
}

/**
 * Hook to confirm a booking and process payment (Step 3)
 * 
 * @example
 * ```tsx
 * const { mutate: confirmBooking } = useConfirmBooking();
 * confirmBooking({ booking_id: 'booking-id', payment_method: 'card' });
 * ```
 */
export function useConfirmBooking() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ConfirmBookingRequest) => bookingApi.confirm(data),
    onSuccess: (confirmedBooking) => {
      // Update booking in cache
      queryClient.setQueryData(
        queryKeys.bookings.detail(confirmedBooking.booking_id),
        confirmedBooking
      );
      
      // Invalidate bookings list
      queryClient.invalidateQueries({ queryKey: queryKeys.bookings.mine });
      queryClient.invalidateQueries({ queryKey: queryKeys.bookings.all });
      
      // Invalidate availability
      queryClient.invalidateQueries({
        predicate: (query) =>
          (query.queryKey[0] === 'practitioners' && query.queryKey[1] === 'availability') ||
          (query.queryKey[0] === 'bookings' && query.queryKey[1] === 'serviceSlots'),
      });
    },
  });
}

/**
 * Hook to cancel a booking
 * 
 * @example
 * ```tsx
 * const { mutate: cancelBooking } = useCancelBooking();
 * cancelBooking({ booking_id: 'booking-id', reason: 'Schedule conflict' });
 * ```
 */
export function useCancelBooking() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CancelBookingRequest) => bookingApi.cancel(data),
    onSuccess: (cancelledBooking) => {
      // Update booking in cache
      queryClient.setQueryData(
        queryKeys.bookings.detail(cancelledBooking.booking_id),
        cancelledBooking
      );
      
      // Invalidate lists
      queryClient.invalidateQueries({ queryKey: queryKeys.bookings.mine });
      queryClient.invalidateQueries({ queryKey: queryKeys.bookings.all });
      
      // Invalidate availability (slot becomes available again)
      queryClient.invalidateQueries({
        predicate: (query) =>
          (query.queryKey[0] === 'practitioners' && query.queryKey[1] === 'availability') ||
          (query.queryKey[0] === 'bookings' && query.queryKey[1] === 'serviceSlots'),
      });
    },
  });
}

/**
 * Complete booking flow hook - combines all three steps
 * 
 * @example
 * ```tsx
 * const { initiateBooking, lockSlot, confirmBooking, currentStep, bookingId } = useBookingFlow();
 * 
 * // Step 1: Initiate
 * await initiateBooking({ service_id, practitioner_id, slot });
 * 
 * // Step 2: Lock
 * await lockSlot();
 * 
 * // Step 3: Confirm
 * await confirmBooking({ payment_method: 'card' });
 * ```
 */
export function useBookingFlow() {
  const queryClient = useQueryClient();

  const initiateMutation = useMutation({
    mutationFn: (data: InitiateBookingRequest) => bookingApi.initiate(data),
    onSuccess: (booking) => {
      queryClient.setQueryData(queryKeys.bookings.detail(booking.booking_id), booking);
    },
  });

  const lockMutation = useMutation({
    mutationFn: (bookingId: string) => bookingApi.lockSlot(bookingId),
    onSuccess: (_, bookingId) => {
      queryClient.setQueryData(queryKeys.bookings.detail(bookingId), (old: Booking | undefined) => {
        if (!old) return old;
        return { ...old, status: 'pending' as BookingStatus };
      });
    },
  });

  const confirmMutation = useMutation({
    mutationFn: (data: ConfirmBookingRequest) => bookingApi.confirm(data),
    onSuccess: (booking) => {
      queryClient.setQueryData(queryKeys.bookings.detail(booking.booking_id), booking);
      queryClient.invalidateQueries({ queryKey: queryKeys.bookings.mine });
      queryClient.invalidateQueries({
        predicate: (query) =>
          (query.queryKey[0] === 'practitioners' && query.queryKey[1] === 'availability') ||
          (query.queryKey[0] === 'bookings' && query.queryKey[1] === 'serviceSlots'),
      });
    },
  });

  // Get current booking ID from the initiate mutation
  const bookingId = initiateMutation.data?.booking_id;

  // Determine current step
  let currentStep: 'idle' | 'initiated' | 'locked' | 'confirmed' | 'error' = 'idle';
  if (confirmMutation.isSuccess) {
    currentStep = 'confirmed';
  } else if (lockMutation.isSuccess) {
    currentStep = 'locked';
  } else if (initiateMutation.isSuccess) {
    currentStep = 'initiated';
  }
  if (initiateMutation.isError || lockMutation.isError || confirmMutation.isError) {
    currentStep = 'error';
  }

  return {
    // Mutations
    initiateBooking: initiateMutation.mutateAsync,
    lockSlot: (overrideBookingId?: string) => {
      const id = overrideBookingId ?? bookingId;
      if (!id) throw new Error('No booking initiated');
      return lockMutation.mutateAsync(id);
    },
    confirmBooking: (paymentMethod?: string, overrideBookingId?: string) => {
      const id = overrideBookingId ?? bookingId;
      if (!id) throw new Error('No booking initiated');
      return confirmMutation.mutateAsync({ booking_id: id, payment_method: paymentMethod });
    },

    // State
    currentStep,
    bookingId,
    booking: initiateMutation.data,
    lockResponse: lockMutation.data,
    confirmationResponse: confirmMutation.data,

    // Loading states
    isInitiating: initiateMutation.isPending,
    isLocking: lockMutation.isPending,
    isConfirming: confirmMutation.isPending,
    isLoading: initiateMutation.isPending || lockMutation.isPending || confirmMutation.isPending,

    // Error states
    initiateError: initiateMutation.error,
    lockError: lockMutation.error,
    confirmError: confirmMutation.error,
    error: initiateMutation.error || lockMutation.error || confirmMutation.error,

    // Reset the flow
    reset: () => {
      initiateMutation.reset();
      lockMutation.reset();
      confirmMutation.reset();
    },
  };
}

// ==================== Admin Booking Hooks ====================

/**
 * Hook to fetch all bookings (Admin only)
 */
export function useAllBookings(status?: BookingStatus) {
  return useQuery({
    queryKey: status ? queryKeys.bookings.byStatus(status) : queryKeys.bookings.all,
    queryFn: () => bookingApi.getAll(status),
    staleTime: 1 * 60 * 1000,
  });
}

/**
 * Hook to fetch bookings by date range (Admin only)
 */
export function useBookingsByDateRange(
  startDate: string | undefined,
  endDate: string | undefined,
  practitionerId?: string
) {
  return useQuery({
    queryKey: queryKeys.bookings.byDateRange(startDate || '', endDate || '', practitionerId),
    queryFn: () => bookingApi.getByDateRange(startDate!, endDate!, practitionerId),
    enabled: !!startDate && !!endDate,
    staleTime: 1 * 60 * 1000,
  });
}

/**
 * Hook to admin cancel a booking (Admin only)
 */
export function useAdminCancelBooking() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ bookingId, reason }: { bookingId: string; reason?: string }) =>
      bookingApi.adminCancel(bookingId, reason),
    onSuccess: (cancelledBooking) => {
      queryClient.setQueryData(
        queryKeys.bookings.detail(cancelledBooking.booking_id),
        cancelledBooking
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.bookings.all });
    },
  });
}
