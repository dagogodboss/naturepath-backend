/**
 * Calendar deep links + .ics download for booking confirmation UX.
 * Apple / iCloud: use downloadBookingIcal (GET /api/booking/{id}/ical).
 */

import { bookingApi } from '../api/endpoints';
import type { Booking } from '../types';

function pad2(n: string | number): string {
  return String(n).padStart(2, '0');
}

function toLocalCompact(dateStr: string, timeStr?: string): string {
  const t = (timeStr || '09:00').trim();
  const parts = t.split(':');
  const hh = pad2(parts[0] || '09');
  const mm = pad2(parts[1] || '00');
  const ss = pad2(parts[2] || '00');
  const ds = String(dateStr || '').replace(/-/g, '');
  return `${ds}T${hh}${mm}${ss}`;
}

function toIsoLocal(dateStr: string, timeStr?: string): string {
  const t = (timeStr || '09:00').trim();
  const normalized = t.length === 5 ? `${t}:00` : t;
  return `${dateStr}T${normalized}`;
}

export interface CalendarLinkInput {
  title?: string;
  date: string;
  startTime?: string;
  endTime?: string;
  details?: string;
  location?: string;
}

export interface CalendarLinks {
  google: string;
  yahoo: string;
  outlookLive: string;
  outlookOffice: string;
}

export function buildCalendarLinks({
  title,
  date,
  startTime,
  endTime,
  details = '',
  location = 'The Natural Path Spa',
}: CalendarLinkInput): CalendarLinks {
  const gStart = toLocalCompact(date, startTime);
  const gEnd = toLocalCompact(date, endTime || startTime);
  const isoStart = toIsoLocal(date, startTime);
  const isoEnd = toIsoLocal(date, endTime || startTime);

  const google = new URL('https://calendar.google.com/calendar/render');
  google.searchParams.set('action', 'TEMPLATE');
  google.searchParams.set('text', title || 'Appointment');
  google.searchParams.set('dates', `${gStart}/${gEnd}`);
  google.searchParams.set('details', details);
  google.searchParams.set('location', location);

  const yahoo = new URL('https://calendar.yahoo.com/');
  yahoo.searchParams.set('v', '60');
  yahoo.searchParams.set('title', title || 'Appointment');
  yahoo.searchParams.set('st', gStart);
  yahoo.searchParams.set('et', gEnd);
  yahoo.searchParams.set('desc', details);
  yahoo.searchParams.set('in_loc', location);

  const outlookLive = new URL('https://outlook.live.com/calendar/0/deeplink/compose');
  outlookLive.searchParams.set('path', '/calendar/action/compose');
  outlookLive.searchParams.set('rru', 'addevent');
  outlookLive.searchParams.set('subject', title || 'Appointment');
  outlookLive.searchParams.set('startdt', isoStart);
  outlookLive.searchParams.set('enddt', isoEnd);
  outlookLive.searchParams.set('body', details);
  outlookLive.searchParams.set('location', location);

  const outlookOffice = new URL('https://outlook.office.com/calendar/0/deeplink/compose');
  outlookOffice.searchParams.set('path', '/calendar/action/compose');
  outlookOffice.searchParams.set('rru', 'addevent');
  outlookOffice.searchParams.set('subject', title || 'Appointment');
  outlookOffice.searchParams.set('startdt', isoStart);
  outlookOffice.searchParams.set('enddt', isoEnd);
  outlookOffice.searchParams.set('body', details);
  outlookOffice.searchParams.set('location', location);

  return {
    google: google.toString(),
    yahoo: yahoo.toString(),
    outlookLive: outlookLive.toString(),
    outlookOffice: outlookOffice.toString(),
  };
}

export function linksFromBooking(booking: Partial<Booking> | null | undefined): CalendarLinks {
  const slot = booking?.slot || { date: '', start_time: '', end_time: '' };
  const serviceName = booking?.service?.name || 'Appointment';
  const id = booking?.booking_id || '';
  return buildCalendarLinks({
    title: serviceName,
    date: slot.date,
    startTime: slot.start_time,
    endTime: slot.end_time,
    details: id
      ? `Booking ${String(id).slice(0, 8).toUpperCase()} — The Natural Path Spa`
      : '',
  });
}

/** Download .ics via authenticated API (Apple Calendar / iCloud path). */
export async function downloadBookingIcal(bookingId: string): Promise<void> {
  const data = await bookingApi.downloadIcal(bookingId);
  const blob = new Blob([data], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `booking-${bookingId}.ics`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
