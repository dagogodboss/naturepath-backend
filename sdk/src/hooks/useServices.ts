/**
 * @natural-path/sdk - Service Hooks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { servicesApi } from '../api/endpoints';
import { queryKeys } from './queryKeys';
import type {
  Service,
  CreateServiceRequest,
  UpdateServiceRequest,
  ServiceCategory,
} from '../types';

/**
 * Hook to fetch all services
 * 
 * @example
 * ```tsx
 * const { data: services, isLoading } = useServices();
 * ```
 */
export function useServices(category?: ServiceCategory) {
  return useQuery({
    queryKey: category ? queryKeys.services.byCategory(category) : queryKeys.services.all,
    queryFn: () => servicesApi.getAll(category),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Hook to fetch featured services
 * 
 * @example
 * ```tsx
 * const { data: featuredServices } = useFeaturedServices();
 * ```
 */
export function useFeaturedServices() {
  return useQuery({
    queryKey: queryKeys.services.featured,
    queryFn: () => servicesApi.getFeatured(),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to fetch a single service by ID
 * 
 * @example
 * ```tsx
 * const { data: service } = useService('service-id');
 * ```
 */
export function useService(serviceId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.services.detail(serviceId || ''),
    queryFn: () => servicesApi.getById(serviceId!),
    enabled: !!serviceId,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to create a new service (Admin only)
 * 
 * @example
 * ```tsx
 * const { mutate: createService, isPending } = useCreateService();
 * createService({ name: 'New Service', ... });
 * ```
 */
export function useCreateService() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateServiceRequest) => servicesApi.create(data),
    onSuccess: () => {
      // Invalidate services cache
      queryClient.invalidateQueries({ queryKey: queryKeys.services.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.services.featured });
    },
  });
}

/**
 * Hook to update a service (Admin only)
 * 
 * @example
 * ```tsx
 * const { mutate: updateService } = useUpdateService();
 * updateService({ serviceId: 'id', data: { price: 150 } });
 * ```
 */
export function useUpdateService() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ serviceId, data }: { serviceId: string; data: UpdateServiceRequest }) =>
      servicesApi.update(serviceId, data),
    onSuccess: (updatedService) => {
      // Update cache
      queryClient.setQueryData(
        queryKeys.services.detail(updatedService.service_id),
        updatedService
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.services.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.services.featured });
    },
  });
}

/**
 * Hook to delete/deactivate a service (Admin only)
 * 
 * @example
 * ```tsx
 * const { mutate: deleteService } = useDeleteService();
 * deleteService('service-id');
 * ```
 */
export function useDeleteService() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (serviceId: string) => servicesApi.delete(serviceId),
    onSuccess: (_, serviceId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.services.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.services.featured });
      queryClient.invalidateQueries({ queryKey: queryKeys.services.detail(serviceId) });
    },
  });
}

/**
 * Hook to sync services with REVEL POS (Admin only)
 */
export function useSyncServicesWithRevel() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => servicesApi.syncWithRevel(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.services.all });
    },
  });
}
