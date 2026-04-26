"""
Date/time helpers that don't fit elsewhere.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional


def add_business_days(
    start: datetime,
    days: int,
    *,
    holidays: Optional[frozenset[date]] = None,
) -> datetime:
    """
    Return `start + days` business days, skipping Saturdays and Sundays and any
    dates in the supplied holidays set. Time-of-day and tz are preserved.
    """
    if days <= 0:
        return start
    holidays = holidays or frozenset()
    cur = start
    added = 0
    while added < days:
        cur = cur + timedelta(days=1)
        if cur.weekday() >= 5:  # Sat=5, Sun=6
            continue
        if cur.date() in holidays:
            continue
        added += 1
    return cur


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
