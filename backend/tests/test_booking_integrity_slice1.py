"""
Issue #9 Slice 1: booking integrity A1–A6 (behind MULTI_RESOURCE_SCHEDULING).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from application.resource_availability import (
    BookingWindowViolation,
    ResourceCalendarUnavailable,
    assert_notice_and_window,
)
from application.resource_reservation import (
    acquire_resource_reservation,
    expire_pending_booking_busy,
    expire_pending_reservations,
)
from application.multi_resource_booking import fetch_resource_busy
from core.config import settings
from tests.test_multi_resource_booking_wiring import (
    RES_NICHOLE,
    RES_SALT,
    TUE,
    _FindCollection,
    _build_use_case,
    _services,
)


def test_a1_busy_lookup_failure_is_not_empty_free():
    class BoomBusy:
        def find(self, *args, **kwargs):
            raise RuntimeError("mongo down")

    db = type(
        "DB",
        (),
        {
            "resource_busy_intervals": BoomBusy(),
            "resource_reservations": _FindCollection([]),
            "outlook_calendar_connections": _FindCollection([]),
            "resources": _FindCollection(
                [
                    {
                        "resource_id": RES_SALT,
                        "active": True,
                        "weekly_hours": [],
                    }
                ]
            ),
        },
    )()
    with pytest.raises(ResourceCalendarUnavailable):
        asyncio.run(fetch_resource_busy(db, RES_SALT, TUE))


def test_a1_stale_connection_blocks_slots_and_lock():
    use_case, booking_repo, _ = _build_use_case()
    db = booking_repo.collection.database
    db.outlook_calendar_connections.rows.append(
        {
            "connection_id": "c1",
            "authoritative_for_resource_ids": [RES_SALT],
            "visibility_only": False,
            "last_sync_status": "error",
            "last_synced_at": (
                datetime.now(timezone.utc) - timedelta(hours=2)
            ).isoformat(),
        }
    )
    with patch.object(settings, "multi_resource_scheduling", True):
        with pytest.raises(ResourceCalendarUnavailable):
            asyncio.run(use_case.get_service_available_slots("svc-salt", TUE))

        booking_id = "b-stale-lock"
        booking_repo.docs[booking_id] = {
            "booking_id": booking_id,
            "customer_id": "u-cust",
            "practitioner_id": "p1",
            "service_id": "svc-salt",
            "status": "draft",
            "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
            "total_price": 45,
        }
        with pytest.raises(ResourceCalendarUnavailable):
            asyncio.run(use_case.lock_slot(booking_id=booking_id, user_id="u-cust"))


def test_a1_stale_salt_does_not_block_healthy_discovery():
    use_case, booking_repo, _ = _build_use_case()
    db = booking_repo.collection.database
    db.outlook_calendar_connections.rows.append(
        {
            "connection_id": "c-salt",
            "authoritative_for_resource_ids": [RES_SALT],
            "last_sync_status": "error",
            "last_synced_at": None,
        }
    )
    with patch.object(settings, "multi_resource_scheduling", True):
        discovery = asyncio.run(
            use_case.get_service_available_slots("svc-discovery", TUE)
        )
        with pytest.raises(ResourceCalendarUnavailable):
            asyncio.run(use_case.get_service_available_slots("svc-salt", TUE))
    assert "15:00" in [s["start_time"] for s in discovery]


def test_a2_discovery_and_salt_same_clock_both_lock():
    use_case, booking_repo, _ = _build_use_case()
    booking_repo.docs["b-d"] = {
        "booking_id": "b-d",
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-discovery",
        "status": "draft",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:30"},
        "total_price": 0,
    }
    booking_repo.docs["b-s"] = {
        "booking_id": "b-s",
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "draft",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "total_price": 45,
    }
    with patch.object(settings, "multi_resource_scheduling", True):
        asyncio.run(use_case.lock_slot(booking_id="b-d", user_id="u-cust"))
        asyncio.run(use_case.lock_slot(booking_id="b-s", user_id="u-cust"))
    reservations = booking_repo.collection.database.resource_reservations.rows
    assert {r["resource_id"] for r in reservations} == {RES_NICHOLE, RES_SALT}


def test_a2_overlapping_salt_starts_one_winner():
    use_case, booking_repo, _ = _build_use_case()
    booking_repo.docs["b-1500"] = {
        "booking_id": "b-1500",
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "draft",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "total_price": 45,
    }
    booking_repo.docs["b-1515"] = {
        "booking_id": "b-1515",
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "draft",
        # Grid is 60m for Salt; use 15:00 occupied overlap via manual occupied
        # by booking a Discovery-length isn't right — Salt occupied is 60m.
        # Second booking at 15:00 again should lose; use adjacent start that
        # overlaps occupied via a synthetic reservation after first lock.
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "total_price": 45,
    }
    with patch.object(settings, "multi_resource_scheduling", True):
        asyncio.run(use_case.lock_slot(booking_id="b-1500", user_id="u-cust"))
        with pytest.raises(ValueError, match="no longer available"):
            asyncio.run(use_case.lock_slot(booking_id="b-1515", user_id="u-cust"))


def test_a2_overlap_different_starts_via_reservation_primitive():
    use_case, booking_repo, _ = _build_use_case()
    db = booking_repo.collection.database

    async def run():
        await acquire_resource_reservation(
            db,
            resource_id=RES_SALT,
            date_str=TUE,
            occupied_start="15:00",
            occupied_end="16:00",
            booking_id="winner",
            owner_user_id="u1",
        )
        with pytest.raises(ValueError, match="no longer available"):
            await acquire_resource_reservation(
                db,
                resource_id=RES_SALT,
                date_str=TUE,
                occupied_start="15:15",
                occupied_end="16:15",
                booking_id="loser",
                owner_user_id="u2",
            )
        # Independent resource still succeeds at overlapping clock time.
        await acquire_resource_reservation(
            db,
            resource_id=RES_NICHOLE,
            date_str=TUE,
            occupied_start="15:00",
            occupied_end="15:45",
            booking_id="discovery",
            owner_user_id="u3",
        )

    asyncio.run(run())


def test_a3_pending_hold_expires_with_cleanup():
    use_case, booking_repo, busy_col = _build_use_case()
    booking_id = "b-expire"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "draft",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "total_price": 45,
    }
    with patch.object(settings, "multi_resource_scheduling", True):
        asyncio.run(use_case.lock_slot(booking_id=booking_id, user_id="u-cust"))

    db = booking_repo.collection.database
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    for row in db.resource_reservations.rows:
        if row.get("booking_id") == booking_id:
            row["expires_at"] = past
            row["status"] = "pending"
    for row in busy_col.rows:
        if row.get("booking_id") == booking_id:
            row["expires_at"] = past

    async def cleanup():
        assert await expire_pending_reservations(db) >= 1
        assert await expire_pending_booking_busy(db) >= 1

    asyncio.run(cleanup())
    assert not any(r.get("booking_id") == booking_id for r in db.resource_reservations.rows)
    assert not any(r.get("booking_id") == booking_id for r in busy_col.rows)

    booking_repo.docs[booking_id]["status"] = "pending"
    with patch.object(settings, "multi_resource_scheduling", True):
        # Expired pending can reacquire via confirm's acquire, but competing
        # busy is gone so confirm should succeed after reacquire.
        result = asyncio.run(
            use_case.confirm_booking(booking_id=booking_id, user_id="u-cust")
        )
    assert result["status"] == "confirmed"
    # Confirmed busy must not carry a pending expiry.
    confirmed_busy = [r for r in busy_col.rows if r.get("booking_id") == booking_id]
    assert confirmed_busy and confirmed_busy[0].get("expires_at") is None


def test_a4_series_uses_resource_busy_not_practitioner_only():
    use_case, booking_repo, busy_col = _build_use_case()
    parent_id = "b-series-parent"
    booking_repo.docs[parent_id] = {
        "booking_id": parent_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "confirmed",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "resource_id": RES_SALT,
        "total_price": 45,
        "total_price_cents": 4500,
        "currency": "USD",
        "recurrence": {"frequency": "monthly", "active": True},
    }
    # Salt busy one month ahead at the same clock; Nichole free.
    next_month = "2026-11-20"
    busy_col.rows.append(
        {
            "resource_id": RES_SALT,
            "date": next_month,
            "start_time": "15:00",
            "end_time": "16:00",
            "show_as": "busy",
            "authoritative": True,
            "source": "outlook",
        }
    )
    service = _services()["svc-salt"]
    customer = {
        "user_id": "u-cust",
        "email": "p@example.com",
        "first_name": "Pat",
    }
    with patch.object(settings, "multi_resource_scheduling", True):
        meta = asyncio.run(
            use_case._materialize_monthly_series(
                parent=booking_repo.docs[parent_id],
                service=service,
                customer=customer,
                months=1,
            )
        )
    assert meta["created"] == []
    assert meta["skipped"]
    assert meta["skipped"][0]["date"] == next_month


def test_a5_confirm_writes_service_resource_not_stale_stored():
    use_case, booking_repo, busy_col = _build_use_case()
    # Service now requires Salt; booking still stores Nichole from an old assign.
    booking_id = "b-reassign"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "pending",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "resource_id": RES_NICHOLE,
        "total_price": 45,
    }
    with patch.object(settings, "multi_resource_scheduling", True):
        result = asyncio.run(
            use_case.confirm_booking(booking_id=booking_id, user_id="u-cust")
        )
    assert result["resource_id"] == RES_SALT
    written = [r for r in busy_col.rows if r.get("booking_id") == booking_id]
    assert written and written[0]["resource_id"] == RES_SALT
    assert not any(
        r.get("booking_id") == booking_id and r.get("resource_id") == RES_NICHOLE
        for r in busy_col.rows
    )


def test_a6_notice_and_window_enforced_on_initiate():
    use_case, booking_repo, _ = _build_use_case()
    services = _services()
    services["svc-salt"]["min_notice_minutes"] = 120
    services["svc-salt"]["booking_window_days"] = 30
    use_case.service_repo.services = services

    clinic_local = datetime(2026, 10, 20, 14, 45)  # 15:00 is inside 120m notice
    with patch.object(settings, "multi_resource_scheduling", True):
        with patch(
            "application.resource_availability.clinic_now", return_value=clinic_local
        ):
            with pytest.raises(BookingWindowViolation):
                asyncio.run(
                    use_case.initiate_booking(
                        customer_id="u-cust",
                        service_id="svc-salt",
                        practitioner_id=None,
                        date=TUE,
                        start_time="15:00",
                        end_time="15:45",
                    )
                )

    # Beyond window
    far = "2026-12-01"
    with patch.object(settings, "multi_resource_scheduling", True):
        with patch(
            "application.resource_availability.clinic_now",
            return_value=datetime(2026, 10, 20, 10, 0),
        ):
            with pytest.raises(BookingWindowViolation):
                asyncio.run(
                    use_case.initiate_booking(
                        customer_id="u-cust",
                        service_id="svc-salt",
                        practitioner_id=None,
                        date=far,
                        start_time="15:00",
                        end_time="15:45",
                    )
                )


def test_a6_exact_notice_boundary_allowed():
    service = {
        "min_notice_minutes": 120,
        "booking_window_days": 30,
    }
    now = datetime(2026, 10, 20, 13, 0)
    # Exactly 120 minutes later → allowed (slot_dt < earliest is false when equal).
    assert_notice_and_window(service, TUE, "15:00", now=now)
