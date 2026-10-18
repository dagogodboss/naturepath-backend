"""Q7 safer-B conflict path and review enqueue (flag-gated booking use case)."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import patch

import pytest

from application.multi_resource_conflicts import (
    confirmed_booking_overlaps_busy_interval,
    enqueue_sync_conflicts_for_busy_intervals,
    find_office_busy_blocking_occupied,
    upsert_open_manual_outlook_race_review,
    upsert_open_sync_conflict_review,
)
from application.use_cases.booking_use_case import BookingUseCase
from core.config import settings
from domain.entities.models import BusyIntervalSource, ReviewQueueItemType

# Reuse wiring fixtures from Phase 3 tests.
from tests.test_multi_resource_booking_wiring import RES_SALT, TUE, _build_use_case


class _ReviewQueueCol:
    def __init__(self):
        self.rows: list = []

    async def find_one(self, query, projection=None):
        for row in self.rows:
            if query.get("review_id") and row.get("review_id") != query.get("review_id"):
                continue
            if query.get("booking_id") and row.get("booking_id") != query.get("booking_id"):
                continue
            if query.get("type") and row.get("type") != query.get("type"):
                continue
            if query.get("status") and row.get("status") != query.get("status"):
                continue
            payload = row.get("payload") or {}
            if "payload.action" in query and payload.get("action") != query["payload.action"]:
                continue
            slot = payload.get("slot") or {}
            if "payload.slot.date" in query and slot.get("date") != query["payload.slot.date"]:
                continue
            if (
                "payload.slot.start_time" in query
                and slot.get("start_time") != query["payload.slot.start_time"]
            ):
                continue
            blocking = payload.get("blocking_interval") or {}
            if (
                "payload.blocking_interval.start_time" in query
                and blocking.get("start_time")
                != query["payload.blocking_interval.start_time"]
            ):
                continue
            if query.get("resource_id") and row.get("resource_id") != query.get(
                "resource_id"
            ):
                continue
            if query.get("event_id") and row.get("event_id") != query.get("event_id"):
                continue
            return deepcopy(row)
        return None

    async def insert_one(self, doc):
        self.rows.append(deepcopy(doc))


def test_find_office_busy_blocks_on_outlook_overlap():
    blocker = find_office_busy_blocking_occupied(
        [
            {
                "source": BusyIntervalSource.OUTLOOK.value,
                "start_time": "15:00",
                "end_time": "16:00",
                "authoritative": True,
            }
        ],
        occupied_start="15:00",
        occupied_end="16:00",
    )
    assert blocker is not None
    assert blocker["source"] == "outlook"


def test_find_office_busy_ignores_own_booking_dual_write():
    blocker = find_office_busy_blocking_occupied(
        [
            {
                "source": BusyIntervalSource.BOOKING.value,
                "booking_id": "b1",
                "start_time": "15:00",
                "end_time": "16:00",
                "authoritative": True,
            }
        ],
        occupied_start="15:00",
        occupied_end="16:00",
        exclude_booking_id="b1",
    )
    assert blocker is None


@pytest.mark.asyncio
async def test_upsert_review_idempotent():
    db = type("DB", (), {"review_queue": _ReviewQueueCol()})()
    args = dict(
        booking_id="b1",
        resource_id=RES_SALT,
        date_str=TUE,
        customer_start="15:00",
        customer_end="15:45",
        action="confirm",
        blocking_interval={"source": "outlook", "start_time": "15:00", "end_time": "16:00"},
    )
    rid1 = await upsert_open_manual_outlook_race_review(db, **args)
    rid2 = await upsert_open_manual_outlook_race_review(db, **args)
    assert rid1 == rid2
    assert len(db.review_queue.rows) == 1
    assert db.review_queue.rows[0]["type"] == ReviewQueueItemType.MANUAL_OUTLOOK_RACE.value


def test_confirm_outlook_conflict_enqueues_review_without_confirming():
    outlook_busy = [
        {
            "resource_id": RES_SALT,
            "date": TUE,
            "start_time": "15:00",
            "end_time": "16:00",
            "source": BusyIntervalSource.OUTLOOK.value,
            "authoritative": True,
        }
    ]
    use_case, booking_repo, _ = _build_use_case(busy_rows=outlook_busy)
    review_col = _ReviewQueueCol()
    use_case.booking_repo.collection.database.review_queue = review_col

    booking_id = "b-confirm-conflict"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "pending",
        "payment_status": "none",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "resource_id": RES_SALT,
        "total_price": 45,
    }

    with patch.object(settings, "multi_resource_scheduling", True):
        with pytest.raises(ValueError, match="no longer available"):
            asyncio.run(
                use_case.confirm_booking(booking_id=booking_id, user_id="u-cust")
            )

    still = booking_repo.docs[booking_id]
    assert still["status"] == "pending"
    assert still.get("payment_status") == "none"
    assert len(review_col.rows) == 1
    assert review_col.rows[0]["booking_id"] == booking_id
    assert review_col.rows[0]["type"] == ReviewQueueItemType.MANUAL_OUTLOOK_RACE.value


def test_confirmed_booking_overlaps_outlook_busy():
    booking = {
        "booking_id": "b-conf",
        "resource_id": RES_SALT,
        "occupied_start_time": "15:00",
        "occupied_end_time": "16:00",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
    }
    busy = {
        "resource_id": RES_SALT,
        "date": TUE,
        "start_time": "15:30",
        "end_time": "16:30",
        "source": BusyIntervalSource.OUTLOOK.value,
        "authoritative": True,
    }
    assert confirmed_booking_overlaps_busy_interval(booking, busy) is True


@pytest.mark.asyncio
async def test_sync_conflict_review_idempotent():
    db = type("DB", (), {"review_queue": _ReviewQueueCol()})()
    booking = {
        "booking_id": "b-conf",
        "resource_id": RES_SALT,
        "occupied_start_time": "15:00",
        "occupied_end_time": "16:00",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
    }
    blocking = {
        "resource_id": RES_SALT,
        "date": TUE,
        "start_time": "15:00",
        "end_time": "16:00",
        "source": "outlook",
        "event_id": "evt-salt",
        "connection_id": "conn-1",
    }
    rid1 = await upsert_open_sync_conflict_review(
        db, booking=booking, blocking_interval=blocking
    )
    rid2 = await upsert_open_sync_conflict_review(
        db, booking=booking, blocking_interval=blocking
    )
    assert rid1 == rid2
    assert len(db.review_queue.rows) == 1
    assert db.review_queue.rows[0]["type"] == ReviewQueueItemType.SYNC_CONFLICT.value


class _BookingsCursor:
    def __init__(self, matched):
        self._matched = matched

    async def to_list(self, length=500):
        return list(self._matched)[:length]


class _BookingsCol:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection=None):
        matched = []
        for row in self.rows:
            if query.get("status") and row.get("status") != query["status"]:
                continue
            if query.get("resource_id") and row.get("resource_id") != query[
                "resource_id"
            ]:
                continue
            slot = row.get("slot") or {}
            if query.get("slot.date") and slot.get("date") != query["slot.date"]:
                continue
            matched.append(row)
        return _BookingsCursor(matched)


@pytest.mark.asyncio
async def test_enqueue_sync_conflicts_for_busy_intervals():
    booking = {
        "booking_id": "b-conf",
        "status": "confirmed",
        "resource_id": RES_SALT,
        "occupied_start_time": "15:00",
        "occupied_end_time": "16:00",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
    }
    db = type(
        "DB",
        (),
        {
            "review_queue": _ReviewQueueCol(),
            "bookings": _BookingsCol([booking]),
        },
    )()
    count = await enqueue_sync_conflicts_for_busy_intervals(
        db,
        busy_intervals=[
            {
                "resource_id": RES_SALT,
                "date": TUE,
                "start_time": "15:00",
                "end_time": "16:00",
                "source": BusyIntervalSource.OUTLOOK.value,
                "authoritative": True,
                "event_id": "evt-1",
            }
        ],
    )
    assert count == 1
    assert db.review_queue.rows[0]["booking_id"] == "b-conf"
    assert db.review_queue.rows[0]["type"] == ReviewQueueItemType.SYNC_CONFLICT.value


def test_lock_slot_outlook_conflict_enqueues_review_without_pending():
    outlook_busy = [
        {
            "resource_id": RES_SALT,
            "date": TUE,
            "start_time": "15:00",
            "end_time": "16:00",
            "source": BusyIntervalSource.OUTLOOK.value,
            "authoritative": True,
        }
    ]
    use_case, booking_repo, _ = _build_use_case(busy_rows=outlook_busy)
    review_col = _ReviewQueueCol()
    use_case.booking_repo.collection.database.review_queue = review_col

    booking_id = "b-lock-conflict"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "draft",
        "payment_status": "none",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "resource_id": RES_SALT,
        "total_price": 45,
    }

    with patch.object(settings, "multi_resource_scheduling", True):
        with pytest.raises(ValueError, match="no longer available"):
            asyncio.run(
                use_case.lock_slot(booking_id=booking_id, user_id="u-cust")
            )

    still = booking_repo.docs[booking_id]
    assert still["status"] == "draft"
    assert still.get("payment_status") == "none"
    assert len(review_col.rows) == 1
    assert review_col.rows[0]["type"] == ReviewQueueItemType.MANUAL_OUTLOOK_RACE.value
