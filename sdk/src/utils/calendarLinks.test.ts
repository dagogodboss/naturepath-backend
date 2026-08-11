/**
 * SDK calendar link builders (Phase C1) — user-story: add to calendar buttons work.
 */
import { describe, expect, it } from 'vitest';
import { buildCalendarLinks, linksFromBooking } from './calendarLinks';

describe('buildCalendarLinks', () => {
  it('builds google yahoo and outlook URLs', () => {
    const links = buildCalendarLinks({
      title: 'Discovery Call',
      date: '2026-08-01',
      startTime: '10:00',
      endTime: '11:00',
      details: 'Booking bk-1',
    });
    expect(links.google).toContain('calendar.google.com');
    expect(links.yahoo).toContain('calendar.yahoo.com');
    expect(links.outlookLive).toContain('outlook.live.com');
    expect(links.outlookOffice).toContain('outlook.office.com');
    expect(links.google).toContain('20260801T100000');
    expect(links.google).toContain('20260801T110000');
  });
});

describe('linksFromBooking', () => {
  it('reads slot + service from booking shape', () => {
    const links = linksFromBooking({
      slot: { date: '2026-08-15', start_time: '14:00', end_time: '15:00' },
      service: { name: 'Massage' },
    } as any);
    expect(links.google).toContain('Massage');
    expect(links.yahoo).toContain('20260815T140000');
  });
});
