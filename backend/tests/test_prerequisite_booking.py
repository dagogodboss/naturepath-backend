"""Booking gate for the admin prerequisite service and per-service switch."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta

import pytest

from application.booking_policy import coerce_service_policy_updates, set_prerequisite_service
from application.use_cases.booking_use_case import BookingUseCase
from presentation.api.service_routes import _annotate_booking_lock, _discovery_gate_active


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=None):
        return list(self._rows)


class _StateCollection:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query, projection=None):
        row = self.rows.get(query["state_key"])
        return deepcopy(row) if row else None

    async def update_one(self, query, update, upsert=False):
        key = query["state_key"]
        row = self.rows.get(key, {"state_key": key})
        row.update(update.get("$set", {}))
        self.rows[key] = row


class _SettingsCollection:
    def __init__(self, service_id):
        self.doc = {"key": "booking_policy", "prerequisite_service_id": service_id}

    async def find_one(self, query, projection=None):
        if query.get("key") == "booking_policy":
            return dict(self.doc)
        return None

    async def update_one(self, query, update, upsert=False):
        self.doc.update(update.get("$set", {}))


class _BookingCollection:
    def __init__(self, state_collection, settings):
        self.database = type(
            "DB",
            (),
            {"booking_assignment_state": state_collection, "site_settings": settings},
        )()


class FakeBookingRepo:
    def __init__(self, settings):
        self.docs = {}
        self.collection = _BookingCollection(_StateCollection(), settings)

    async def create(self, entity):
        self.docs[entity["booking_id"]] = deepcopy(entity)
        return deepcopy(entity)

    async def get_by_id(self, booking_id):
        row = self.docs.get(booking_id)
        return deepcopy(row) if row else None

    async def get_by_customer(self, customer_id):
        return [deepcopy(row) for row in self.docs.values() if row.get("customer_id") == customer_id]

    async def update(self, booking_id, data):
        self.docs[booking_id].update(data)
        return deepcopy(self.docs[booking_id])


class FakeServiceRepo:
    def __init__(self, services):
        self.services = services

    async def get_by_id(self, service_id):
        row = self.services.get(service_id)
        return deepcopy(row) if row else None


class FakePractitionerRepo:
    def __init__(self, practitioners):
        self.practitioners = practitioners

    async def get_by_service(self, service_id):
        return [
            deepcopy(row)
            for row in self.practitioners.values()
            if service_id in row.get("services", [])
        ]

    async def get_by_id(self, practitioner_id):
        row = self.practitioners.get(practitioner_id)
        return deepcopy(row) if row else None


class FakeUserRepo:
    def __init__(self, users):
        self.users = users

    async def get_by_id(self, user_id):
        row = self.users.get(user_id)
        return deepcopy(row) if row else None

    async def update(self, user_id, updates):
        self.users.setdefault(user_id, {"user_id": user_id}).update(updates)


class FakeSlotRepo:
    async def get_available_slots(self, practitioner_id, date):
        return []

    async def list_slot_windows_for_practitioner_date(self, practitioner_id, date):
        return []


class _EventRepo:
    async def store_event(self, event):
        return event


class _SlotCollection:
    def find(self, query, projection=None):
        return _Cursor([])


def _services():
    rows = {
        "disc": {
            "service_id": "disc",
            "name": "Discovery Call",
            "price": 30,
            "is_active": True,
            "is_discovery_entry": True,
            "is_prerequisite": True,
            "requires_prerequisite": False,
            "requires_discovery": False,
        },
        "salt": {
            "service_id": "salt",
            "name": "Salt Session (Halotherapy)",
            "price": 25,
            "is_active": True,
            "requires_prerequisite": False,
            "requires_discovery": False,
        },
        "edu": {
            "service_id": "edu",
            "name": "Natural Health Education Hour",
            "price": 80,
            "is_active": True,
            "requires_prerequisite": False,
            "requires_discovery": False,
        },
        "well": {
            "service_id": "well",
            "name": "Wellness Consultation",
            "price": 175,
            "is_active": True,
            "requires_prerequisite": True,
            "requires_discovery": True,
        },
        "ext": {
            "service_id": "ext",
            "name": "2-Hours Extended Consultation",
            "price": 300,
            "is_active": True,
            "requires_prerequisite": True,
            "requires_discovery": True,
        },
        "follow": {
            "service_id": "follow",
            "name": "Follow-up Consultation",
            "price": 75,
            "is_active": True,
            "requires_prerequisite": True,
            "requires_discovery": True,
        },
        "lab": {
            "service_id": "lab",
            "name": "Direct-to-Consumer Lab Testing",
            "price": 75,
            "is_active": True,
            "requires_prerequisite": True,
            "requires_discovery": True,
        },
    }
    return rows


def _next_friday() -> str:
    from core.time_utils import clinic_now

    today = clinic_now().date()
    return (today + timedelta(days=(4 - today.weekday()) % 7)).isoformat()


def _build(customer=None, prerequisite_id="disc"):
    services = _services()
    settings = _SettingsCollection(prerequisite_id)
    users = {
        "staff-1": {"user_id": "staff-1", "is_active": True, "role": "practitioner"},
    }
    if customer:
        users[customer["user_id"]] = customer
    practitioner = {
        "practitioner_id": "p1",
        "user_id": "staff-1",
        "services": list(services),
        "availability": [
            {"day_of_week": 4, "start_time": "09:00", "end_time": "12:00", "is_available": True}
        ],
    }
    booking_repo = FakeBookingRepo(settings)
    use_case = BookingUseCase(
        booking_repo=booking_repo,
        slot_repo=FakeSlotRepo(),
        service_repo=FakeServiceRepo(services),
        practitioner_repo=FakePractitionerRepo({"p1": practitioner}),
        user_repo=FakeUserRepo(users),
        payment_repo=object(),
        event_repo=_EventRepo(),
        cache=None,
    )
    # Slot repo collection is unused; outlook lookup uses booking db.
    use_case.slot_repo.collection = _SlotCollection()
    return use_case, services, settings, users


def _run(coro):
    return asyncio.run(coro)


def _book(use_case, customer_id, service_id, topics=None):
    return _run(
        use_case.initiate_booking(
            customer_id,
            service_id,
            None,
            _next_friday(),
            "09:00",
            "10:00",
            education_topics=topics,
        )
    )


def _customer(completed=False, completed_service_id=None):
    user = {"user_id": "c1", "role": "customer", "is_discovery_completed": completed}
    if completed_service_id:
        user["prerequisite_completed_service_id"] = completed_service_id
    return user


def test_guest_can_book_salt_and_education_without_discovery():
    guest_gate = True
    salt = _annotate_booking_lock(_services()["salt"], guest_gate, "disc")
    education = _annotate_booking_lock(_services()["edu"], guest_gate, "disc")
    assert salt["booking_locked"] is False
    assert education["booking_locked"] is False
    use_case, _, _, _ = _build()
    salt_booking = _book(use_case, "guest-user", "salt")
    education_booking = _book(
        use_case,
        "guest-user",
        "edu",
        topics=["sleep", "nutrition", "stress"],
    )
    assert salt_booking["service_id"] == "salt"
    assert education_booking["service_id"] == "edu"


def test_guest_cannot_book_a_gated_consult():
    locked = _annotate_booking_lock(_services()["well"], True, "disc")
    assert locked["booking_locked"] is True
    use_case, _, _, _ = _build()
    with pytest.raises(ValueError, match="Discovery call required"):
        _book(use_case, "guest-user", "well")


def test_authenticated_without_prerequisite_matches_guest_lock():
    user = {"user_id": "c1", "role": "customer"}
    booking_uc = type("U", (), {})()
    booking_uc.get_discovery_eligibility = _async_return({"state": "none"})
    assert _run(_discovery_gate_active(user, booking_uc)) is True
    assert _run(_discovery_gate_active(None, booking_uc)) is True
    use_case, _, _, _ = _build(_customer(False))
    _book(use_case, "c1", "salt")
    _book(use_case, "c1", "edu", topics=["a", "b", "c"])
    with pytest.raises(ValueError, match="Discovery call required"):
        _book(use_case, "c1", "well")


def test_authenticated_with_prerequisite_completed_can_book_gated_consult():
    user = {"user_id": "c1", "role": "customer"}
    booking_uc = type("U", (), {})()
    booking_uc.get_discovery_eligibility = _async_return({"state": "completed"})
    assert _run(_discovery_gate_active(user, booking_uc)) is False
    use_case, _, _, _ = _build(_customer(True, "disc"))
    booking = _book(use_case, "c1", "well")
    assert booking["service_id"] == "well"
    follow = _book(use_case, "c1", "follow")
    lab = _book(use_case, "c1", "lab")
    assert follow["service_id"] == "follow"
    assert lab["service_id"] == "lab"


def test_prerequisite_service_itself_stays_bookable():
    forced = _annotate_booking_lock(
        {**_services()["disc"], "requires_prerequisite": True},
        True,
        "disc",
    )
    assert forced["booking_locked"] is False
    assert forced["requires_prerequisite"] is False
    use_case, services, _, _ = _build()
    services["disc"]["requires_prerequisite"] = True
    booking = _book(use_case, "c1", "disc")
    assert booking["service_id"] == "disc"


def test_admin_can_change_prerequisite_and_the_booking_api_honors_it():
    class ServiceUseCase:
        def __init__(self, rows):
            self.rows = rows

        async def get_all_services(self, active_only=False):
            return list(self.rows.values())

        async def update_service(self, service_id, **updates):
            self.rows[service_id].update(updates)
            return self.rows[service_id]

    class Services:
        def __init__(self, rows):
            self.rows = rows

        def find(self, query, projection=None):
            rows = list(self.rows.values())

            class Cursor:
                async def to_list(self, length=None):
                    return rows

            return Cursor()

    rows = _services()
    settings = _SettingsCollection("disc")

    class DB:
        def __init__(self):
            self.site_settings = settings
            self.services = Services(rows)

    saved = _run(set_prerequisite_service(DB(), "edu", service_use_case=ServiceUseCase(rows)))
    assert saved["prerequisite_service_id"] == "edu"
    assert rows["edu"]["is_prerequisite"] is True
    assert rows["edu"]["requires_prerequisite"] is False
    assert rows["disc"]["is_prerequisite"] is False

    updates = coerce_service_policy_updates(
        {"requires_prerequisite": True},
        "salt",
        "edu",
    )
    rows["salt"].update(updates)
    assert rows["salt"]["requires_prerequisite"] is True

    forced = coerce_service_policy_updates(
        {"requires_prerequisite": True},
        "edu",
        "edu",
    )
    assert forced["requires_prerequisite"] is False

    use_case, services, live_settings, users = _build(_customer(True, "disc"), prerequisite_id="edu")
    services["salt"]["requires_prerequisite"] = True
    services["edu"]["is_prerequisite"] = True
    services["edu"]["requires_prerequisite"] = False
    services["disc"]["is_prerequisite"] = False
    live_settings.doc["prerequisite_service_id"] = "edu"

    with pytest.raises(ValueError, match="Discovery call required"):
        _book(use_case, "c1", "salt")
    with pytest.raises(ValueError, match="Discovery call required"):
        _book(use_case, "c1", "well")

    education = _book(use_case, "c1", "edu", topics=["labs", "sleep", "food"])
    _run(use_case.booking_repo.update(education["booking_id"], {"status": "confirmed"}))
    _run(use_case.mark_discovery_completed(education["booking_id"], "staff-1", as_admin=False))
    assert users["c1"]["is_discovery_completed"] is True
    assert users["c1"]["prerequisite_completed_service_id"] == "edu"

    wellness = _book(use_case, "c1", "well")
    assert wellness["service_id"] == "well"


def test_existing_gated_flag_still_blocks_and_service_rows_keep_their_identity():
    wellness = _annotate_booking_lock(_services()["well"], True, "disc")
    assert wellness["booking_locked"] is True
    assert wellness["service_id"] == "well"
    assert wellness["name"] == "Wellness Consultation"
    use_case, _, _, _ = _build(_customer(False))
    for service_id in ("well", "ext", "follow", "lab"):
        with pytest.raises(ValueError, match="Discovery call required"):
            _book(use_case, "c1", service_id)


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner
