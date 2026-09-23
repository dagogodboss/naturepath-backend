/**
 * natural-path-sdk - Utility Functions
 */

export {
  discoveryState,
  discoveryMessagingKey,
  discoveryBannerCopy,
  isDiscoveryUnlocked,
} from './discoveryGate';
export type { DiscoveryState, DiscoveryMessagingKey } from './discoveryGate';

export {
  previewMediaSrc,
  reelPreviewSrc,
  embedIframeSrc,
  cardPosterSrc,
} from './previewMedia';

export {
  buildCalendarLinks,
  linksFromBooking,
  downloadBookingIcal,
} from './calendarLinks';
export type { CalendarLinkInput, CalendarLinks } from './calendarLinks';

/** Clinic wall clock for Youngsville, LA. Booking days use this zone, not UTC. */
export const CLINIC_TIMEZONE = 'America/Chicago';

/**
 * Format a Date as YYYY-MM-DD on the clinic calendar.
 * `toISOString()` is UTC and shifts US afternoons onto the previous evening
 * once the string is parsed with `new Date("YYYY-MM-DD")`.
 */
export function formatDate(date: Date, timeZone: string = CLINIC_TIMEZONE): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value || '';
  return `${value('year')}-${value('month')}-${value('day')}`;
}

/** Add calendar days to a YYYY-MM-DD string without crossing a timezone. */
export function addCalendarDays(isoDate: string, days: number): string {
  const [year, month, day] = isoDate.split('-').map(Number);
  const utc = new Date(Date.UTC(year, month - 1, day + days));
  const y = utc.getUTCFullYear();
  const m = String(utc.getUTCMonth() + 1).padStart(2, '0');
  const d = String(utc.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * Label a clinic calendar day. Parsing `YYYY-MM-DD` with `new Date()` is UTC
 * midnight, which reads as the previous evening in US timezones.
 */
export function formatClinicDateLabel(isoDate: string): string {
  const [year, month, day] = isoDate.split('-').map(Number);
  const utcNoon = new Date(Date.UTC(year, month - 1, day, 12, 0, 0));
  return utcNoon.toLocaleDateString('en-US', {
    timeZone: 'UTC',
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

/**
 * Format time to HH:MM
 */
export function formatTime(date: Date): string {
  return date.toTimeString().slice(0, 5);
}

/**
 * Parse date string to Date object
 */
export function parseDate(dateStr: string): Date {
  return new Date(dateStr);
}

/**
 * Get day of week (0 = Monday, 6 = Sunday)
 */
export function getDayOfWeek(date: Date): number {
  const day = date.getDay();
  return day === 0 ? 6 : day - 1; // Convert Sunday = 0 to Sunday = 6
}

/**
 * Add days to a date
 */
export function addDays(date: Date, days: number): Date {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

/**
 * Get date range for the week
 */
export function getWeekRange(date: Date = new Date()): { start: string; end: string } {
  const dayOfWeek = getDayOfWeek(date);
  const start = addDays(date, -dayOfWeek);
  const end = addDays(start, 6);
  return {
    start: formatDate(start),
    end: formatDate(end),
  };
}

/**
 * Get date range for the month
 */
export function getMonthRange(date: Date = new Date()): { start: string; end: string } {
  const start = new Date(date.getFullYear(), date.getMonth(), 1);
  const end = new Date(date.getFullYear(), date.getMonth() + 1, 0);
  return {
    start: formatDate(start),
    end: formatDate(end),
  };
}

/**
 * Format currency
 *
 * Deprecated in favor of `formatMoney({amount_cents, currency})` when a cents
 * field is available. Kept for backward compatibility; new UI surfaces should
 * prefer `formatMoney`.
 */
export function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
  }).format(amount);
}

/**
 * Preferred money formatter: reads an integer cents value plus a currency
 * code. Falls back to USD formatting if currency is missing.
 */
export function formatMoney(input: {
  amount_cents?: number | null;
  currency?: string | null;
  /** Legacy: accept a float dollars value when cents are not available. */
  amount?: number | null;
}): string {
  const currency = (input.currency || 'USD').toUpperCase();
  let amount: number;
  if (input.amount_cents != null) {
    amount = Number(input.amount_cents) / 100;
  } else if (input.amount != null) {
    amount = Number(input.amount);
  } else {
    amount = 0;
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
  }).format(amount);
}

/**
 * Format duration in minutes to human readable
 */
export function formatDuration(minutes: number): string {
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (remainingMinutes === 0) {
    return `${hours} hr`;
  }
  return `${hours} hr ${remainingMinutes} min`;
}

/**
 * Check if a date is today
 */
export function isToday(date: Date | string): boolean {
  const d = typeof date === 'string' ? new Date(date) : date;
  const today = new Date();
  return (
    d.getDate() === today.getDate() &&
    d.getMonth() === today.getMonth() &&
    d.getFullYear() === today.getFullYear()
  );
}

/**
 * Check if a date is in the past
 */
export function isPastDate(date: Date | string): boolean {
  const d = typeof date === 'string' ? new Date(date) : date;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return d < today;
}

/**
 * Generate time slots between start and end hours
 */
export function generateTimeSlots(
  startHour: number,
  endHour: number,
  intervalMinutes: number = 60
): string[] {
  const slots: string[] = [];
  let currentMinutes = startHour * 60;
  const endMinutes = endHour * 60;

  while (currentMinutes < endMinutes) {
    const hours = Math.floor(currentMinutes / 60);
    const minutes = currentMinutes % 60;
    slots.push(`${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`);
    currentMinutes += intervalMinutes;
  }

  return slots;
}

/**
 * Sleep utility for async operations
 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Debounce function
 */
export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout> | null = null;

  return (...args: Parameters<T>) => {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    timeoutId = setTimeout(() => func(...args), wait);
  };
}
