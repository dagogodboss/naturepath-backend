import { describe, expect, it } from 'vitest';
import { buildNotificationsEndpoint } from '../websocket/manager';

describe('buildNotificationsEndpoint', () => {
  it('appends JWT as ?token= query param', () => {
    const url = buildNotificationsEndpoint(
      'wss://api.example.com',
      'user-123',
      'jwt.access.token'
    );
    expect(url).toBe(
      'wss://api.example.com/ws/notifications/user-123?token=jwt.access.token'
    );
  });

  it('URL-encodes special characters in the token', () => {
    const url = buildNotificationsEndpoint(
      'wss://api.example.com',
      'user-123',
      'a+b/c='
    );
    expect(url).toContain('token=a%2Bb%2Fc%3D');
  });

  it('omits token when accessToken is missing', () => {
    expect(buildNotificationsEndpoint('wss://api.example.com', 'u1', null)).toBe(
      'wss://api.example.com/ws/notifications/u1'
    );
  });
});
