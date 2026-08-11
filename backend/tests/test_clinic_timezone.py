"""Clinic timezone slot parsing."""
from datetime import datetime
from zoneinfo import ZoneInfo

from core.time_utils import parse_clinic_slot


def test_parse_clinic_slot_uses_la_not_utc():
    dt = parse_clinic_slot("2026-07-26", "15:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.tzinfo == ZoneInfo("America/Los_Angeles")
    # Same wall clock in UTC would be wrong for discovery gate comparisons.
    assert dt != datetime(2026, 7, 26, 15, 0, tzinfo=ZoneInfo("UTC"))
    assert dt.hour == 15
