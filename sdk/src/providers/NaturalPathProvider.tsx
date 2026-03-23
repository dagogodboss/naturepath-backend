/**
 * @natural-path/sdk - React Provider
 * 
 * Main provider component that initializes the SDK
 */

import React, { createContext, useContext, useEffect, useMemo, useState, ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { initializeSDK, TokenStorage, NaturalPathConfig, resetApiClient } from '../api/client';
import { authApi } from '../api/endpoints';

// ==================== Types ====================

export interface NaturalPathProviderProps {
  /**
   * API base URL (e.g., 'https://api.thenaturalpath.com')
   */
  baseUrl: string;
  
  /**
   * Custom QueryClient instance (optional)
   */
  queryClient?: QueryClient;
  
  /**
   * Custom token storage (optional, defaults to localStorage)
   */
  tokenStorage?: TokenStorage;
  
  /**
   * Callback when authentication error occurs
   */
  onAuthError?: (error: { detail: string }) => void;
  
  /**
   * Children components
   */
  children: ReactNode;
}

export interface NaturalPathContextValue {
  baseUrl: string;
  isInitialized: boolean;
}

// ==================== Context ====================

const NaturalPathContext = createContext<NaturalPathContextValue | null>(null);

// ==================== Default Token Storage ====================

const createDefaultTokenStorage = (): TokenStorage => {
  const ACCESS_TOKEN_KEY = 'natural_path_access_token';
  const REFRESH_TOKEN_KEY = 'natural_path_refresh_token';

  // Check if we're in a browser environment
  const isBrowser = typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';

  return {
    getAccessToken: () => {
      if (!isBrowser) return null;
      return localStorage.getItem(ACCESS_TOKEN_KEY);
    },
    getRefreshToken: () => {
      if (!isBrowser) return null;
      return localStorage.getItem(REFRESH_TOKEN_KEY);
    },
    setTokens: (access: string, refresh: string) => {
      if (!isBrowser) return;
      localStorage.setItem(ACCESS_TOKEN_KEY, access);
      localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
    },
    clearTokens: () => {
      if (!isBrowser) return;
      localStorage.removeItem(ACCESS_TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
    },
  };
};

// ==================== Default Query Client ====================

const createDefaultQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 60 * 1000, // 5 minutes
        retry: 3,
        retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: 1,
      },
    },
  });

// ==================== Provider Component ====================

/**
 * NaturalPathProvider - Initialize and configure the SDK
 * 
 * @example
 * ```tsx
 * import { NaturalPathProvider } from '@natural-path/sdk';
 * 
 * function App() {
 *   return (
 *     <NaturalPathProvider
 *       baseUrl="https://api.thenaturalpath.com"
 *       onAuthError={(error) => {
 *         console.error('Auth error:', error);
 *         // Redirect to login
 *       }}
 *     >
 *       <YourApp />
 *     </NaturalPathProvider>
 *   );
 * }
 * ```
 */
export function NaturalPathProvider({
  baseUrl,
  queryClient: customQueryClient,
  tokenStorage: customTokenStorage,
  onAuthError,
  children,
}: NaturalPathProviderProps) {
  const [isInitialized, setIsInitialized] = useState(false);

  // Create or use provided instances
  const tokenStorage = useMemo(
    () => customTokenStorage || createDefaultTokenStorage(),
    [customTokenStorage]
  );

  const queryClient = useMemo(
    () => customQueryClient || createDefaultQueryClient(),
    [customQueryClient]
  );

  // Initialize SDK
  useEffect(() => {
    const config: NaturalPathConfig = {
      baseUrl,
      onTokenRefresh: async () => {
        const refreshToken = tokenStorage.getRefreshToken();
        if (!refreshToken) return null;
        
        try {
          const response = await authApi.refreshToken(refreshToken);
          tokenStorage.setTokens(response.access_token, response.refresh_token);
          return response.access_token;
        } catch (error) {
          tokenStorage.clearTokens();
          return null;
        }
      },
      onAuthError,
    };

    initializeSDK(config, tokenStorage);
    setIsInitialized(true);

    // Cleanup on unmount
    return () => {
      resetApiClient();
    };
  }, [baseUrl, tokenStorage, onAuthError]);

  // Context value
  const contextValue = useMemo(
    () => ({ baseUrl, isInitialized }),
    [baseUrl, isInitialized]
  );

  if (!isInitialized) {
    return null; // Or a loading spinner
  }

  return (
    <NaturalPathContext.Provider value={contextValue}>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </NaturalPathContext.Provider>
  );
}

// ==================== Hook to access context ====================

/**
 * Hook to access NaturalPath SDK context
 * 
 * @example
 * ```tsx
 * const { baseUrl, isInitialized } = useNaturalPath();
 * ```
 */
export function useNaturalPath(): NaturalPathContextValue {
  const context = useContext(NaturalPathContext);
  
  if (!context) {
    throw new Error(
      'useNaturalPath must be used within a NaturalPathProvider. ' +
      'Make sure you have wrapped your app with <NaturalPathProvider>.'
    );
  }
  
  return context;
}

// ==================== Re-export QueryClient for advanced usage ====================

export { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
