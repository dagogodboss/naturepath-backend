"""Unit tests for calendar .ics + Google/Yahoo/Outlook deep links (Phase C1)."""
from core.calendar_utils import (
    booking_calendar_links,
    build_booking_ical,
    google_calendar_template_url,
    yahoo_calendar_template_url,
    microsoft_calendar_template_url,
)


def _booking(**overrides):
    base = {
        "booking_id": "bk-1",
        "status": "confirmed",
        "slot": {"date": "2026-08-01", "start_time": "10:00", "end_time": "11:00"},
        "service": {"name": "Discovery Call"},
        "practitioner": {"first_name": "Ada", "last_name": "Lovelace"},
        "customer": {"first_name": "Pat", "last_name": "Customer"},
    }
    base.update(overrides)
    return base


def test_build_booking_ical_single_vevent():
    ics = build_booking_ical(_booking())
    assert "BEGIN:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics
    assert "SUMMARY:Discovery Call" in ics
    assert "DTSTART:20260801T100000" in ics
    assert "DTEND:20260801T110000" in ics
    assert ics.count("BEGIN:VEVENT") == 1


def test_build_booking_ical_multi_vevent_series():
    parent = _booking(series_id="ser-1")
    children = [
        _booking(
            booking_id="bk-2",
            slot={"date": "2026-09-01", "start_time": "10:00", "end_time": "11:00"},
            series_id="ser-1",
        ),
        _booking(
            booking_id="bk-3",
            slot={"date": "2026-10-01", "start_time": "10:00", "end_time": "11:00"},
            series_id="ser-1",
        ),
    ]
    ics = build_booking_ical(parent, series_bookings=[parent, *children])
    assert ics.count("BEGIN:VEVENT") == 3
    assert "RRULE" not in ics  # intentional multi-VEVENT design
    assert "Series: ser-1" in ics


def test_build_booking_ical_skips_cancelled():
    ics = build_booking_ical(
        _booking(),
        series_bookings=[
            _booking(booking_id="a"),
            _booking(booking_id="b", status="cancelled"),
        ],
    )
    assert ics.count("BEGIN:VEVENT") == 1


def test_calendar_links_all_providers():
    links = booking_calendar_links(
        "Massage",
        "2026-08-01",
        "10:00",
        "11:00",
        details="Booking bk-1",
        location="The Natural Path Spa",
    )
    assert "calendar.google.com" in links["google"]
    assert "calendar.yahoo.com" in links["yahoo"]
    assert "outlook.live.com" in links["outlook_live"]
    assert "outlook.office.com" in links["outlook_office"]
    assert "20260801T100000" in links["google"]
    assert "20260801T110000" in links["google"]


def test_provider_url_builders_contain_title():
    assert "Discovery" in google_calendar_template_url(
        "Discovery", "2026-08-01", "09:00", "09:30"
    )
    assert "Discovery" in yahoo_calendar_template_url(
        "Discovery", "2026-08-01", "09:00", "09:30"
    )
    assert "Discovery" in microsoft_calendar_template_url(
        "Discovery", "2026-08-01", "09:00", "09:30"
    )
