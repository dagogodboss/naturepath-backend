import { describe, expect, it } from 'vitest';
import {
  discoveryBannerCopy,
  discoveryMessagingKey,
  discoveryState,
  isDiscoveryUnlocked,
} from './discoveryGate';

describe('discoveryState', () => {
  it('prefers explicit state', () => {
    expect(discoveryState({ state: 'scheduled', has_discovery_booking: true })).toBe(
      'scheduled'
    );
  });

  it('does not map legacy has_discovery_booking to scheduled', () => {
    expect(
      discoveryState({
        has_discovery_booking: true,
        is_discovery_completed: false,
      })
    ).toBe('pending_completion');
  });

  it('maps completed flag', () => {
    expect(discoveryState({ is_discovery_completed: true })).toBe('completed');
  });

  it('returns none when empty', () => {
    expect(discoveryState(null)).toBe('none');
    expect(discoveryState({})).toBe('none');
  });
});

describe('discoveryMessagingKey + banner copy (A2 user story)', () => {
  it('maps four messaging keys', () => {
    expect(discoveryMessagingKey({ state: 'none' })).toBe('please_book');
    expect(discoveryMessagingKey({ state: 'scheduled' })).toBe('scheduled');
    expect(discoveryMessagingKey({ state: 'pending_completion' })).toBe('pending');
    expect(discoveryMessagingKey({ state: 'completed' })).toBe('unlocked');
  });

  it('guest banner asks to register', () => {
    const copy = discoveryBannerCopy({ state: 'none' }, { isAuthenticated: false });
    expect(copy).toMatch(/Register and book a Discovery Call/i);
  });

  it('authenticated please_book / scheduled / pending copy', () => {
    expect(
      discoveryBannerCopy({ state: 'none' }, { isAuthenticated: true })
    ).toMatch(/Please book a Discovery Call first/i);
    expect(
      discoveryBannerCopy(
        {
          state: 'scheduled',
          discovery_slot: { date: '2026-08-01', start_time: '10:00' },
        },
        { isAuthenticated: true }
      )
    ).toMatch(/scheduled Discovery Call/i);
    expect(
      discoveryBannerCopy({ state: 'pending_completion' }, { isAuthenticated: true })
    ).toMatch(/Pending Discovery Call/i);
  });

  it('unlocked hides banner', () => {
    expect(
      discoveryBannerCopy({ state: 'completed' }, { isAuthenticated: true })
    ).toBeNull();
  });

  it('isDiscoveryUnlocked requires auth + completed', () => {
    expect(isDiscoveryUnlocked({ state: 'completed' }, true)).toBe(true);
    expect(isDiscoveryUnlocked({ state: 'completed' }, false)).toBe(false);
    expect(isDiscoveryUnlocked({ state: 'scheduled' }, true)).toBe(false);
  });
});
