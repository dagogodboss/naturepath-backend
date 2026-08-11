"""
Date/time helpers that don't fit elsewhere.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from core.config import settings


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


def clinic_tz() -> ZoneInfo:
    """Clinic wall-clock timezone (slots are stored as local date + HH:MM)."""
    name = (getattr(settings, "clinic_timezone", None) or "America/Los_Angeles").strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/Los_Angeles")


def clinic_now() -> datetime:
    return datetime.now(clinic_tz())


def parse_clinic_slot(date_s: str, time_s: str = "00:00") -> Optional[datetime]:
    """Parse YYYY-MM-DD + HH:MM as clinic-local, return timezone-aware datetime."""
    time_s = (time_s or "00:00")[:5]
    try:
        naive = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M")
        return naive.replace(tzinfo=clinic_tz())
    except ValueError:
        return None
