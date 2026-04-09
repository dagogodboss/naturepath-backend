/**
 * natural-path-sdk - WebSocket Hooks
 * 
 * Real-time availability and notification hooks
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { NaturalPathWebSocket, createWebSocket } from '../websocket/manager';
import { getConfig } from '../api/client';
import { queryKeys } from './queryKeys';
import type {
  AvailabilitySlot,
  AvailabilityUpdate,
  SlotLockedEvent,
  SlotReleasedEvent,
} from '../types';

export interface UseRealtimeAvailabilityResult {
  slots: AvailabilitySlot[];
  isConnected: boolean;
  lastUpdate: Date | null;
  error: Error | null;
}

/**
 * Hook for real-time availability updates via WebSocket
 * 
 * @example
 * ```tsx
 * const { slots, isConnected, lastUpdate } = useRealtimeAvailability(
 *   'practitioner-id',
 *   '2026-03-25'
 * );
 * 
 * // Slots automatically update when changes occur
 * return (
 *   <div>
 *     {slots.map(slot => (
 *       <TimeSlot key={slot.slot_id} slot={slot} />
 *     ))}
 *   </div>
 * );
 * ```
 */
export function useRealtimeAvailability(
  practitionerId: string | undefined,
  date: string | undefined
): UseRealtimeAvailabilityResult {
  const [slots, setSlots] = useState<AvailabilitySlot[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const wsRef = useRef<NaturalPathWebSocket | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!practitionerId || !date) {
      return;
    }

    try {
      const config = getConfig();
      wsRef.current = createWebSocket({ baseUrl: config.baseUrl });

      // Handle connection
      wsRef.current.on('connected', () => {
        setIsConnected(true);
        setError(null);
      });

      wsRef.current.on('disconnected', () => {
        setIsConnected(false);
      });

      wsRef.current.on('error', (err) => {
        setError(err as Error);
      });

      // Handle availability updates
      wsRef.current.on<AvailabilityUpdate>('availability_update', (data) => {
        setSlots(data.slots);
        setLastUpdate(new Date());
        
        // Also update React Query cache
        queryClient.setQueryData(
          queryKeys.practitioners.availability(practitionerId, date),
          data.slots
        );
      });

      // Handle slot locked
      wsRef.current.on<SlotLockedEvent>('slot_locked', (data) => {
        setSlots((prev) =>
          prev.map((slot) =>
            slot.slot_id === data.slot_id ? { ...slot, status: 'locked' as const } : slot
          )
        );
        setLastUpdate(new Date());
      });

      // Handle slot released
      wsRef.current.on<SlotReleasedEvent>('slot_released', (data) => {
        setSlots((prev) =>
          prev.map((slot) =>
            slot.slot_id === data.slot_id ? { ...slot, status: 'available' as const } : slot
          )
        );
        setLastUpdate(new Date());
      });

      // Connect to availability WebSocket
      wsRef.current.connectToAvailability(practitionerId, date);

    } catch (err) {
      console.error('[NaturalPath SDK] WebSocket setup error:', err);
      setError(err as Error);
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.disconnect();
        wsRef.current = null;
      }
    };
  }, [practitionerId, date, queryClient]);

  return { slots, isConnected, lastUpdate, error };
}

export interface UseRealtimeNotificationsResult {
  isConnected: boolean;
  error: Error | null;
}

/**
 * Hook for real-time notifications via WebSocket
 * 
 * @example
 * ```tsx
 * const { isConnected } = useRealtimeNotifications('user-id', (notification) => {
 *   toast.info(notification.title);
 * });
 * ```
 */
export function useRealtimeNotifications(
  userId: string | undefined,
  onNotification?: (notification: unknown) => void
): UseRealtimeNotificationsResult {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const wsRef = useRef<NaturalPathWebSocket | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!userId) {
      return;
    }

    try {
      const config = getConfig();
      wsRef.current = createWebSocket({ baseUrl: config.baseUrl });

      wsRef.current.on('connected', () => {
        setIsConnected(true);
        setError(null);
      });

      wsRef.current.on('disconnected', () => {
        setIsConnected(false);
      });

      wsRef.current.on('error', (err) => {
        setError(err as Error);
      });

      // Handle notifications
      wsRef.current.on('notification', (data) => {
        // Invalidate notifications cache
        queryClient.invalidateQueries({ queryKey: queryKeys.user.notifications() });
        
        // Call custom handler if provided
        if (onNotification) {
          onNotification(data);
        }
      });

      // Connect to notifications WebSocket
      wsRef.current.connectToNotifications(userId);

    } catch (err) {
      console.error('[NaturalPath SDK] WebSocket setup error:', err);
      setError(err as Error);
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.disconnect();
        wsRef.current = null;
      }
    };
  }, [userId, onNotification, queryClient]);

  return { isConnected, error };
}

/**
 * Manual WebSocket connection hook for advanced use cases
 * 
 * @example
 * ```tsx
 * const { connect, disconnect, isConnected, on } = useWebSocket();
 * 
 * useEffect(() => {
 *   connect('availability', practitionerId, date);
 *   const unsubscribe = on('slot_locked', (data) => console.log(data));
 *   return () => {
 *     unsubscribe();
 *     disconnect();
 *   };
 * }, []);
 * ```
 */
export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<NaturalPathWebSocket | null>(null);

  const connect = useCallback((
    type: 'availability' | 'notifications',
    ...args: string[]
  ) => {
    const config = getConfig();
    wsRef.current = createWebSocket({ baseUrl: config.baseUrl });

    wsRef.current.on('connected', () => setIsConnected(true));
    wsRef.current.on('disconnected', () => setIsConnected(false));

    if (type === 'availability' && args.length >= 2) {
      wsRef.current.connectToAvailability(args[0], args[1]);
    } else if (type === 'notifications' && args.length >= 1) {
      wsRef.current.connectToNotifications(args[0]);
    }
  }, []);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.disconnect();
      wsRef.current = null;
    }
  }, []);

  const on = useCallback(<T>(event: string, handler: (data: T) => void) => {
    if (!wsRef.current) {
      console.warn('[NaturalPath SDK] WebSocket not connected');
      return () => {};
    }
    return wsRef.current.on(event as any, handler);
  }, []);

  useEffect(() => {
    return () => disconnect();
  }, [disconnect]);

  return { connect, disconnect, isConnected, on };
}
