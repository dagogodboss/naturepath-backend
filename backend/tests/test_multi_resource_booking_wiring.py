"""
Phase 3 wiring: open-dates/slots/confirm behind MULTI_RESOURCE_SCHEDULING.

Default flag False → legacy practitioner path unchanged.
Flag True (monkeypatched) → per-resource slots; Discovery busy ≠ Salt.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import patch

import pytest

from application.booking_open_dates import open_dates_in_window
from application.multi_resource_booking import (
    busy_intervals_for_slot_engine,
    compute_session_slots,
    provisional_last_start_for_occupied_finish,
)
from domain.entities.models import BusyIntervalSource
from application.use_cases.booking_use_case import BookingUseCase
from core.config import settings
from domain.entities.models import PractitionerAvailability

TUE = "2026-10-20"  # Tuesday
MON = "2026-10-19"  # Monday

NICHOLE_HOURS = [
    PractitionerAvailability(day_of_week=d, start_time="10:30", end_time="17:45")
    for d in range(1, 5)  # Tue–Fri LOCKED from 10:30; finish occupied by 17:45
]

SALT_HOURS = [
    PractitionerAvailability(day_of_week=d, start_time="10:30", end_time="18:00")
    for d in range(5)  # LOCKED Q6 Mon–Fri 10:30–18:00, last start 17:00
]

RES_NICHOLE = "res-nichole"
RES_SALT = "res-salt"


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=None):
        if length is None:
            return list(self._rows)
        return list(self._rows)[:length]


def _row_get(row, key):
    if "." not in key:
        return row.get(key)
    cur = row
    for part in key.split("."):
        if isinstance(cur, list):
            # Any element containing the remaining path match is handled by caller.
            return [e.get(part) if isinstance(e, dict) else None for e in cur]
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _match_simple(row, query):
    for k, v in query.items():
        if k == "$or":
            if not any(_match_simple(row, clause) for clause in v):
                return False
            continue
        row_val = _row_get(row, k)
        if isinstance(v, dict):
            if "$ne" in v:
                if row_val == v["$ne"]:
                    return False
                continue
            if "$lt" in v:
                if row_val is None or not (str(row_val) < str(v["$lt"])):
                    return False
                continue
            if "$in" in v:
                if row_val not in v["$in"]:
                    return False
                continue
        if isinstance(row_val, list) and not isinstance(v, list):
            # Array contains scalar (authoritative_for_resource_ids) or nested maps.
            if v in row_val:
                continue
            if any(
                isinstance(el, dict) and v in el.values()
                for el in row_val
            ):
                continue
            return False
        if row_val != v:
            return False
    return True


class _FindCollection:
    def __init__(self, rows):
        self.rows = list(rows)

    async def find_one(self, query, projection=None):
        for row in self.rows:
            if _match_simple(row, query):
                return deepcopy(row)
        return None

    def find(self, query, projection=None):
        matched = []
        for row in self.rows:
            if _match_simple(row, query):
                matched.append(deepcopy(row))
        return _Cursor(matched)

    async def insert_one(self, doc):
        self.rows.append(deepcopy(doc))
        return type("Result", (), {"inserted_id": doc.get("reservation_id")})()

    async def update_one(self, query, update, upsert=False):
        for i, row in enumerate(self.rows):
            if _match_simple(row, query):
                patch = update.get("$set", {})
                self.rows[i] = {**row, **patch}
                return type("Result", (), {"modified_count": 1})()
        if upsert:
            doc = {**query, **update.get("$set", {}), **update.get("$setOnInsert", {})}
            self.rows.append(doc)
            return type("Result", (), {"modified_count": 0, "upserted_id": True})()
        return type("Result", (), {"modified_count": 0})()

    async def update_many(self, query, update):
        count = 0
        for i, row in enumerate(self.rows):
            if _match_simple(row, query):
                patch = update.get("$set", {})
                self.rows[i] = {**row, **patch}
                count += 1
        return type("Result", (), {"modified_count": count})()

    async def delete_many(self, query):
        kept = []
        removed = 0
        for row in self.rows:
            if _match_simple(row, query):
                removed += 1
            else:
                kept.append(row)
        self.rows = kept
        return type("Result", (), {"deleted_count": removed})()


class _StateCollection:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query, projection=None):
        key = query["state_key"]
        row = self.rows.get(key)
        return deepcopy(row) if row else None

    async def update_one(self, query, update, upsert=False):
        key = query["state_key"]
        row = self.rows.get(key, {"state_key": key})
        row.update(update.get("$set", {}))
        self.rows[key] = row


class _SlotCollection:
    def __init__(self, slot_docs):
        self.slot_docs = list(slot_docs)

    async def find_one(self, query, projection=None):
        for r in self.slot_docs:
            if (
                r.get("practitioner_id") == query.get("practitioner_id")
                and r.get("date") == query.get("date")
                and r.get("start_time") == query.get("start_time")
            ):
                return deepcopy(r)
        return None

    async def update_one(self, query, update, upsert=False):
        for i, r in enumerate(self.slot_docs):
            if (
                r.get("practitioner_id") == query.get("practitioner_id")
                and r.get("date") == query.get("date")
                and r.get("start_time") == query.get("start_time")
            ):
                patch = update.get("$set", {})
                on_insert = update.get("$setOnInsert", {})
                self.slot_docs[i] = {**r, **on_insert, **patch}
                return
        if upsert:
            doc = {
                **query,
                **update.get("$setOnInsert", {}),
                **update.get("$set", {}),
            }
            self.slot_docs.append(doc)

    def find(self, query, projection=None):
        rows = [
            deepcopy(r)
            for r in self.slot_docs
            if r.get("practitioner_id") == query.get("practitioner_id")
            and r.get("date") == query.get("date")
            and (
                "start_time" not in query
                or r.get("start_time") == query.get("start_time")
            )
        ]
        return _Cursor(rows)


class _BookingCollection:
    def __init__(self, database):
        self.database = database


class FakeBookingRepo:
    def __init__(self, database):
        self.docs = {}
        self.collection = _BookingCollection(database)

    async def create(self, entity):
        self.docs[entity["booking_id"]] = deepcopy(entity)
        return deepcopy(entity)

    async def get_by_id(self, booking_id):
        return deepcopy(self.docs.get(booking_id))

    async def update(self, booking_id, data):
        if booking_id in self.docs:
            self.docs[booking_id].update(data)
        return deepcopy(self.docs.get(booking_id))

    async def get_by_customer(self, customer_id):
        return deepcopy(
            [d for d in self.docs.values() if d.get("customer_id") == customer_id]
        )


class FakeSlotRepo:
    def __init__(self, available_by_pid_date, slot_docs):
        self.available_by_pid_date = available_by_pid_date
        self.collection = _SlotCollection(slot_docs)

    async def get_available_slots(self, practitioner_id, date):
        return deepcopy(self.available_by_pid_date.get((practitioner_id, date), []))

    async def list_slot_windows_for_practitioner_date(self, practitioner_id, date):
        out = []
        for r in self.collection.slot_docs:
            if r.get("practitioner_id") != practitioner_id or r.get("date") != date:
                continue
            st, et = r.get("start_time"), r.get("end_time")
            if st and et:
                out.append({"start_time": st, "end_time": et})
        return deepcopy(out)

    async def lock_slot(self, slot_id, user_id, lock_duration_seconds=300):
        return True

    async def update(self, slot_id, data):
        return None


class FakeServiceRepo:
    def __init__(self, services):
        self.services = services

    async def get_by_id(self, service_id):
        return deepcopy(self.services.get(service_id))


class FakePractitionerRepo:
    def __init__(self, practitioners):
        self.practitioners = practitioners

    async def get_by_service(self, service_id):
        return [
            deepcopy(p)
            for p in self.practitioners.values()
            if service_id in p.get("services", [])
        ]

    async def get_by_id(self, practitioner_id):
        p = self.practitioners.get(practitioner_id)
        return deepcopy(p) if p else None

    async def list_all(self, skip=0, limit=100):
        return deepcopy(list(self.practitioners.values())[skip : skip + limit])


class FakeUserRepo:
    def __init__(self, users):
        self.users = users

    async def get_by_id(self, user_id):
        return deepcopy(self.users.get(user_id))


class FakeEventRepo:
    async def store_event(self, event):
        return event


def _nichole_resource():
    return {
        "resource_id": RES_NICHOLE,
        "type": "practitioner",
        "name": "Dr. Nichole",
        "active": True,
        "weekly_hours": [h.model_dump() for h in NICHOLE_HOURS],
        # 30m grid so LOCKED 10:30 first start is offered (not snapped to 11:00).
        "slot_grid": {"start_increment_minutes": 30},
        # PROVISIONAL Q3: explicit 17:00 (= occupied 45 ending 17:45), not 17:15.
        "last_start_time": "17:00",
    }


def _salt_resource():
    return {
        "resource_id": RES_SALT,
        "type": "room",
        "name": "Salt room",
        "active": True,
        "weekly_hours": [h.model_dump() for h in SALT_HOURS],
        "slot_grid": {"start_increment_minutes": 60},
        "last_start_time": "17:00",
    }


def _services():
    return {
        "svc-discovery": {
            "service_id": "svc-discovery",
            "name": "Discovery Call",
            "is_active": True,
            "price": 0,
            "duration_minutes": 30,
            "prep_minutes": 0,
            "recovery_minutes": 15,
            "required_resource_id": RES_NICHOLE,
            "flags": {"no_mondays": True},
            "requires_prerequisite": False,
            "requires_discovery": False,
        },
        "svc-salt": {
            "service_id": "svc-salt",
            "name": "Salt Session",
            "is_active": True,
            "price": 45,
            "duration_minutes": 45,
            "customer_duration_minutes": 45,
            "prep_minutes": 0,
            "recovery_minutes": 15,
            "required_resource_id": RES_SALT,
            "flags": {},
            "requires_prerequisite": False,
            "requires_discovery": False,
        },
        "svc-orphan": {
            "service_id": "svc-orphan",
            "name": "Orphan",
            "is_active": True,
            "price": 10,
            "duration_minutes": 30,
            "prep_minutes": 0,
            "recovery_minutes": 0,
            # missing required_resource_id → fail closed when flag on
            "flags": {},
            "requires_prerequisite": False,
            "requires_discovery": False,
        },
    }


def _build_use_case(
    *,
    busy_rows=None,
    resources=None,
    available_by_pid_date=None,
    slot_docs=None,
):
    state = _StateCollection()
    resources_col = _FindCollection(resources or [_nichole_resource(), _salt_resource()])
    busy_col = _FindCollection(busy_rows or [])
    reservations_col = _FindCollection([])
    connections_col = _FindCollection([])
    database = type(
        "DB",
        (),
        {
            "booking_assignment_state": state,
            "resources": resources_col,
            "resource_busy_intervals": busy_col,
            "resource_reservations": reservations_col,
            "outlook_calendar_connections": connections_col,
            "outlook_calendar_events": _FindCollection([]),
        },
    )()
    practitioners = {
        "p1": {
            "practitioner_id": "p1",
            "user_id": "u-pract",
            "services": ["svc-discovery", "svc-salt", "svc-orphan"],
            "availability": [
                {
                    "day_of_week": d,
                    "start_time": "10:00",
                    "end_time": "17:00",
                    "is_available": True,
                }
                for d in range(5)
            ],
        }
    }
    users = {
        "u-pract": {
            "user_id": "u-pract",
            "is_active": True,
            "first_name": "Nichole",
            "last_name": "Moore",
            "email": "n@example.com",
        },
        "u-cust": {
            "user_id": "u-cust",
            "first_name": "Pat",
            "last_name": "Customer",
            "email": "p@example.com",
            "is_discovery_completed": True,
        },
    }
    booking_repo = FakeBookingRepo(database)
    use_case = BookingUseCase(
        booking_repo=booking_repo,
        slot_repo=FakeSlotRepo(available_by_pid_date or {}, slot_docs or []),
        service_repo=FakeServiceRepo(_services()),
        practitioner_repo=FakePractitionerRepo(practitioners),
        user_repo=FakeUserRepo(users),
        payment_repo=object(),
        event_repo=FakeEventRepo(),
        cache=None,
    )
    return use_case, booking_repo, busy_col


def test_flag_default_is_false():
    assert settings.multi_resource_scheduling is False


def test_provisional_q3_last_start_not_1715():
    # Occupied 45 → last start 17:00 (NOT 17:15) until Jonathan confirms.
    assert (
        provisional_last_start_for_occupied_finish(
            prep_minutes=0, session_minutes=30, recovery_minutes=15
        )
        == "17:00"
    )
    assert (
        provisional_last_start_for_occupied_finish(
            prep_minutes=0, session_minutes=45, recovery_minutes=0
        )
        == "17:00"
    )


def test_flag_false_uses_legacy_practitioner_slots():
    """Identical legacy path: weekly hours + availability_slots, not resources."""
    use_case, _, _ = _build_use_case(
        available_by_pid_date={
            ("p1", TUE): [{"start_time": "12:00", "end_time": "13:00"}],
        },
        # Resource busy that would block Salt at 12:00 if multi-resource ran —
        # must be ignored when flag is false.
        busy_rows=[
            {
                "resource_id": RES_SALT,
                "date": TUE,
                "start_time": "12:00",
                "end_time": "13:00",
                "show_as": "busy",
                "authoritative": True,
            }
        ],
    )
    with patch.object(settings, "multi_resource_scheduling", False):
        slots = asyncio.run(use_case.get_service_available_slots("svc-salt", TUE))
    starts = [s["start_time"] for s in slots]
    assert "12:00" in starts
    # Legacy hourly merge still offers other hours from weekly profile.
    assert "10:00" in starts


def test_flag_true_fail_closed_without_required_resource():
    use_case, _, _ = _build_use_case()
    with patch.object(settings, "multi_resource_scheduling", True):
        slots = asyncio.run(use_case.get_service_available_slots("svc-orphan", TUE))
    assert slots == []


def test_flag_true_fail_closed_missing_resource_doc():
    use_case, _, _ = _build_use_case(resources=[_salt_resource()])  # no Nichole
    with patch.object(settings, "multi_resource_scheduling", True):
        slots = asyncio.run(
            use_case.get_service_available_slots("svc-discovery", TUE)
        )
    assert slots == []


def test_flag_true_discovery_busy_does_not_block_salt():
    """Discovery≠Salt: Nichole Discovery busy must not remove Salt 15:00."""
    nichole_busy = [
        {
            "resource_id": RES_NICHOLE,
            "date": TUE,
            "start_time": "15:00",
            "end_time": "15:45",
            "show_as": "busy",
            "authoritative": True,
            "category_name": "Discovery",
        }
    ]
    use_case, _, _ = _build_use_case(busy_rows=nichole_busy)
    with patch.object(settings, "multi_resource_scheduling", True):
        salt = asyncio.run(use_case.get_service_available_slots("svc-salt", TUE))
        discovery = asyncio.run(
            use_case.get_service_available_slots("svc-discovery", TUE)
        )
    assert {"start_time": "15:00", "end_time": "15:45"} in salt
    assert "15:00" not in [s["start_time"] for s in discovery]


def test_flag_true_salt_busy_does_not_block_discovery():
    salt_busy = [
        {
            "resource_id": RES_SALT,
            "date": TUE,
            "start_time": "15:00",
            "end_time": "16:00",
            "show_as": "busy",
            "authoritative": True,
            "category_name": "Salt",
        }
    ]
    use_case, _, _ = _build_use_case(busy_rows=salt_busy)
    with patch.object(settings, "multi_resource_scheduling", True):
        discovery = asyncio.run(
            use_case.get_service_available_slots("svc-discovery", TUE)
        )
        salt = asyncio.run(use_case.get_service_available_slots("svc-salt", TUE))
    assert "15:00" in [s["start_time"] for s in discovery]
    assert "15:00" not in [s["start_time"] for s in salt]


def test_flag_true_open_dates_respect_resource_busy():
    use_case, _, _ = _build_use_case(
        busy_rows=[
            {
                "resource_id": RES_NICHOLE,
                "date": TUE,
                "start_time": "10:30",
                "end_time": "17:45",
                "show_as": "busy",
                "authoritative": True,
            }
        ]
    )

    async def run():
        with patch.object(settings, "multi_resource_scheduling", True):
            return await open_dates_in_window(
                [MON, TUE],
                lambda day: use_case.get_service_available_slots(
                    "svc-discovery", day
                ),
            )

    summary = asyncio.run(run())
    # Monday: no_mondays → closed; Tuesday: fully busy → not open.
    assert summary["open_dates"] == []


def test_busy_intervals_for_slot_engine_excludes_own_booking_hold():
    rows = [
        {
            "source": BusyIntervalSource.BOOKING.value,
            "booking_id": "b1",
            "start_time": "15:00",
            "end_time": "15:45",
        },
        {
            "source": BusyIntervalSource.BOOKING.value,
            "booking_id": "b2",
            "start_time": "16:00",
            "end_time": "16:45",
        },
    ]
    filtered = busy_intervals_for_slot_engine(rows, exclude_booking_id="b1")
    assert len(filtered) == 1
    assert filtered[0]["booking_id"] == "b2"


def test_flag_true_lock_dual_writes_pending_busy():
    use_case, booking_repo, busy_col = _build_use_case()
    booking_id = "b-lock-1"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-discovery",
        "status": "draft",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:30"},
        "total_price": 0,
    }

    with patch.object(settings, "multi_resource_scheduling", True):
        asyncio.run(use_case.lock_slot(booking_id=booking_id, user_id="u-cust"))

    written = [
        r
        for r in busy_col.rows
        if r.get("booking_id") == booking_id and r.get("resource_id") == RES_NICHOLE
    ]
    assert len(written) == 1
    assert written[0]["start_time"] == "15:00"
    assert written[0]["end_time"] == "15:45"
    assert written[0]["source"] == BusyIntervalSource.BOOKING.value


def test_flag_true_confirm_after_lock_succeeds_with_own_hold():
    use_case, booking_repo, busy_col = _build_use_case()
    booking_id = "b-lock-confirm"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-discovery",
        "status": "draft",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:30"},
        "total_price": 0,
    }
    with patch.object(settings, "multi_resource_scheduling", True):
        asyncio.run(use_case.lock_slot(booking_id=booking_id, user_id="u-cust"))
        result = asyncio.run(
            use_case.confirm_booking(booking_id=booking_id, user_id="u-cust")
        )
    assert result["status"] == "confirmed"
    assert len([r for r in busy_col.rows if r.get("booking_id") == booking_id]) == 1


def test_flag_true_confirmed_booking_blocks_same_resource_slot():
    use_case, booking_repo, busy_col = _build_use_case()
    booking_id = "b-block-discovery"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-discovery",
        "status": "pending",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:30"},
        "total_price": 0,
    }
    with patch.object(settings, "multi_resource_scheduling", True):
        asyncio.run(
            use_case.confirm_booking(booking_id=booking_id, user_id="u-cust")
        )
        discovery = asyncio.run(
            use_case.get_service_available_slots("svc-discovery", TUE)
        )
        salt = asyncio.run(use_case.get_service_available_slots("svc-salt", TUE))
    assert "15:00" not in [s["start_time"] for s in discovery]
    assert {"start_time": "15:00", "end_time": "15:45"} in salt


def test_flag_true_cancel_clears_booking_busy():
    use_case, booking_repo, busy_col = _build_use_case()
    booking_id = "b-cancel-busy"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-discovery",
        "status": "pending",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:30"},
        "total_price": 0,
    }
    with patch.object(settings, "multi_resource_scheduling", True):
        asyncio.run(
            use_case.confirm_booking(booking_id=booking_id, user_id="u-cust")
        )
        assert any(r.get("booking_id") == booking_id for r in busy_col.rows)
        asyncio.run(
            use_case.cancel_booking(
                booking_id=booking_id, user_id="u-cust", is_admin=True
            )
        )
    assert not any(r.get("booking_id") == booking_id for r in busy_col.rows)


def test_flag_true_confirm_rechecks_busy_and_dual_writes():
    use_case, booking_repo, busy_col = _build_use_case()
    booking_id = "b-confirm-1"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "pending",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "resource_id": RES_SALT,
        "total_price": 45,
    }

    with patch.object(settings, "multi_resource_scheduling", True):
        result = asyncio.run(
            use_case.confirm_booking(booking_id=booking_id, user_id="u-cust")
        )

    assert result["status"] == "confirmed"
    assert result["resource_id"] == RES_SALT
    assert result["occupied_start_time"] == "15:00"
    assert result["occupied_end_time"] == "16:00"  # 45 + 15 cleanup
    written = [
        r
        for r in busy_col.rows
        if r.get("booking_id") == booking_id and r.get("resource_id") == RES_SALT
    ]
    assert len(written) == 1
    assert written[0]["start_time"] == "15:00"
    assert written[0]["end_time"] == "16:00"
    assert written[0]["source"] == "booking"


def test_flag_true_confirm_fails_when_resource_became_busy():
    use_case, booking_repo, _ = _build_use_case(
        busy_rows=[
            {
                "resource_id": RES_SALT,
                "date": TUE,
                "start_time": "15:00",
                "end_time": "16:00",
                "show_as": "busy",
                "authoritative": True,
            }
        ]
    )
    booking_id = "b-confirm-2"
    booking_repo.docs[booking_id] = {
        "booking_id": booking_id,
        "customer_id": "u-cust",
        "practitioner_id": "p1",
        "service_id": "svc-salt",
        "status": "pending",
        "slot": {"date": TUE, "start_time": "15:00", "end_time": "15:45"},
        "resource_id": RES_SALT,
        "total_price": 45,
    }
    with patch.object(settings, "multi_resource_scheduling", True):
        with pytest.raises(ValueError, match="no longer available"):
            asyncio.run(
                use_case.confirm_booking(booking_id=booking_id, user_id="u-cust")
            )


def test_compute_session_slots_uses_resource_not_other_busy():
    """Pure helper: only passed busy applies (Discovery≠Salt invariant)."""
    service = _services()["svc-salt"]
    resource = _salt_resource()
    slots = compute_session_slots(
        date_str=TUE,
        service=service,
        resource=resource,
        busy_intervals=[],  # Nichole busy must not be passed
    )
    assert {"start_time": "15:00", "end_time": "15:45"} in slots
