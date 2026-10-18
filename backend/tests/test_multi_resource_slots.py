"""Phase 3 per-resource slot engine scaffold — T1–T5 and helpers."""

from application.multi_resource_slots import (
    candidate_session_starts,
    free_intervals_for_resource,
    occupied_interval_for_session_start,
    open_windows_for_date,
    session_slots_for_resource,
    slots_for_open_dates_preview,
    subtract_busy_from_windows,
)
from domain.entities.models import PractitionerAvailability

# Stable test dates (clinic-local America/Chicago wall clock).
# 2026-10-20 = Tuesday; 2026-10-19 = Monday.
TUE = "2026-10-20"
MON = "2026-10-19"

NICHOLE_HOURS = [
    PractitionerAvailability(day_of_week=d, start_time="09:00", end_time="17:00")
    for d in range(1, 6)  # Tue–Sat provisional; Monday closed for consults via flag
]
# Also allow Tue–Fri only matching common clinic; Discovery uses no_mondays.
NICHOLE_HOURS_WITH_MON = [
    PractitionerAvailability(day_of_week=d, start_time="09:00", end_time="17:00")
    for d in range(0, 5)  # Mon–Fri hours on resource; service flag blocks Mon
]

# LOCKED Q6: Salt Mon–Fri 10:30–18:00, last start 17:00
SALT_HOURS = [
    PractitionerAvailability(day_of_week=d, start_time="10:30", end_time="18:00")
    for d in range(5)  # Mon–Fri
]

# LOCKED Q1: customer 45 + cleanup 15 = occupied 60
SALT_SESSION = 45
SALT_RECOVERY = 15
SALT_LAST_START = "17:00"


def _starts(slots):
    return [s["start_time"] for s in slots]


# --- T1: Discovery busy on Nichole ≠ Salt blocked at same wall time ---


def test_t1_discovery_busy_does_not_block_salt_same_wall_time():
    nichole_busy = [
        {
            "resource_id": "res-nichole",
            "date": TUE,
            "start_time": "15:00",
            "end_time": "15:45",
            "show_as": "busy",
            "authoritative": True,
            "category_name": "Discovery",
        }
    ]
    # Salt must only see Salt busy (empty here).
    salt_slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=SALT_HOURS,
        busy_intervals=[],  # Discovery busy must not be passed for Salt
        prep_minutes=0,
        session_minutes=SALT_SESSION,
        recovery_minutes=SALT_RECOVERY,
        start_increment_minutes=60,
        last_start_time=SALT_LAST_START,
    )
    assert {"start_time": "15:00", "end_time": "15:45"} in salt_slots

    # Sanity: same busy on Nichole does block Discovery at 15:00.
    discovery_slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=NICHOLE_HOURS,
        busy_intervals=nichole_busy,
        prep_minutes=0,
        session_minutes=30,
        recovery_minutes=15,
        start_increment_minutes=60,
        flags={"no_mondays": True},
    )
    assert "15:00" not in _starts(discovery_slots)


# --- T2: Salt busy ≠ Discovery blocked ---


def test_t2_salt_busy_does_not_block_discovery_same_wall_time():
    salt_busy = [
        {
            "resource_id": "res-salt",
            "date": TUE,
            "start_time": "15:00",
            "end_time": "16:00",
            "show_as": "busy",
            "authoritative": True,
            "category_name": "Salt",
        }
    ]
    discovery_slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=NICHOLE_HOURS,
        busy_intervals=[],  # Salt busy not applied to Nichole
        prep_minutes=0,
        session_minutes=30,
        recovery_minutes=15,
        start_increment_minutes=60,
        flags={"no_mondays": True},
    )
    assert "15:00" in _starts(discovery_slots)

    salt_slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=SALT_HOURS,
        busy_intervals=salt_busy,
        prep_minutes=0,
        session_minutes=SALT_SESSION,
        recovery_minutes=SALT_RECOVERY,
        start_increment_minutes=60,
        last_start_time=SALT_LAST_START,
    )
    assert "15:00" not in _starts(salt_slots)


# --- T3: Monday — no Discovery/consult; Salt still open Mon–Fri ---


def test_t3_monday_no_discovery_salt_still_offers():
    discovery_slots = session_slots_for_resource(
        date_str=MON,
        weekly_hours=NICHOLE_HOURS_WITH_MON,
        busy_intervals=[],
        prep_minutes=0,
        session_minutes=30,
        recovery_minutes=15,
        start_increment_minutes=60,
        flags={"no_mondays": True},
    )
    assert discovery_slots == []

    salt_slots = session_slots_for_resource(
        date_str=MON,
        weekly_hours=SALT_HOURS,
        busy_intervals=[],
        prep_minutes=0,
        session_minutes=SALT_SESSION,
        recovery_minutes=SALT_RECOVERY,
        start_increment_minutes=60,
        last_start_time=SALT_LAST_START,
    )
    assert salt_slots
    assert salt_slots[0]["start_time"] == "11:00"
    assert salt_slots[-1]["start_time"] == SALT_LAST_START


# --- T4: Wellness occupation overflow vs free window end ---


def test_t4_wellness_occupation_must_fit_free_window():
    # Wellness Consultation PROVISIONAL: prep 15 + session 60 + recovery 15 = 90m.
    # Free window ends 16:30 → last hourly session start is 15:00
    # (occupied 14:45–16:15); 16:00 overflows (occupied ends 17:15).
    weekly = [
        PractitionerAvailability(day_of_week=1, start_time="09:00", end_time="16:30")
    ]
    slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=weekly,
        busy_intervals=[],
        prep_minutes=15,
        session_minutes=60,
        recovery_minutes=15,
        start_increment_minutes=60,
    )
    starts = _starts(slots)
    assert "15:00" in starts
    assert "16:00" not in starts
    assert starts[-1] == "15:00"

    occupied = occupied_interval_for_session_start(
        "15:00", prep_minutes=15, session_minutes=60, recovery_minutes=15
    )
    assert occupied == {"start_time": "14:45", "end_time": "16:15"}


# --- T5: Salt last start 17:00 for 10:30–18:00; occupied 60; no start after 17:00 ---


def test_t5_salt_last_start_no_after_1700():
    slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=SALT_HOURS,
        busy_intervals=[],
        prep_minutes=0,
        session_minutes=SALT_SESSION,
        recovery_minutes=SALT_RECOVERY,
        start_increment_minutes=60,
        last_start_time=SALT_LAST_START,
    )
    starts = _starts(slots)
    assert starts[0] == "11:00"
    assert starts[-1] == SALT_LAST_START
    assert "17:30" not in starts
    # Without last_start_time, 17:00 is still last that fits in 10–18 (17:30 wouldn't
    # fit a 60m occupied span ending by 18:00 either). Explicit last_start is enforced:
    capped = candidate_session_starts(
        [{"start_time": "10:30", "end_time": "18:00"}],
        prep_minutes=0,
        session_minutes=SALT_SESSION,
        recovery_minutes=SALT_RECOVERY,
        start_increment_minutes=30,  # would otherwise allow 17:30 if hours allowed
        last_start_time=SALT_LAST_START,
    )
    assert "17:30" not in _starts(capped)
    assert "17:00" in _starts(capped)


def test_free_intervals_punch_busy_hole():
    open_w = open_windows_for_date(SALT_HOURS, TUE)
    assert open_w == [{"start_time": "10:30", "end_time": "18:00"}]
    free = subtract_busy_from_windows(
        open_w,
        [{"start_time": "15:00", "end_time": "16:00", "show_as": "busy"}],
    )
    assert free == [
        {"start_time": "10:30", "end_time": "15:00"},
        {"start_time": "16:00", "end_time": "18:00"},
    ]


def test_free_intervals_ignore_other_resource_when_not_passed():
    """Invariant helper: only intervals supplied are subtracted."""
    free = free_intervals_for_resource(
        SALT_HOURS,
        [],  # caller must not pass Nichole Discovery busy
        TUE,
    )
    assert free == [{"start_time": "10:30", "end_time": "18:00"}]


def test_slots_for_open_dates_preview_empty_without_weekly_hours():
    assert (
        slots_for_open_dates_preview(
            date_str=TUE,
            resource={"name": "empty"},
            busy_intervals=[],
            session_minutes=SALT_SESSION,
        )
        == []
    )


def test_slots_for_open_dates_preview_reads_resource_grid():
    resource = {
        "weekly_hours": SALT_HOURS,
        "slot_grid": {"start_increment_minutes": 60},
        "last_start_time": SALT_LAST_START,
    }
    slots = slots_for_open_dates_preview(
        date_str=TUE,
        resource=resource,
        busy_intervals=[],
        session_minutes=SALT_SESSION,
        recovery_minutes=SALT_RECOVERY,
    )
    assert _starts(slots)[-1] == SALT_LAST_START
