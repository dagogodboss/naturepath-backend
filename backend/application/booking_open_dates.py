"""Which clinic dates in the booking window still have an open slot."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Awaitable, Callable, Dict, List, Sequence

from core.time_utils import clinic_now


def clinic_window_dates(days: int = 7, today: date | None = None) -> List[str]:
    """Clinic-local dates the booking calendar offers, capped at two weeks."""
    count = min(max(int(days), 1), 14)
    start = today or clinic_now().date()
    return [(start + timedelta(days=offset)).isoformat() for offset in range(count)]


async def open_dates_in_window(
    dates: Sequence[str],
    slots_for_date: Callable[[str], Awaitable[Sequence]],
) -> Dict[str, object]:
    """Keep every date visible, and mark only dates that still have bookable time."""
    open_dates: List[str] = []
    for day in dates:
        slots = await slots_for_date(day)
        if slots:
            open_dates.append(day)
    return {
        "dates": list(dates),
        "open_dates": open_dates,
        "has_open_slots": bool(open_dates),
    }
