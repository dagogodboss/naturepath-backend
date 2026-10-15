"""Which clinic dates in the booking window still have an open slot."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Awaitable, Callable, Dict, List, Sequence

from core.time_utils import clinic_now

# Matches practitioner slot generation (AvailabilityManagement: next 60 days).
BOOKING_OPEN_DATES_MAX_DAYS = 60


def clinic_window_dates(days: int = 60, today: date | None = None) -> List[str]:
    """Clinic-local dates the booking calendar offers, capped at 60 days."""
    count = min(max(int(days), 1), BOOKING_OPEN_DATES_MAX_DAYS)
    start = today or clinic_now().date()
    return [(start + timedelta(days=offset)).isoformat() for offset in range(count)]


async def open_dates_in_window(
    dates: Sequence[str],
    slots_for_date: Callable[[str], Awaitable[Sequence]],
) -> Dict[str, object]:
    """Keep every date visible, and mark only dates that still have bookable time."""
    results = await asyncio.gather(*[slots_for_date(day) for day in dates])
    open_dates = [day for day, slots in zip(dates, results) if slots]
    return {
        "dates": list(dates),
        "open_dates": open_dates,
        "has_open_slots": bool(open_dates),
    }
