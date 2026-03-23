/**
 * @natural-path/sdk - Health Check Hook
 */

import { useQuery } from '@tanstack/react-query';
import { healthApi } from '../api/endpoints';
import { queryKeys } from './queryKeys';

/**
 * Hook to check API health status
 * 
 * @example
 * ```tsx
 * const { data: health, isLoading, error } = useHealthCheck();
 * 
 * if (health?.status === 'healthy') {
 *   console.log('API is up!');
 * }
 * ```
 */
export function useHealthCheck() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => healthApi.check(),
    staleTime: 30 * 1000, // 30 seconds
    retry: 3,
    retryDelay: 1000,
  });
}
