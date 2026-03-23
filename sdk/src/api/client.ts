/**
 * @natural-path/sdk - API Client
 * 
 * Axios-based HTTP client with automatic JWT handling
 */

import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { ApiError } from '../types';

export interface NaturalPathConfig {
  baseUrl: string;
  onTokenRefresh?: () => Promise<string | null>;
  onAuthError?: (error: ApiError) => void;
}

export interface TokenStorage {
  getAccessToken: () => string | null;
  getRefreshToken: () => string | null;
  setTokens: (access: string, refresh: string) => void;
  clearTokens: () => void;
}

let globalConfig: NaturalPathConfig | null = null;
let tokenStorage: TokenStorage | null = null;

/**
 * Initialize the SDK with configuration
 */
export function initializeSDK(config: NaturalPathConfig, storage: TokenStorage): void {
  globalConfig = config;
  tokenStorage = storage;
}

/**
 * Get the current configuration
 */
export function getConfig(): NaturalPathConfig {
  if (!globalConfig) {
    throw new Error(
      '@natural-path/sdk: SDK not initialized. Call initializeSDK() or wrap your app with NaturalPathProvider.'
    );
  }
  return globalConfig;
}

/**
 * Get token storage
 */
export function getTokenStorage(): TokenStorage {
  if (!tokenStorage) {
    throw new Error(
      '@natural-path/sdk: Token storage not initialized. Call initializeSDK() or wrap your app with NaturalPathProvider.'
    );
  }
  return tokenStorage;
}

/**
 * Create configured Axios instance
 */
export function createApiClient(): AxiosInstance {
  const config = getConfig();
  const storage = getTokenStorage();

  const client = axios.create({
    baseURL: config.baseUrl,
    headers: {
      'Content-Type': 'application/json',
    },
    timeout: 30000,
  });

  // Request interceptor - attach JWT token
  client.interceptors.request.use(
    (requestConfig: InternalAxiosRequestConfig) => {
      const token = storage.getAccessToken();
      if (token && requestConfig.headers) {
        requestConfig.headers.Authorization = `Bearer ${token}`;
      }
      return requestConfig;
    },
    (error) => Promise.reject(error)
  );

  // Response interceptor - handle errors and token refresh
  client.interceptors.response.use(
    (response) => response,
    async (error: AxiosError<ApiError>) => {
      const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

      // Handle 401 Unauthorized
      if (error.response?.status === 401 && !originalRequest._retry) {
        originalRequest._retry = true;

        // Try to refresh token
        if (config.onTokenRefresh) {
          try {
            const newToken = await config.onTokenRefresh();
            if (newToken && originalRequest.headers) {
              originalRequest.headers.Authorization = `Bearer ${newToken}`;
              return client(originalRequest);
            }
          } catch (refreshError) {
            // Token refresh failed
            storage.clearTokens();
            if (config.onAuthError) {
              config.onAuthError({ detail: 'Session expired. Please login again.' });
            }
          }
        } else {
          storage.clearTokens();
          if (config.onAuthError) {
            config.onAuthError({ detail: 'Authentication required.' });
          }
        }
      }

      // Transform error response
      const apiError: ApiError = {
        detail: error.response?.data?.detail || error.message || 'An unexpected error occurred',
        status_code: error.response?.status,
      };

      return Promise.reject(apiError);
    }
  );

  return client;
}

// Singleton instance
let apiClientInstance: AxiosInstance | null = null;

/**
 * Get or create API client instance
 */
export function getApiClient(): AxiosInstance {
  if (!apiClientInstance) {
    apiClientInstance = createApiClient();
  }
  return apiClientInstance;
}

/**
 * Reset API client (useful for testing or reconfiguration)
 */
export function resetApiClient(): void {
  apiClientInstance = null;
}
