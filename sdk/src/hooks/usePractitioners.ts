/**
 * @natural-path/sdk - Practitioner Hooks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { practitionersApi } from '../api/endpoints';
import { queryKeys } from './queryKeys';
import type {
  CreatePractitionerRequest,
  UpdatePractitionerRequest,
} from '../types';

/**
 * Hook to fetch all practitioners
 * 
 * @example
 * ```tsx
 * const { data: practitioners, isLoading } = usePractitioners();
 * ```
 */
export function usePractitioners() {
  return useQuery({
    queryKey: queryKeys.practitioners.all,
    queryFn: () => practitionersApi.getAll(),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to fetch featured practitioners
 * 
 * @example
 * ```tsx
 * const { data: featuredPractitioners } = useFeaturedPractitioners();
 * ```
 */
export function useFeaturedPractitioners() {
  return useQuery({
    queryKey: queryKeys.practitioners.featured,
    queryFn: () => practitionersApi.getFeatured(),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to fetch practitioners by service
 * 
 * @example
 * ```tsx
 * const { data: practitioners } = usePractitionersByService('service-id');
 * ```
 */
export function usePractitionersByService(serviceId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.practitioners.byService(serviceId || ''),
    queryFn: () => practitionersApi.getByService(serviceId!),
    enabled: !!serviceId,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to fetch a single practitioner by ID
 * 
 * @example
 * ```tsx
 * const { data: practitioner } = usePractitioner('practitioner-id');
 * ```
 */
export function usePractitioner(practitionerId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.practitioners.detail(practitionerId || ''),
    queryFn: () => practitionersApi.getById(practitionerId!),
    enabled: !!practitionerId,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to fetch practitioner availability for a specific date
 * 
 * @example
 * ```tsx
 * const { data: slots } = useAvailability('practitioner-id', '2026-03-25');
 * ```
 */
export function useAvailability(
  practitionerId: string | undefined,
  date: string | undefined
) {
  return useQuery({
    queryKey: queryKeys.practitioners.availability(practitionerId || '', date || ''),
    queryFn: () => practitionersApi.getAvailability(practitionerId!, date!),
    enabled: !!practitionerId && !!date,
    staleTime: 1 * 60 * 1000, // 1 minute - availability changes more frequently
    refetchInterval: 30 * 1000, // Refetch every 30 seconds
  });
}

/**
 * Hook to create a practitioner profile (Admin only)
 * 
 * @example
 * ```tsx
 * const { mutate: createPractitioner } = useCreatePractitioner();
 * createPractitioner({ user_id: 'user-id', bio: '...' });
 * ```
 */
export function useCreatePractitioner() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreatePractitionerRequest) => practitionersApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.practitioners.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.practitioners.featured });
    },
  });
}

/**
 * Hook to update a practitioner profile
 * 
 * @example
 * ```tsx
 * const { mutate: updatePractitioner } = useUpdatePractitioner();
 * updatePractitioner({ practitionerId: 'id', data: { bio: 'New bio' } });
 * ```
 */
export function useUpdatePractitioner() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      practitionerId,
      data,
    }: {
      practitionerId: string;
      data: UpdatePractitionerRequest;
    }) => practitionersApi.update(practitionerId, data),
    onSuccess: (updatedPractitioner) => {
      queryClient.setQueryData(
        queryKeys.practitioners.detail(updatedPractitioner.practitioner_id),
        updatedPractitioner
      );
      queryClient.setQueryData(queryKeys.user.myPractitioner, updatedPractitioner);
      queryClient.invalidateQueries({ queryKey: queryKeys.practitioners.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.practitioners.featured });
    },
  });
}

/**
 * Hook to generate availability slots (Admin only)
 * 
 * @example
 * ```tsx
 * const { mutate: generateSlots } = useGenerateSlots();
 * generateSlots({
 *   practitionerId: 'id',
 *   data: { start_date: '2026-03-25', end_date: '2026-03-31' }
 * });
 * ```
 */
export function useGenerateSlots() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      practitionerId,
      data,
    }: {
      practitionerId: string;
      data: { start_date: string; end_date: string; start_hour?: number; end_hour?: number };
    }) => practitionersApi.generateSlots(practitionerId, data),
    onSuccess: (_, { practitionerId }) => {
      queryClient.invalidateQueries({
        predicate: (query) =>
          query.queryKey[0] === 'practitioners' &&
          query.queryKey[1] === 'availability' &&
          query.queryKey[2] === practitionerId,
      });
      queryClient.invalidateQueries({
        predicate: (q) =>
          q.queryKey[0] === 'bookings' && q.queryKey[1] === 'practitionerCalendar',
      });
    },
  });
}
