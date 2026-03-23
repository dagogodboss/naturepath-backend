/**
 * @natural-path/sdk - Authentication Hook
 * 
 * Complete auth state management with JWT handling
 */

import { useState, useCallback, useEffect, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { authApi, userApi } from '../api/endpoints';
import { getTokenStorage } from '../api/client';
import { queryKeys } from './queryKeys';
import type { User, LoginRequest, RegisterRequest, AuthResponse } from '../types';

export interface UseAuthResult {
  // User state
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  
  // Auth methods
  login: (data: LoginRequest) => Promise<AuthResponse>;
  register: (data: RegisterRequest) => Promise<AuthResponse>;
  logout: () => void;
  refreshToken: () => Promise<string | null>;
  
  // Error state
  error: Error | null;
}

/**
 * Authentication hook with complete JWT management
 * 
 * @example
 * ```tsx
 * const { user, isAuthenticated, login, logout } = useAuth();
 * 
 * // Login
 * await login({ email: 'user@example.com', password: 'password' });
 * 
 * // Check auth state
 * if (isAuthenticated) {
 *   console.log('Welcome', user?.first_name);
 * }
 * 
 * // Logout
 * logout();
 * ```
 */
export function useAuth(): UseAuthResult {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const queryClient = useQueryClient();

  // Check if user is authenticated
  const isAuthenticated = useMemo(() => !!user, [user]);

  // Load user on mount if token exists
  useEffect(() => {
    const loadUser = async () => {
      try {
        const storage = getTokenStorage();
        const token = storage.getAccessToken();
        
        if (token) {
          const profile = await userApi.getProfile();
          setUser(profile);
          queryClient.setQueryData(queryKeys.user.profile, profile);
        }
      } catch (err) {
        // Token might be expired
        console.warn('[NaturalPath SDK] Failed to load user:', err);
        const storage = getTokenStorage();
        storage.clearTokens();
      } finally {
        setIsLoading(false);
      }
    };

    loadUser();
  }, [queryClient]);

  // Login function
  const login = useCallback(async (data: LoginRequest): Promise<AuthResponse> => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await authApi.login(data);
      const storage = getTokenStorage();
      
      // Store tokens
      storage.setTokens(response.access_token, response.refresh_token);
      
      // Fetch full user profile
      const profile = await userApi.getProfile();
      setUser(profile);
      queryClient.setQueryData(queryKeys.user.profile, profile);
      
      return response;
    } catch (err) {
      setError(err as Error);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [queryClient]);

  // Register function
  const register = useCallback(async (data: RegisterRequest): Promise<AuthResponse> => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await authApi.register(data);
      const storage = getTokenStorage();
      
      // Store tokens
      storage.setTokens(response.access_token, response.refresh_token);
      
      // Fetch full user profile
      const profile = await userApi.getProfile();
      setUser(profile);
      queryClient.setQueryData(queryKeys.user.profile, profile);
      
      return response;
    } catch (err) {
      setError(err as Error);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [queryClient]);

  // Logout function
  const logout = useCallback(() => {
    const storage = getTokenStorage();
    storage.clearTokens();
    setUser(null);
    setError(null);
    
    // Clear all cached data
    queryClient.clear();
  }, [queryClient]);

  // Refresh token function
  const refreshToken = useCallback(async (): Promise<string | null> => {
    try {
      const storage = getTokenStorage();
      const currentRefreshToken = storage.getRefreshToken();
      
      if (!currentRefreshToken) {
        return null;
      }

      const response = await authApi.refreshToken(currentRefreshToken);
      storage.setTokens(response.access_token, response.refresh_token);
      
      return response.access_token;
    } catch (err) {
      console.error('[NaturalPath SDK] Token refresh failed:', err);
      logout();
      return null;
    }
  }, [logout]);

  return {
    user,
    isAuthenticated,
    isLoading,
    login,
    register,
    logout,
    refreshToken,
    error,
  };
}

/**
 * Hook to get just the current user (lighter weight than useAuth)
 * 
 * @example
 * ```tsx
 * const user = useCurrentUser();
 * ```
 */
export function useCurrentUser(): User | null {
  const { user } = useAuth();
  return user;
}

/**
 * Hook to check if user is authenticated
 * 
 * @example
 * ```tsx
 * const isAuthenticated = useIsAuthenticated();
 * ```
 */
export function useIsAuthenticated(): boolean {
  const { isAuthenticated } = useAuth();
  return isAuthenticated;
}
