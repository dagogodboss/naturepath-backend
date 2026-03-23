/**
 * @natural-path/sdk - WebSocket Manager
 * 
 * Real-time availability updates and notifications
 */

import type {
  WebSocketMessage,
  AvailabilityUpdate,
  SlotLockedEvent,
  SlotReleasedEvent,
  AvailabilitySlot,
} from '../types';

export type WebSocketEventType =
  | 'availability_update'
  | 'slot_locked'
  | 'slot_released'
  | 'notification'
  | 'pong'
  | 'connected'
  | 'disconnected'
  | 'error';

export type WebSocketEventHandler<T = unknown> = (data: T) => void;

export interface WebSocketConfig {
  baseUrl: string;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
  pingInterval?: number;
}

export class NaturalPathWebSocket {
  private ws: WebSocket | null = null;
  private config: Required<WebSocketConfig>;
  private eventHandlers: Map<string, Set<WebSocketEventHandler<unknown>>> = new Map();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private currentEndpoint: string | null = null;

  constructor(config: WebSocketConfig) {
    this.config = {
      reconnectInterval: 3000,
      maxReconnectAttempts: 5,
      pingInterval: 30000,
      ...config,
    };
  }

  /**
   * Connect to availability updates for a specific practitioner and date
   */
  connectToAvailability(practitionerId: string, date: string): void {
    const wsUrl = this.config.baseUrl.replace(/^http/, 'ws');
    this.currentEndpoint = `${wsUrl}/ws/availability/${practitionerId}/${date}`;
    this.connect();
  }

  /**
   * Connect to user notifications
   */
  connectToNotifications(userId: string): void {
    const wsUrl = this.config.baseUrl.replace(/^http/, 'ws');
    this.currentEndpoint = `${wsUrl}/ws/notifications/${userId}`;
    this.connect();
  }

  private connect(): void {
    if (!this.currentEndpoint) {
      console.error('No endpoint specified for WebSocket connection');
      return;
    }

    try {
      this.ws = new WebSocket(this.currentEndpoint);

      this.ws.onopen = () => {
        console.log('[NaturalPath SDK] WebSocket connected');
        this.reconnectAttempts = 0;
        this.emit('connected', null);
        this.startPing();
      };

      this.ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          this.handleMessage(message);
        } catch (error) {
          console.error('[NaturalPath SDK] Failed to parse WebSocket message:', error);
        }
      };

      this.ws.onclose = () => {
        console.log('[NaturalPath SDK] WebSocket disconnected');
        this.emit('disconnected', null);
        this.stopPing();
        this.attemptReconnect();
      };

      this.ws.onerror = (error) => {
        console.error('[NaturalPath SDK] WebSocket error:', error);
        this.emit('error', error);
      };
    } catch (error) {
      console.error('[NaturalPath SDK] Failed to create WebSocket:', error);
      this.attemptReconnect();
    }
  }

  private handleMessage(message: WebSocketMessage): void {
    switch (message.type) {
      case 'availability_update':
        this.emit('availability_update', message.data as AvailabilityUpdate);
        break;
      case 'slot_locked':
        this.emit('slot_locked', message.data as SlotLockedEvent);
        break;
      case 'slot_released':
        this.emit('slot_released', message.data as SlotReleasedEvent);
        break;
      case 'pong':
        // Pong received, connection is alive
        break;
      default:
        // Emit generic event for unknown types
        this.emit(message.type as WebSocketEventType, message.data);
    }
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.config.maxReconnectAttempts) {
      console.error('[NaturalPath SDK] Max reconnection attempts reached');
      return;
    }

    this.reconnectAttempts++;
    console.log(
      `[NaturalPath SDK] Reconnecting in ${this.config.reconnectInterval}ms (attempt ${this.reconnectAttempts})`
    );

    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, this.config.reconnectInterval);
  }

  private startPing(): void {
    this.pingTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, this.config.pingInterval);
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  /**
   * Subscribe to WebSocket events
   */
  on<T = unknown>(event: WebSocketEventType, handler: WebSocketEventHandler<T>): () => void {
    if (!this.eventHandlers.has(event)) {
      this.eventHandlers.set(event, new Set());
    }
    this.eventHandlers.get(event)!.add(handler as WebSocketEventHandler<unknown>);

    // Return unsubscribe function
    return () => {
      this.eventHandlers.get(event)?.delete(handler as WebSocketEventHandler<unknown>);
    };
  }

  /**
   * Emit event to all subscribers
   */
  private emit<T>(event: WebSocketEventType, data: T): void {
    const handlers = this.eventHandlers.get(event);
    if (handlers) {
      handlers.forEach((handler) => handler(data));
    }
  }

  /**
   * Disconnect WebSocket
   */
  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopPing();
    
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    
    this.currentEndpoint = null;
    this.reconnectAttempts = 0;
  }

  /**
   * Check if WebSocket is connected
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// Factory function for creating WebSocket instances
export function createWebSocket(config: WebSocketConfig): NaturalPathWebSocket {
  return new NaturalPathWebSocket(config);
}
