import { describe, expect, it } from 'vitest';
import { addCalendarDays, formatClinicDateLabel, formatDate } from './index';

describe('clinic calendar dates', () => {
  it('labels Wednesday Sep 23 as that calendar day, not the previous evening', () => {
    // 21:00 UTC is 4:00pm in America/Chicago on the same civil date.
    const afternoon = new Date('2026-09-23T21:00:00.000Z');
    const iso = formatDate(afternoon);
    expect(iso).toBe('2026-09-23');
    expect(formatClinicDateLabel(iso)).toBe('Wed, Sep 23');
  });

  it('does not shift late Chicago evening onto the next UTC date', () => {
    // 03:30 UTC Sep 24 is still 10:30pm Sep 23 in Chicago.
    const evening = new Date('2026-09-24T03:30:00.000Z');
    expect(formatDate(evening)).toBe('2026-09-23');
  });

  it('adds clinic calendar days without a timezone hop', () => {
    expect(addCalendarDays('2026-09-23', 1)).toBe('2026-09-24');
    expect(addCalendarDays('2026-09-23', 6)).toBe('2026-09-29');
  });
});