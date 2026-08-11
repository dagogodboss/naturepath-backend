/**
 * natural-path-sdk - API Client
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
      'natural-path-sdk: SDK not initialized. Call initializeSDK() or wrap your app with NaturalPathProvider.'
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
      'natural-path-sdk: Token storage not initialized. Call initializeSDK() or wrap your app with NaturalPathProvider.'
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

  // Request interceptor - attach JWT token (+ standalone PWA hint)
  client.interceptors.request.use(
    (requestConfig: InternalAxiosRequestConfig) => {
      const token = storage.getAccessToken();
      if (token && requestConfig.headers) {
        requestConfig.headers.Authorization = `Bearer ${token}`;
      }
      if (typeof window !== 'undefined' && requestConfig.headers) {
        const standalone =
          window.matchMedia?.('(display-mode: standalone)')?.matches ||
          // iOS Safari installed PWA
          (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
        if (standalone) {
          requestConfig.headers['X-Client-Mode'] = 'standalone';
        }
      }
      return requestConfig;
    },
    (error) => Promise.reject(error)
  );

  /**
   * H3: when the backend returns a 2xx body of shape
   * `{status: "pending_verification", check_url}`, poll the check_url for up
   * to POLL_MAX_MS (default 30s) before surfacing the response to the caller.
   */
  client.interceptors.response.use(async (response) => {
    const body: any = response?.data;
    if (
      body &&
      typeof body === 'object' &&
      body.status === 'pending_verification' &&
      typeof body.check_url === 'string'
    ) {
      const POLL_INTERVAL_MS = 2000;
      const POLL_MAX_MS = 30_000;
      const started = Date.now();
      while (Date.now() - started < POLL_MAX_MS) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        try {
          const statusResp = await client.get(body.check_url);
          const statusBody: any = statusResp?.data;
          if (
            statusBody &&
            statusBody.status !== 'pending_verification' &&
            statusBody.payment_status !== 'pending' &&
            statusBody.payment_status !== 'processing'
          ) {
            return statusResp;
          }
        } catch {
          // swallow transient errors and keep polling
        }
      }
      // Timed out — return the original pending-verification response.
    }
    return response;
  },
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
