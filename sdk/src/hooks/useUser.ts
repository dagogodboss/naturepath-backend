/**
 * @natural-path/sdk - User & Profile Hooks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { userApi } from '../api/endpoints';
import { queryKeys } from './queryKeys';
import type { User, UpdateProfileRequest, Notification } from '../types';

/**
 * Hook to fetch current user profile
 * 
 * @example
 * ```tsx
 * const { data: profile } = useProfile();
 * ```
 */
export function useProfile() {
  return useQuery({
    queryKey: queryKeys.user.profile,
    queryFn: () => userApi.getProfile(),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to update current user profile
 * 
 * @example
 * ```tsx
 * const { mutate: updateProfile } = useUpdateProfile();
 * updateProfile({ first_name: 'John', phone: '+1234567890' });
 * ```
 */
export function useUpdateProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: UpdateProfileRequest) => userApi.updateProfile(data),
    onSuccess: (updatedUser) => {
      queryClient.setQueryData(queryKeys.user.profile, updatedUser);
    },
  });
}

/**
 * Hook to fetch user notifications
 * 
 * @example
 * ```tsx
 * const { data: notifications } = useNotifications();
 * const { data: unreadNotifications } = useNotifications(true);
 * ```
 */
export function useNotifications(unreadOnly = false) {
  return useQuery({
    queryKey: queryKeys.user.notifications(unreadOnly),
    queryFn: () => userApi.getNotifications(unreadOnly),
    staleTime: 30 * 1000, // 30 seconds
    refetchInterval: 60 * 1000, // Refetch every minute
  });
}

/**
 * Hook to mark a notification as read
 * 
 * @example
 * ```tsx
 * const { mutate: markAsRead } = useMarkNotificationRead();
 * markAsRead('notification-id');
 * ```
 */
export function useMarkNotificationRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (notificationId: string) => userApi.markNotificationRead(notificationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user', 'notifications'] });
    },
  });
}

/**
 * Hook to mark all notifications as read
 * 
 * @example
 * ```tsx
 * const { mutate: markAllAsRead } = useMarkAllNotificationsRead();
 * markAllAsRead();
 * ```
 */
export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => userApi.markAllNotificationsRead(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user', 'notifications'] });
    },
  });
}
