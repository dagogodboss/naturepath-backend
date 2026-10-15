from application.practitioner_schedule_services import (
    merge_service_ids,
    practitioner_has_weekly_schedule,
    sync_active_services_onto_scheduled_practitioners,
)


def test_practitioner_has_weekly_schedule_requires_open_window():
    assert practitioner_has_weekly_schedule(
        {
            "availability": [
                {
                    "day_of_week": 1,
                    "start_time": "10:30",
                    "end_time": "16:30",
                    "is_available": True,
                }
            ]
        }
    )
    assert not practitioner_has_weekly_schedule({"availability": []})
    assert not practitioner_has_weekly_schedule(
        {
            "availability": [
                {
                    "day_of_week": 1,
                    "start_time": "10:30",
                    "end_time": "16:30",
                    "is_available": False,
                }
            ]
        }
    )


def test_merge_service_ids_keeps_stable_union():
    assert merge_service_ids(["a", "b"], ["b", "c"]) == ["a", "b", "c"]
    assert merge_service_ids(None, ["x"]) == ["x"]


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def __aiter__(self):
        self._iter = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _Collection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection=None):
        return _Cursor(self.rows)

    async def update_one(self, query, update):
        pid = query["practitioner_id"]
        for row in self.rows:
            if row.get("practitioner_id") == pid:
                row.update(update.get("$set", {}))
                return


class _DB:
    def __init__(self, services, practitioners):
        self.services = _Collection(services)
        self.practitioners = _Collection(practitioners)


async def _run_sync():
    db = _DB(
        services=[
            {"service_id": "disc"},
            {"service_id": "salt"},
            {"service_id": "edu"},
        ],
        practitioners=[
            {
                "practitioner_id": "p1",
                "services": ["edu"],
                "availability": [
                    {
                        "day_of_week": 2,
                        "start_time": "10:30",
                        "end_time": "16:30",
                        "is_available": True,
                    }
                ],
            },
            {
                "practitioner_id": "p2",
                "services": [],
                "availability": [],
            },
        ],
    )
    result = await sync_active_services_onto_scheduled_practitioners(db)
    assert result["service_count"] == 3
    assert result["practitioners_updated"] == 1
    assert db.practitioners.rows[0]["services"] == ["edu", "disc", "salt"]
    assert db.practitioners.rows[1]["services"] == []


def test_sync_active_services_onto_scheduled_practitioners():
    import asyncio

    asyncio.run(_run_sync())
