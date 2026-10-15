import asyncio
from datetime import date

from application.booking_open_dates import clinic_window_dates, open_dates_in_window


def test_window_is_clinic_local_and_capped():
    assert clinic_window_dates(7, today=date(2026, 10, 15)) == [
        "2026-10-15",
        "2026-10-16",
        "2026-10-17",
        "2026-10-18",
        "2026-10-19",
        "2026-10-20",
        "2026-10-21",
    ]
    assert len(clinic_window_dates(60, today=date(2026, 10, 15))) == 14


def test_days_without_slots_stay_in_the_window_but_are_not_open():
    async def slots_for_date(day: str):
        if day == "2026-10-16":
            return [{"start_time": "12:00", "end_time": "13:00"}]
        return []

    summary = asyncio.run(
        open_dates_in_window(
            ["2026-10-15", "2026-10-16", "2026-10-17"],
            slots_for_date,
        )
    )

    assert summary["dates"] == ["2026-10-15", "2026-10-16", "2026-10-17"]
    assert summary["open_dates"] == ["2026-10-16"]
    assert summary["has_open_slots"] is True


def test_service_with_no_open_slots_is_reported_before_booking():
    async def slots_for_date(_day: str):
        return []

    summary = asyncio.run(
        open_dates_in_window(["2026-10-15", "2026-10-16"], slots_for_date)
    )
    assert summary["open_dates"] == []
    assert summary["has_open_slots"] is False
