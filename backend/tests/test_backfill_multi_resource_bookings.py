"""Unit tests for booking resource backfill helpers (no Mongo)."""

from scripts.backfill_multi_resource_bookings import (
    _needs_backfill,
    _resolve_resource_id,
)


def test_needs_backfill_detects_missing_occupied():
    booking = {"resource_id": "r1", "occupied_start_time": "14:00"}
    patch = {"resource_id": "r1", "occupied_start_time": "14:15"}
    assert _needs_backfill(booking, patch) is True


def test_needs_backfill_ok_when_matching():
    booking = {
        "resource_id": "r1",
        "occupied_start_time": "14:15",
        "occupied_end_time": "15:00",
    }
    patch = {
        "resource_id": "r1",
        "occupied_start_time": "14:15",
        "occupied_end_time": "15:00",
    }
    assert _needs_backfill(booking, patch) is False


def test_resolve_resource_id_prefers_service_required():
    booking = {}
    service = {"name": "Discovery Call", "required_resource_id": "res-nichole"}
    rid, note = _resolve_resource_id(
        booking, service, nichole_id="res-nichole", salt_id="res-salt"
    )
    assert rid == "res-nichole"
    assert note is None


def test_resolve_resource_id_from_attach_rules():
    booking = {}
    service = {"name": "Salt Session (Halotherapy)", "duration_minutes": 45}
    rid, note = _resolve_resource_id(
        booking, service, nichole_id="res-nichole", salt_id="res-salt"
    )
    assert rid == "res-salt"
    assert note is None
