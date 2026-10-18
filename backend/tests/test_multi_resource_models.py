"""Unit tests for Phase 1 multi-resource scheduling scaffold (models + helpers)."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.config import MULTI_RESOURCE_SCHEDULING, settings
from domain.entities.models import (
    BusyIntervalSource,
    OutlookCategoryMap,
    OutlookMailboxConnectionFields,
    PractitionerAvailability,
    Resource,
    ResourceBusyInterval,
    ResourceSlotGrid,
    ResourceType,
    ReviewQueueItem,
    ReviewQueueItemStatus,
    ReviewQueueItemType,
    Service,
    ServiceCategory,
)
from domain.scheduling_occupation import (
    occupied_minutes,
    resolve_customer_duration_minutes,
)


def test_feature_flag_defaults_false():
    assert MULTI_RESOURCE_SCHEDULING is False
    assert settings.multi_resource_scheduling is False


def test_occupied_minutes_prep_session_recovery():
    assert occupied_minutes(0, 30, 15) == 45
    assert occupied_minutes(15, 60, 15) == 90
    assert occupied_minutes(10, 120, 15) == 145
    assert occupied_minutes(0, 60, 0) == 60


def test_occupied_minutes_rejects_negatives_and_zero_customer():
    with pytest.raises(ValueError, match="non-negative"):
        occupied_minutes(-1, 30, 0)
    with pytest.raises(ValueError, match="positive"):
        occupied_minutes(0, 0, 0)


def test_resolve_customer_duration_prefers_explicit():
    assert resolve_customer_duration_minutes(45, 60) == 60
    assert resolve_customer_duration_minutes(45, None) == 45


def test_resource_practitioner_and_room_validation():
    nichole = Resource(
        type=ResourceType.PRACTITIONER,
        name="Dr. Nichole",
        linked_practitioner_id="prac-1",
        weekly_hours=[
            PractitionerAvailability(
                day_of_week=1, start_time="09:00", end_time="17:00"
            )
        ],
    )
    assert nichole.active is True
    assert nichole.capacity == 1
    assert nichole.timezone == "America/Chicago"
    assert nichole.type == ResourceType.PRACTITIONER

    salt = Resource(
        type=ResourceType.ROOM,
        name="Salt room",
        slot_grid=ResourceSlotGrid(start_increment_minutes=15),
        last_start_time="17:00",
        weekly_hours=[
            PractitionerAvailability(
                day_of_week=d, start_time="10:30", end_time="18:00"
            )
            for d in range(5)
        ],
    )
    assert salt.slot_grid.start_increment_minutes == 15
    assert salt.last_start_time == "17:00"
    assert len(salt.weekly_hours) == 5


def test_resource_busy_interval_and_review_queue():
    interval = ResourceBusyInterval(
        resource_id="res-nichole",
        date="2026-10-20",
        start_time="15:00",
        end_time="15:45",
        source=BusyIntervalSource.OUTLOOK,
        authoritative=True,
        category_name="Discovery",
        show_as="busy",
        synced_at=datetime.now(timezone.utc),
    )
    assert interval.is_cancelled is False
    assert interval.source == BusyIntervalSource.OUTLOOK

    item = ReviewQueueItem(
        type=ReviewQueueItemType.UNMAPPED_CATEGORY,
        message="Unclassified busy on authoritative mailbox",
        resource_id="res-nichole",
        category_name=None,
        payload={"event_id": "evt-1"},
    )
    assert item.status == ReviewQueueItemStatus.OPEN


def test_outlook_category_map_on_connection_fields():
    fields = OutlookMailboxConnectionFields(
        mailbox_email="nichole@example.com",
        linked_practitioner_id="prac-1",
        authoritative_for_resource_ids=["res-nichole"],
        visibility_only=False,
        category_maps=[
            OutlookCategoryMap(category_name="Discovery", resource_ids=["res-nichole"]),
            OutlookCategoryMap(category_name="Salt", resource_ids=["res-salt"]),
            OutlookCategoryMap(
                category_name="Business closure",
                resource_ids=["res-nichole", "res-salt"],
                blocks_all_authoritative=True,
            ),
        ],
    )
    assert len(fields.category_maps) == 3
    assert fields.visibility_only is False


def test_service_optional_scheduling_fields_default_safe():
    svc = Service(
        name="Discovery Call",
        description="Intro",
        category=ServiceCategory.WELLNESS,
        duration_minutes=30,
        price=0.0,
    )
    assert svc.required_resource_id is None
    assert svc.prep_minutes == 0
    assert svc.recovery_minutes == 0
    assert svc.flags == {}
    # Legacy field still required / present for booking path compatibility.
    assert svc.duration_minutes == 30


def test_resource_type_enum_rejects_invalid():
    with pytest.raises(ValidationError):
        Resource(type="spaceship", name="Nope")


def test_seed_builders_nichole_and_salt():
    """Seed script pure builders (no Mongo) — used when flag later enabled."""
    import sys
    from pathlib import Path

    scripts_parent = Path(__file__).resolve().parents[2]
    if str(scripts_parent) not in sys.path:
        sys.path.insert(0, str(scripts_parent))

    from scripts.seed_multi_resource_resources import (
        build_nichole_resource,
        build_salt_resource,
    )

    prac = {
        "practitioner_id": "prac-abc",
        "user_id": "user-xyz",
        "availability": [
            {
                "day_of_week": 2,
                "start_time": "09:00",
                "end_time": "17:00",
                "is_available": True,
            }
        ],
    }
    nichole = build_nichole_resource(prac)
    assert nichole.type == ResourceType.PRACTITIONER
    assert nichole.linked_practitioner_id == "prac-abc"
    assert len(nichole.weekly_hours) == 1

    salt = build_salt_resource()
    assert salt.type == ResourceType.ROOM
    assert salt.last_start_time == "17:00"
    assert salt.slot_grid is not None
    assert salt.slot_grid.start_increment_minutes == 15
    assert len(salt.weekly_hours) == 5
    assert all(h.start_time == "10:30" and h.end_time == "18:00" for h in salt.weekly_hours)


def test_locked_outlook_defaults_clients_salt_mailbox():
    from domain.multi_resource_defaults import (
        SALT_OUTLOOK_MAILBOX,
        build_clients_salt_authoritative_category_maps,
        build_locked_outlook_connection_templates,
    )

    assert SALT_OUTLOOK_MAILBOX == "Clients@thenaturalpathla.com"
    maps = build_clients_salt_authoritative_category_maps("res-salt", "res-nichole")
    names = {m.category_name for m in maps}
    assert "Salt Session" in names
    templates = build_locked_outlook_connection_templates("res-nichole", "res-salt")
    clients = templates["clients_salt_authoritative"]
    assert clients["mailbox_email"] == SALT_OUTLOOK_MAILBOX
    assert clients["authoritative_for_resource_ids"] == ["res-salt"]
    assert clients["visibility_only"] is False
