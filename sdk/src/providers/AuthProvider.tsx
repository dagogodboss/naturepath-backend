/**
 * Shared auth state for the entire app. A single useAuth() instance avoids
 * per-component user state (which made logout appear broken).
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  ReactNode,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { authApi, userApi } from '../api/endpoints';
import { getTokenStorage, resetApiClient } from '../api/client';
import { queryKeys } from '../hooks/queryKeys';
import type { User, LoginRequest, RegisterRequest, AuthResponse } from '../types';

export interface UseAuthResult {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (data: LoginRequest) => Promise<AuthResponse>;
  register: (data: RegisterRequest) => Promise<AuthResponse>;
  logout: () => void;
  refreshToken: () => Promise<string | null>;
  error: Error | null;
}

const AuthContext = createContext<UseAuthResult | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const queryClient = useQueryClient();

  const isAuthenticated = useMemo(() => !!user, [user]);

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
        console.warn('[NaturalPath SDK] Failed to load user:', err);
        const storage = getTokenStorage();
        storage.clearTokens();
      } finally {
        setIsLoading(false);
      }
    };

    loadUser();
  }, [queryClient]);

  const login = useCallback(
    async (data: LoginRequest): Promise<AuthResponse> => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await authApi.login(data);
        const storage = getTokenStorage();
        storage.setTokens(response.access_token, response.refresh_token);

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
    },
    [queryClient]
  );

  const register = useCallback(
    async (data: RegisterRequest): Promise<AuthResponse> => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await authApi.register(data);
        const storage = getTokenStorage();
        storage.setTokens(response.access_token, response.refresh_token);

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
    },
    [queryClient]
  );

  const logout = useCallback(() => {
    const storage = getTokenStorage();
    storage.clearTokens();
    setUser(null);
    setError(null);
    resetApiClient();
    queryClient.clear();
  }, [queryClient]);

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
      const storage = getTokenStorage();
      storage.clearTokens();
      setUser(null);
      setError(null);
      resetApiClient();
      queryClient.clear();
      return null;
    }
  }, [queryClient]);

  const value = useMemo(
    () => ({
      user,
      isAuthenticated,
      isLoading,
      login,
      register,
      logout,
      refreshToken,
      error,
    }),
    [user, isAuthenticated, isLoading, login, register, logout, refreshToken, error]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): UseAuthResult {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error(
      'useAuth must be used within NaturalPathProvider (AuthProvider is included there).'
    );
  }
  return ctx;
}

export function useCurrentUser(): User | null {
  const { user } = useAuth();
  return user;
}

export function useIsAuthenticated(): boolean {
  const { isAuthenticated } = useAuth();
  return isAuthenticated;
}
