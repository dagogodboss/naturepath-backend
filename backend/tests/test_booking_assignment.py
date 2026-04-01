import asyncio
from copy import deepcopy

from application.use_cases.booking_use_case import BookingUseCase


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=None):
        if length is None:
            return list(self._rows)
        return list(self._rows)[:length]


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
        self.slot_docs = slot_docs

    def find(self, query, projection=None):
        rows = [
            deepcopy(r)
            for r in self.slot_docs
            if r["practitioner_id"] == query.get("practitioner_id")
            and r["date"] == query.get("date")
        ]
        return _Cursor(rows)


class _BookingCollection:
    def __init__(self, state_collection):
        self.database = type("DB", (), {"booking_assignment_state": state_collection})()


class FakeBookingRepo:
    def __init__(self, state_collection):
        self.docs = {}
        self.collection = _BookingCollection(state_collection)

    async def create(self, entity):
        self.docs[entity["booking_id"]] = deepcopy(entity)
        return deepcopy(entity)

    async def get_by_id(self, booking_id):
        return deepcopy(self.docs.get(booking_id))

    async def get_by_customer(self, customer_id):
        rows = [d for d in self.docs.values() if d.get("customer_id") == customer_id]
        return deepcopy(rows)


class FakeSlotRepo:
    def __init__(self, available_by_pid_date, slot_docs):
        self.available_by_pid_date = available_by_pid_date
        self.collection = _SlotCollection(slot_docs)

    async def get_available_slots(self, practitioner_id, date):
        return deepcopy(self.available_by_pid_date.get((practitioner_id, date), []))


class FakeServiceRepo:
    def __init__(self, services):
        self.services = services

    async def get_by_id(self, service_id):
        return deepcopy(self.services.get(service_id))


class FakePractitionerRepo:
    def __init__(self, practitioners):
        self.practitioners = practitioners

    async def get_by_service(self, service_id):
        return [deepcopy(p) for p in self.practitioners.values() if service_id in p.get("services", [])]

    async def get_by_id(self, practitioner_id):
        p = self.practitioners.get(practitioner_id)
        return deepcopy(p) if p else None


class FakeUserRepo:
    def __init__(self, users):
        self.users = users

    async def get_by_id(self, user_id):
        u = self.users.get(user_id)
        return deepcopy(u) if u else None

    async def update(self, user_id, updates):
        if user_id in self.users:
            self.users[user_id].update(updates)


class FakePaymentRepo:
    pass


class FakeEventRepo:
    async def store_event(self, event):
        return event


def _build_use_case(practitioners, users, services, available_by_pid_date, slot_docs=None):
    state = _StateCollection()
    booking_repo = FakeBookingRepo(state)
    slot_repo = FakeSlotRepo(available_by_pid_date, slot_docs or [])
    return (
        BookingUseCase(
            booking_repo=booking_repo,
            slot_repo=slot_repo,
            service_repo=FakeServiceRepo(services),
            practitioner_repo=FakePractitionerRepo(practitioners),
            user_repo=FakeUserRepo(users),
            payment_repo=FakePaymentRepo(),
            event_repo=FakeEventRepo(),
            cache=None,
        ),
        state,
    )


def test_single_practitioner_assignment_owner():
    service_id = "svc-1"
    date = "2026-04-03"
    use_case, _state = _build_use_case(
        practitioners={
            "p-owner": {
                "practitioner_id": "p-owner",
                "user_id": "u-owner",
                "services": [service_id],
                "availability": [{"day_of_week": 4, "start_time": "09:00", "end_time": "11:00", "is_available": True}],
            }
        },
        users={"u-owner": {"user_id": "u-owner", "is_active": True}},
        services={service_id: {"service_id": service_id, "name": "Discovery Call", "price": 100, "is_active": True}},
        available_by_pid_date={},
    )

    booking = asyncio.run(
        use_case.initiate_booking(
            customer_id="c-1",
            service_id=service_id,
            practitioner_id=None,
            date=date,
            start_time="09:00",
            end_time="10:00",
        )
    )
    assert booking["practitioner_id"] == "p-owner"


def test_round_robin_assignment_sequence():
    service_id = "svc-1"
    date = "2026-04-03"
    p1_slots = [{"start_time": "09:00", "end_time": "10:00"}]
    p2_slots = [{"start_time": "09:00", "end_time": "10:00"}]
    use_case, _state = _build_use_case(
        practitioners={
            "p1": {"practitioner_id": "p1", "user_id": "u1", "services": [service_id], "availability": []},
            "p2": {"practitioner_id": "p2", "user_id": "u2", "services": [service_id], "availability": []},
        },
        users={"u1": {"user_id": "u1", "is_active": True}, "u2": {"user_id": "u2", "is_active": True}},
        services={service_id: {"service_id": service_id, "name": "Discovery Call", "price": 100, "is_active": True}},
        available_by_pid_date={("p1", date): p1_slots, ("p2", date): p2_slots},
    )

    b1 = asyncio.run(
        use_case.initiate_booking("c1", service_id, None, date, "09:00", "10:00")
    )
    b2 = asyncio.run(
        use_case.initiate_booking("c2", service_id, None, date, "09:00", "10:00")
    )
    assert b1["practitioner_id"] == "p1"
    assert b2["practitioner_id"] == "p2"


def test_skip_unavailable_practitioner_for_slot():
    service_id = "svc-1"
    date = "2026-04-03"
    use_case, _state = _build_use_case(
        practitioners={
            "p1": {"practitioner_id": "p1", "user_id": "u1", "services": [service_id], "availability": []},
            "p2": {"practitioner_id": "p2", "user_id": "u2", "services": [service_id], "availability": []},
        },
        users={"u1": {"user_id": "u1", "is_active": True}, "u2": {"user_id": "u2", "is_active": True}},
        services={service_id: {"service_id": service_id, "name": "Discovery Call", "price": 100, "is_active": True}},
        available_by_pid_date={
            ("p1", date): [],
            ("p2", date): [{"start_time": "09:00", "end_time": "10:00"}],
        },
    )

    booking = asyncio.run(
        use_case.initiate_booking("c1", service_id, None, date, "09:00", "10:00")
    )
    assert booking["practitioner_id"] == "p2"


def test_no_availability_error():
    service_id = "svc-1"
    date = "2026-04-03"
    use_case, _state = _build_use_case(
        practitioners={
            "p1": {"practitioner_id": "p1", "user_id": "u1", "services": [service_id], "availability": []},
        },
        users={"u1": {"user_id": "u1", "is_active": True}},
        services={service_id: {"service_id": service_id, "name": "Discovery Call", "price": 100, "is_active": True}},
        available_by_pid_date={("p1", date): []},
        slot_docs=[{"slot_id": "s1", "practitioner_id": "p1", "date": date, "status": "booked"}],
    )

    try:
        asyncio.run(use_case.initiate_booking("c1", service_id, None, date, "09:00", "10:00"))
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "No practitioner available" in str(e)
