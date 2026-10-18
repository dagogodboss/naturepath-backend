"""Tests for locked service → resource backfill planning."""

from domain.multi_resource_service_attach import (
    build_service_scheduling_patch,
    patch_differs,
    scheduling_target_for_name,
)


def test_salt_session_targets_room_and_cleanup():
    t = scheduling_target_for_name("Salt Session (Halotherapy)")
    assert t is not None
    assert t.resource_role == "salt"
    assert t.prep_minutes == 0
    assert t.recovery_minutes == 15


def test_discovery_no_mondays_and_nichole():
    t = scheduling_target_for_name("Discovery Call")
    assert t is not None
    assert t.resource_role == "nichole"
    assert t.no_mondays is True
    assert (t.prep_minutes, t.recovery_minutes) == (0, 15)


def test_wellness_buffers():
    t = scheduling_target_for_name("Wellness Consultation")
    assert t is not None
    assert (t.prep_minutes, t.recovery_minutes) == (15, 15)


def test_build_patch_idempotent_when_already_set():
    svc = {
        "name": "Discovery Call",
        "duration_minutes": 30,
        "required_resource_id": "res-n",
        "prep_minutes": 0,
        "recovery_minutes": 15,
        "customer_duration_minutes": 30,
        "flags": {"no_mondays": True},
    }
    patch = build_service_scheduling_patch(
        svc, nichole_resource_id="res-n", salt_resource_id="res-s"
    )
    assert patch is not None
    assert patch_differs(svc, patch) is False


def test_build_patch_detects_drift():
    svc = {"name": "Salt Session (Halotherapy)", "duration_minutes": 45}
    patch = build_service_scheduling_patch(
        svc, nichole_resource_id="res-n", salt_resource_id="res-s"
    )
    assert patch is not None
    assert patch["required_resource_id"] == "res-s"
    assert patch_differs(svc, patch) is True
