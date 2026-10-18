"""Phase 5 availability explainer — key reason codes (pure unit tests)."""

from datetime import datetime, timedelta, timezone

from application.availability_explain import (
    BUSY_BOOKING,
    BUSY_OUTLOOK,
    OCCUPATION_OVERFLOW,
    SERVICE_WEEKDAY_CLOSED,
    SYNC_STALE,
    explain_availability,
    sync_is_stale,
)
from domain.entities.models import PractitionerAvailability

# 2026-10-19 = Monday; 2026-10-20 = Tuesday (America/Chicago wall clock).
MON = "2026-10-19"
TUE = "2026-10-20"

NICHOLE_HOURS = [
    PractitionerAvailability(day_of_week=d, start_time="09:00", end_time="17:00")
    for d in range(0, 5)  # Mon–Fri on resource; Discovery flag blocks Mon
]

SALT_HOURS = [
    PractitionerAvailability(day_of_week=d, start_time="10:00", end_time="18:00")
    for d in range(5)
]

DISCOVERY = {
    "service_id": "svc-discovery",
    "name": "Discovery Call",
    "duration_minutes": 30,
    "prep_minutes": 0,
    "recovery_minutes": 15,
    "flags": {"no_mondays": True},
    "required_resource_id": "res-nichole",
}

SALT_SERVICE = {
    "service_id": "svc-salt",
    "name": "Salt Session",
    "duration_minutes": 45,
    "customer_duration_minutes": 45,
    "prep_minutes": 0,
    "recovery_minutes": 15,
    "flags": {},
    "required_resource_id": "res-salt",
}

WELLNESS = {
    "service_id": "svc-wellness",
    "name": "Wellness Consultation",
    "duration_minutes": 60,
    "prep_minutes": 15,
    "recovery_minutes": 15,
    "flags": {"no_mondays": True},
    "required_resource_id": "res-nichole",
}

NICHOLE = {
    "resource_id": "res-nichole",
    "type": "practitioner",
    "name": "Dr. Nichole",
    "weekly_hours": NICHOLE_HOURS,
}

SALT_ROOM = {
    "resource_id": "res-salt",
    "type": "room",
    "name": "Salt room",
    "weekly_hours": SALT_HOURS,
}


def _codes(result):
    return [r["code"] for r in result["reasons"]]


def test_monday_discovery_service_weekday_closed():
    result = explain_availability(
        date_str=MON,
        service=DISCOVERY,
        resource=NICHOLE,
        busy_intervals=[],
        start_time="10:00",
    )
    assert result["available"] is False
    assert SERVICE_WEEKDAY_CLOSED in _codes(result)


def test_discovery_busy_salt_free_same_wall_time():
    nichole_busy = [
        {
            "resource_id": "res-nichole",
            "date": TUE,
            "start_time": "15:00",
            "end_time": "15:45",
            "source": "booking",
            "booking_id": "bk-discovery",
            "show_as": "busy",
            "authoritative": True,
        }
    ]
    discovery = explain_availability(
        date_str=TUE,
        service=DISCOVERY,
        resource=NICHOLE,
        busy_intervals=nichole_busy,
        start_time="15:00",
    )
    assert discovery["available"] is False
    assert BUSY_BOOKING in _codes(discovery)

    # Salt must only see Salt busy — Discovery busy is not passed.
    salt = explain_availability(
        date_str=TUE,
        service=SALT_SERVICE,
        resource=SALT_ROOM,
        busy_intervals=[],
        start_time="15:00",
    )
    assert salt["available"] is True
    assert salt["reasons"] == []


def test_outlook_busy_on_resource():
    busy = [
        {
            "resource_id": "res-nichole",
            "date": TUE,
            "start_time": "15:00",
            "end_time": "16:00",
            "source": "outlook",
            "event_id": "evt-1",
            "category_name": "Consultation",
            "show_as": "busy",
            "authoritative": True,
        }
    ]
    result = explain_availability(
        date_str=TUE,
        service=DISCOVERY,
        resource=NICHOLE,
        busy_intervals=busy,
        start_time="15:00",
    )
    assert result["available"] is False
    assert BUSY_OUTLOOK in _codes(result)
    assert result["reasons"][0].get("blocking_event_id") == "evt-1"


def test_sync_stale_fail_closed():
    result = explain_availability(
        date_str=TUE,
        service=DISCOVERY,
        resource=NICHOLE,
        busy_intervals=[],
        start_time="10:00",
        sync_stale=True,
    )
    assert result["available"] is False
    assert SYNC_STALE in _codes(result)


def test_sync_stale_helper_error_and_age():
    now = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
    assert sync_is_stale(last_sync_status="error", now=now) is True
    assert sync_is_stale(
        last_sync_status="ok",
        last_synced_at=now - timedelta(minutes=45),
        now=now,
    ) is True
    assert sync_is_stale(
        last_sync_status="ok",
        last_synced_at=now - timedelta(minutes=10),
        now=now,
    ) is False
    assert sync_is_stale(outlook_required=False, last_sync_status="error") is False


def test_occupation_overflow_wellness():
    # Wellness 90m occupied; hours end 16:30 → 16:00 start overflows.
    short_hours = {
        **NICHOLE,
        "weekly_hours": [
            PractitionerAvailability(day_of_week=1, start_time="09:00", end_time="16:30")
        ],
    }
    overflow = explain_availability(
        date_str=TUE,
        service=WELLNESS,
        resource=short_hours,
        busy_intervals=[],
        start_time="16:00",
    )
    assert overflow["available"] is False
    assert OCCUPATION_OVERFLOW in _codes(overflow)

    fits = explain_availability(
        date_str=TUE,
        service=WELLNESS,
        resource=short_hours,
        busy_intervals=[],
        start_time="15:00",
    )
    assert fits["available"] is True
    assert fits["reasons"] == []
