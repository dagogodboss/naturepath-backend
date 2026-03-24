/**
 * @natural-path/sdk - Admin Hooks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '../api/endpoints';
import { queryKeys } from './queryKeys';
import type { UserRole } from '../types';

/**
 * Hook to fetch admin dashboard statistics
 * 
 * @example
 * ```tsx
 * const { data: stats } = useAdminStats();
 * console.log(stats?.total_bookings, stats?.revenue_today);
 * ```
 */
export function useAdminStats() {
  return useQuery({
    queryKey: queryKeys.admin.stats,
    queryFn: () => adminApi.getStats(),
    staleTime: 1 * 60 * 1000, // 1 minute
    refetchInterval: 5 * 60 * 1000, // Refetch every 5 minutes
  });
}

/**
 * Hook to fetch booking analytics
 * 
 * @example
 * ```tsx
 * const { data: weeklyAnalytics } = useBookingAnalytics('week');
 * const { data: monthlyAnalytics } = useBookingAnalytics('month');
 * ```
 */
export function useBookingAnalytics(period: 'day' | 'week' | 'month' = 'week') {
  return useQuery({
    queryKey: queryKeys.admin.analytics(period),
    queryFn: () => adminApi.getBookingAnalytics(period),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to fetch all customers
 * 
 * @example
 * ```tsx
 * const { data: customers } = useCustomers();
 * ```
 */
export function useCustomers() {
  return useQuery({
    queryKey: queryKeys.admin.customers,
    queryFn: () => adminApi.getCustomers(),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to fetch all users
 * 
 * @example
 * ```tsx
 * const { data: users } = useUsers();
 * ```
 */
export function useUsers() {
  return useQuery({
    queryKey: queryKeys.admin.users,
    queryFn: () => adminApi.getUsers(),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to update user role
 * 
 * @example
 * ```tsx
 * const { mutate: updateRole } = useUpdateUserRole();
 * updateRole({ userId: 'user-id', role: 'practitioner' });
 * ```
 */
export function useUpdateUserRole() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: UserRole }) =>
      adminApi.updateUserRole(userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.users });
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.customers });
    },
  });
}

/**
 * Hook to update user status (activate/deactivate)
 * 
 * @example
 * ```tsx
 * const { mutate: updateStatus } = useUpdateUserStatus();
 * updateStatus({ userId: 'user-id', isActive: false });
 * ```
 */
export function useUpdateUserStatus() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ userId, isActive }: { userId: string; isActive: boolean }) =>
      adminApi.updateUserStatus(userId, isActive),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.users });
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.customers });
    },
  });
}
