"""Clinic-local booking dates must reject yesterday in America/Chicago."""

from datetime import date

import pytest

from core.time_utils import assert_clinic_date_not_past


def test_same_calendar_day_is_allowed():
    assert_clinic_date_not_past("2026-09-23", today=date(2026, 9, 23))


def test_past_clinic_day_is_rejected():
    with pytest.raises(ValueError, match="past date"):
        assert_clinic_date_not_past("2026-09-22", today=date(2026, 9, 23))


def test_invalid_date_is_rejected():
    with pytest.raises(ValueError, match="Invalid booking date"):
        assert_clinic_date_not_past("09/23/2026", today=date(2026, 9, 23))
