/**
 * Discovery 4-state messaging helpers (API may return full or legacy shape).
 */

import type { DiscoveryEligibility } from '../types';

export type DiscoveryState = DiscoveryEligibility['state'];
export type DiscoveryMessagingKey = DiscoveryEligibility['messaging_key'];

export function discoveryState(
  eligibility: Partial<DiscoveryEligibility> | null | undefined
): DiscoveryState {
  if (!eligibility) return 'none';
  if (eligibility.state) return eligibility.state;
  // Legacy payloads without explicit state — stay conservative.
  // Do not map has_discovery_booking → scheduled (past sessions would look future).
  if (eligibility.is_discovery_completed) return 'completed';
  if (eligibility.has_discovery_booking) return 'pending_completion';
  return 'none';
}

export function discoveryMessagingKey(
  eligibility: Partial<DiscoveryEligibility> | null | undefined
): DiscoveryMessagingKey {
  if (eligibility?.messaging_key) return eligibility.messaging_key;
  const state = discoveryState(eligibility);
  if (state === 'completed') return 'unlocked';
  if (state === 'scheduled') return 'scheduled';
  if (state === 'pending_completion') return 'pending';
  return 'please_book';
}

export function discoveryBannerCopy(
  eligibility: Partial<DiscoveryEligibility> | null | undefined,
  { isAuthenticated }: { isAuthenticated?: boolean } = {}
): string | null {
  if (!isAuthenticated) {
    return 'All services are listed below. Register and book a Discovery Call to unlock other bookings.';
  }
  const key = discoveryMessagingKey(eligibility);
  const slot = eligibility?.discovery_slot;
  const when =
    slot?.date && slot?.start_time
      ? ` (${slot.date} at ${slot.start_time})`
      : '';
  switch (key) {
    case 'scheduled':
      return `You have a scheduled Discovery Call${when}. Other services unlock after your practitioner marks it complete.`;
    case 'pending':
      return 'Pending Discovery Call — your session is awaiting practitioner confirmation. Other services stay locked until then.';
    case 'unlocked':
      return null;
    case 'please_book':
    default:
      return 'Please book a Discovery Call first. Other services unlock after your Discovery Call is completed.';
  }
}

export function isDiscoveryUnlocked(
  eligibility: Partial<DiscoveryEligibility> | null | undefined,
  isAuthenticated?: boolean
): boolean {
  if (!isAuthenticated) return false;
  return discoveryState(eligibility) === 'completed';
}
