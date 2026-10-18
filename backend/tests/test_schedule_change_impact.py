"""Unit tests for schedule-change impact evaluation."""
from datetime import date, timedelta

from application.schedule_change_impact import evaluate_booking_schedule_impact


def test_last_start_exceeded_flags_impact():
    future = (date.today() + timedelta(days=14)).isoformat()
    booking = {
        "booking_id": "b1",
        "status": "confirmed",
        "resource_id": "r1",
        "service_id": "s1",
        "slot": {"date": future, "start_time": "17:30", "end_time": "18:30"},
    }
    service = {
        "service_id": "s1",
        "duration_minutes": 60,
        "prep_minutes": 0,
        "recovery_minutes": 0,
    }
    resource = {
        "resource_id": "r1",
        "weekly_hours": [
            {
                "day_of_week": date.fromisoformat(future).weekday(),
                "start_time": "09:00",
                "end_time": "20:00",
                "is_available": True,
            }
        ],
        "last_start_time": "17:00",
    }
    hit = evaluate_booking_schedule_impact(
        booking=booking, service=service, resource=resource
    )
    assert hit is not None
    codes = {r["code"] for r in hit["reasons"]}
    assert "LAST_START_EXCEEDED" in codes


def test_booking_still_fits_returns_none():
    future = (date.today() + timedelta(days=14)).isoformat()
    dow = date.fromisoformat(future).weekday()
    booking = {
        "booking_id": "b2",
        "slot": {"date": future, "start_time": "10:00", "end_time": "11:00"},
    }
    service = {"duration_minutes": 60, "prep_minutes": 0, "recovery_minutes": 0}
    resource = {
        "weekly_hours": [
            {
                "day_of_week": dow,
                "start_time": "09:00",
                "end_time": "17:00",
                "is_available": True,
            }
        ],
        "last_start_time": "16:00",
    }
    assert (
        evaluate_booking_schedule_impact(
            booking=booking, service=service, resource=resource
        )
        is None
    )
