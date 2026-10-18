"""Phase 4 scheduling admin API — flag gating + empty-DB behavior."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from presentation.api import scheduling_admin_routes as routes


def _cursor(items):
    cur = MagicMock()
    cur.to_list = AsyncMock(return_value=items)
    return cur


def _db(
    *,
    resources=None,
    services=None,
    connections=None,
    busy_intervals=None,
    review_queue=None,
    bookings=None,
):
    resources = resources if resources is not None else []
    services = services if services is not None else []
    connections = connections if connections is not None else []
    busy_intervals = busy_intervals if busy_intervals is not None else []
    review_queue = review_queue if review_queue is not None else []
    bookings = bookings if bookings is not None else []

    resources_by_id = {r["resource_id"]: r for r in resources if "resource_id" in r}
    services_by_id = {s["service_id"]: s for s in services if "service_id" in s}
    connections_by_id = {
        c["connection_id"]: c for c in connections if "connection_id" in c
    }

    resources_col = SimpleNamespace(
        find=MagicMock(return_value=_cursor(list(resources))),
        find_one=AsyncMock(
            side_effect=lambda q, *a, **k: resources_by_id.get(q.get("resource_id"))
        ),
        update_one=AsyncMock(),
    )
    services_col = SimpleNamespace(
        find_one=AsyncMock(
            side_effect=lambda q, *a, **k: services_by_id.get(q.get("service_id"))
        ),
        update_one=AsyncMock(),
    )
    outlook_col = SimpleNamespace(
        find_one=AsyncMock(
            side_effect=lambda q, *a, **k: connections_by_id.get(q.get("connection_id"))
        ),
        update_one=AsyncMock(),
        find=MagicMock(return_value=_cursor(list(connections))),
    )
    busy_by_id = {b["interval_id"]: dict(b) for b in busy_intervals if b.get("interval_id")}

    async def _busy_find_one(query, *a, **k):
        iid = query.get("interval_id")
        if iid:
            row = busy_by_id.get(iid)
            return dict(row) if row else None
        return None

    async def _busy_replace_one(query, doc, upsert=False):
        iid = query.get("interval_id") or doc.get("interval_id")
        busy_by_id[iid] = dict(doc)
        for i, b in enumerate(busy_intervals):
            if b.get("interval_id") == iid:
                busy_intervals[i] = dict(doc)
                return
        busy_intervals.append(dict(doc))

    busy_col = SimpleNamespace(
        find=MagicMock(
            side_effect=lambda q, *a, **k: _cursor(
                [
                    b
                    for b in busy_intervals
                    if b.get("resource_id") == q.get("resource_id")
                    and b.get("date") == q.get("date")
                ]
            )
        ),
        find_one=AsyncMock(side_effect=_busy_find_one),
        replace_one=AsyncMock(side_effect=_busy_replace_one),
    )
    async def _review_find_one(query, *a, **k):
        for r in review_queue:
            if query.get("review_id") and r.get("review_id") != query.get("review_id"):
                continue
            if query.get("booking_id") and r.get("booking_id") != query.get("booking_id"):
                continue
            if query.get("type") and r.get("type") != query.get("type"):
                continue
            if query.get("status") and r.get("status") != query.get("status"):
                continue
            if query.get("resource_id") and r.get("resource_id") != query.get("resource_id"):
                continue
            if query.get("event_id") and r.get("event_id") != query.get("event_id"):
                continue
            slot_date = query.get("payload.slot.date")
            if slot_date:
                payload = r.get("payload") or {}
                slot = payload.get("slot") or {}
                if slot.get("date") != slot_date:
                    continue
            slot_start = query.get("payload.slot.start_time")
            if slot_start:
                payload = r.get("payload") or {}
                slot = payload.get("slot") or {}
                if slot.get("start_time") != slot_start:
                    continue
            block_start = query.get("payload.blocking_interval.start_time")
            if block_start:
                payload = r.get("payload") or {}
                blocking = payload.get("blocking_interval") or {}
                if blocking.get("start_time") != block_start:
                    continue
            return dict(r)
        return None

    async def _review_update_one(query, update, *a, **k):
        rid = query.get("review_id")
        for i, r in enumerate(review_queue):
            if r.get("review_id") == rid:
                review_queue[i] = {**r, **update.get("$set", {})}
                return

    async def _review_insert_one(doc):
        review_queue.append(dict(doc))

    review_col = SimpleNamespace(
        find=MagicMock(
            side_effect=lambda q, *a, **k: _cursor(
                [
                    r
                    for r in review_queue
                    if not q.get("status") or r.get("status") == q.get("status")
                ]
            )
        ),
        find_one=AsyncMock(side_effect=_review_find_one),
        update_one=AsyncMock(side_effect=_review_update_one),
        insert_one=AsyncMock(side_effect=_review_insert_one),
        count_documents=AsyncMock(
            side_effect=lambda q: sum(
                1
                for r in review_queue
                if not q.get("status") or r.get("status") == q.get("status")
            )
        ),
    )

    class _BookingsCursor:
        def __init__(self, items):
            self._items = items

        async def to_list(self, length=500):
            return list(self._items)

    bookings_by_id = {
        b["booking_id"]: b for b in bookings if b.get("booking_id")
    }

    async def _bookings_find_one(query, *a, **k):
        bid = query.get("booking_id")
        if bid:
            row = bookings_by_id.get(bid)
            return dict(row) if row else None
        return None

    bookings_col = SimpleNamespace(
        find=MagicMock(
            side_effect=lambda q, *a, **k: _BookingsCursor(
                [
                    b
                    for b in bookings
                    if (not q.get("status") or b.get("status") == q.get("status"))
                    and (
                        not q.get("resource_id")
                        or b.get("resource_id") == q.get("resource_id")
                    )
                    and (
                        not q.get("service_id")
                        or b.get("service_id") == q.get("service_id")
                    )
                    and (
                        not q.get("slot.date")
                        or (b.get("slot") or {}).get("date") == q.get("slot.date")
                    )
                ]
            )
        ),
        find_one=AsyncMock(side_effect=_bookings_find_one),
    )
    return SimpleNamespace(
        resources=resources_col,
        services=services_col,
        outlook_calendar_connections=outlook_col,
        resource_busy_intervals=busy_col,
        review_queue=review_col,
        bookings=bookings_col,
        _resources_by_id=resources_by_id,
        _services_by_id=services_by_id,
        _connections_by_id=connections_by_id,
        _busy_by_id=busy_by_id,
        _review_queue_list=review_queue,
    )


CTX = {"user": {"user_id": "admin-1", "role": "owner"}, "practitioner": None}


@pytest.mark.asyncio
async def test_flag_false_list_resources_returns_404():
    db = _db()
    with patch.object(routes.settings, "multi_resource_scheduling", False):
        with pytest.raises(HTTPException) as exc:
            await routes.list_resources(ctx=CTX, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_flag_false_all_mutating_and_explain_return_404():
    db = _db()
    with patch.object(routes.settings, "multi_resource_scheduling", False):
        cases = [
            routes.update_resource(
                "r1",
                routes.ResourceUpdate(weekly_hours=[]),
                ctx=CTX,
                db=db,
            ),
            routes.get_service_scheduling("s1", ctx=CTX, db=db),
            routes.patch_service_scheduling(
                "s1",
                routes.ServiceSchedulingUpdate(prep_minutes=0),
                ctx=CTX,
                db=db,
            ),
            routes.get_outlook_category_maps("c1", ctx=CTX, db=db),
            routes.list_outlook_connections(ctx=CTX, db=db),
            routes.get_locked_outlook_connection_templates(
                nichole_resource_id="r-n",
                salt_resource_id="r-s",
                ctx=CTX,
            ),
            routes.put_outlook_category_maps(
                "c1",
                routes.CategoryMapsPut(category_maps=[]),
                ctx=CTX,
                db=db,
            ),
            routes.explain_availability(
                service_id="s1", date="2026-10-20", ctx=CTX, db=db
            ),
            routes.list_review_queue(ctx=CTX, db=db),
            routes.upsert_manual_busy_interval(
                "r1",
                "int-1",
                routes.ManualBusyIntervalUpsert(
                    date="2026-10-20", start_time="10:00", end_time="11:00"
                ),
                ctx=CTX,
                db=db,
            ),
            routes.create_manual_busy_interval(
                "r1",
                routes.ManualBusyIntervalUpsert(
                    date="2026-10-20", start_time="10:00", end_time="11:00"
                ),
                ctx=CTX,
                db=db,
            ),
        ]
        for coro in cases:
            with pytest.raises(HTTPException) as exc:
                await coro
            assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_flag_true_empty_resources_returns_empty_list():
    db = _db(resources=[])
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.list_resources(ctx=CTX, db=db)
    assert result == {"items": []}


@pytest.mark.asyncio
async def test_flag_true_locked_outlook_templates_include_clients_mailbox():
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.get_locked_outlook_connection_templates(
            nichole_resource_id="res-nichole",
            salt_resource_id="res-salt",
            ctx=CTX,
        )
    clients = result["templates"]["clients_salt_authoritative"]
    assert clients["mailbox_email"] == "Clients@thenaturalpathla.com"
    assert clients["authoritative_for_resource_ids"] == ["res-salt"]


@pytest.mark.asyncio
async def test_flag_true_patch_resource_missing_returns_404():
    db = _db(resources=[])
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        with pytest.raises(HTTPException) as exc:
            await routes.update_resource(
                "missing",
                routes.ResourceUpdate(weekly_hours=[]),
                ctx=CTX,
                db=db,
            )
    assert exc.value.status_code == 404
    assert "Resource" in exc.value.detail


@pytest.mark.asyncio
async def test_flag_true_patch_resource_empty_body_validation_error():
    db = _db(
        resources=[
            {
                "resource_id": "r1",
                "type": "room",
                "name": "Salt room",
                "weekly_hours": [],
            }
        ]
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        with pytest.raises(HTTPException) as exc:
            await routes.update_resource(
                "r1",
                routes.ResourceUpdate(),
                ctx=CTX,
                db=db,
            )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_flag_true_patch_resource_weekly_hours():
    existing = {
        "resource_id": "r1",
        "type": "room",
        "name": "Salt room",
        "timezone": "America/Chicago",
        "active": True,
        "weekly_hours": [],
    }
    db = _db(resources=[existing])

    async def _find_one_after_update(q, *a, **k):
        rid = q.get("resource_id")
        return db._resources_by_id.get(rid)

    async def _update_one(q, update):
        rid = q.get("resource_id")
        db._resources_by_id[rid] = {**db._resources_by_id[rid], **update["$set"]}

    db.resources.update_one = AsyncMock(side_effect=_update_one)
    db.resources.find_one = AsyncMock(side_effect=_find_one_after_update)

    hours = [
        routes.PractitionerAvailability(
            day_of_week=1, start_time="10:00", end_time="17:00"
        )
    ]
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.update_resource(
            "r1",
            routes.ResourceUpdate(weekly_hours=hours),
            ctx=CTX,
            db=db,
        )
    assert result["resource_id"] == "r1"
    assert len(result["weekly_hours"]) == 1
    assert result["weekly_hours"][0]["day_of_week"] == 1


@pytest.mark.asyncio
async def test_flag_true_service_scheduling_missing_404():
    db = _db(services=[])
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        with pytest.raises(HTTPException) as exc:
            await routes.get_service_scheduling("s-missing", ctx=CTX, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_flag_true_patch_service_unknown_resource_422():
    db = _db(
        services=[
            {
                "service_id": "s1",
                "name": "Discovery Call",
                "duration_minutes": 30,
                "prep_minutes": 0,
                "recovery_minutes": 0,
            }
        ],
        resources=[],
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        with pytest.raises(HTTPException) as exc:
            await routes.patch_service_scheduling(
                "s1",
                routes.ServiceSchedulingUpdate(required_resource_id="no-such"),
                ctx=CTX,
                db=db,
            )
    assert exc.value.status_code == 422
    assert "required_resource_id" in exc.value.detail


@pytest.mark.asyncio
async def test_flag_true_list_outlook_connections_excludes_secrets():
    db = _db(
        connections=[
            {
                "connection_id": "c1",
                "microsoft_email": "nichole@example.com",
                "authoritative_for_resource_ids": ["r-n"],
                "visibility_only": False,
                "last_sync_status": "ok",
                "last_synced_at": "2026-10-01T12:00:00+00:00",
                "refresh_token_encrypted": "must-not-leak",
                "category_maps": [{"category_name": "Salt", "resource_ids": ["r1"]}],
            },
            {
                "connection_id": "c2",
                "mailbox_email": "Clients@thenaturalpathla.com",
                "visibility_only": True,
                "is_active": True,
            },
        ]
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.list_outlook_connections(ctx=CTX, db=db)
    assert len(result["items"]) == 2
    by_id = {i["connection_id"]: i for i in result["items"]}
    assert "refresh_token_encrypted" not in by_id["c1"]
    assert by_id["c1"]["mailbox_email"] == "nichole@example.com"
    assert by_id["c1"]["authoritative_for_resource_ids"] == ["r-n"]
    assert by_id["c1"]["last_sync_status"] == "ok"
    assert by_id["c1"]["category_map_count"] == 1
    assert by_id["c2"]["mailbox_email"] == "Clients@thenaturalpathla.com"
    assert by_id["c2"]["visibility_only"] is True


@pytest.mark.asyncio
async def test_flag_true_patch_resource_last_start_time():
    existing = {
        "resource_id": "r1",
        "type": "room",
        "name": "Salt room",
        "weekly_hours": [],
        "last_start_time": None,
    }
    db = _db(resources=[existing])

    async def _find_one_after_update(q, *a, **k):
        return db._resources_by_id.get(q.get("resource_id"))

    async def _update_one(q, update):
        rid = q.get("resource_id")
        db._resources_by_id[rid] = {**db._resources_by_id[rid], **update["$set"]}

    db.resources.update_one = AsyncMock(side_effect=_update_one)
    db.resources.find_one = AsyncMock(side_effect=_find_one_after_update)

    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.update_resource(
            "r1",
            routes.ResourceUpdate(last_start_time="17:00"),
            ctx=CTX,
            db=db,
        )
    assert result["last_start_time"] == "17:00"

    with patch.object(routes.settings, "multi_resource_scheduling", True):
        cleared = await routes.update_resource(
            "r1",
            routes.ResourceUpdate(last_start_time=""),
            ctx=CTX,
            db=db,
        )
    assert cleared["last_start_time"] is None


@pytest.mark.asyncio
async def test_flag_true_category_maps_missing_connection_404():
    db = _db(connections=[])
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        with pytest.raises(HTTPException) as exc:
            await routes.get_outlook_category_maps("c-missing", ctx=CTX, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_flag_true_put_category_maps_empty_ok():
    conn = {
        "connection_id": "c1",
        "category_maps": [{"category_name": "Salt", "resource_ids": ["r1"]}],
    }
    db = _db(connections=[conn])

    async def _update_one(q, update):
        cid = q.get("connection_id")
        db._connections_by_id[cid] = {
            **db._connections_by_id[cid],
            **update["$set"],
        }

    db.outlook_calendar_connections.update_one = AsyncMock(side_effect=_update_one)

    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.put_outlook_category_maps(
            "c1",
            routes.CategoryMapsPut(category_maps=[]),
            ctx=CTX,
            db=db,
        )
    assert result == {"connection_id": "c1", "category_maps": []}


@pytest.mark.asyncio
async def test_flag_true_explain_uses_real_explainer():
    # Tuesday Discovery with hours + no busy → available.
    db = _db(
        services=[
            {
                "service_id": "s1",
                "name": "Discovery Call",
                "duration_minutes": 30,
                "prep_minutes": 0,
                "recovery_minutes": 15,
                "flags": {"no_mondays": True},
                "required_resource_id": "r1",
            }
        ],
        resources=[
            {
                "resource_id": "r1",
                "type": "practitioner",
                "name": "Nichole",
                "weekly_hours": [
                    {
                        "day_of_week": 1,
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "is_available": True,
                    }
                ],
            }
        ],
        review_queue=[{"review_id": "rq1", "status": "open", "message": "x"}],
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.explain_availability(
            service_id="s1",
            date="2026-10-20",
            start="10:00",
            ctx=CTX,
            db=db,
        )
    assert result["phase"] == "explain"
    assert result["available"] is True
    assert result["reasons"] == []
    assert result["review_queue_open_count"] == 1
    assert result["resource_id"] == "r1"


@pytest.mark.asyncio
async def test_flag_true_explain_monday_discovery_closed():
    db = _db(
        services=[
            {
                "service_id": "s1",
                "duration_minutes": 30,
                "prep_minutes": 0,
                "recovery_minutes": 15,
                "flags": {"no_mondays": True},
                "required_resource_id": "r1",
            }
        ],
        resources=[
            {
                "resource_id": "r1",
                "weekly_hours": [
                    {
                        "day_of_week": 0,
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "is_available": True,
                    }
                ],
            }
        ],
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.explain_availability(
            service_id="s1",
            date="2026-10-19",
            start="10:00",
            ctx=CTX,
            db=db,
        )
    assert result["available"] is False
    assert any(r["code"] == "SERVICE_WEEKDAY_CLOSED" for r in result["reasons"])


@pytest.mark.asyncio
async def test_flag_true_explain_missing_service_404():
    db = _db(services=[])
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        with pytest.raises(HTTPException) as exc:
            await routes.explain_availability(
                service_id="missing", date="2026-10-20", ctx=CTX, db=db
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_flag_true_review_queue_list_stub():
    db = _db(
        review_queue=[
            {"review_id": "rq1", "status": "open", "message": "unmapped"},
            {"review_id": "rq2", "status": "resolved", "message": "done"},
        ]
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.list_review_queue(status_filter="open", ctx=CTX, db=db)
    assert result["phase"] == "list"
    assert len(result["items"]) == 1
    assert result["items"][0]["review_id"] == "rq1"


@pytest.mark.asyncio
async def test_flag_off_resolve_review_404():
    db = _db(review_queue=[{"review_id": "rq1", "status": "open", "message": "x"}])
    with patch.object(routes.settings, "multi_resource_scheduling", False):
        with pytest.raises(HTTPException) as exc:
            await routes.resolve_review_queue_item(
                review_id="rq1", body=routes.ReviewQueueResolveBody(), ctx=CTX, db=db
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_flag_true_resolve_review_queue_item():
    db = _db(
        review_queue=[
            {
                "review_id": "rq1",
                "status": "open",
                "message": "conflict",
                "payload": {},
            }
        ]
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.resolve_review_queue_item(
            review_id="rq1",
            body=routes.ReviewQueueResolveBody(note="handled"),
            ctx=CTX,
            db=db,
        )
    assert result["phase"] == "resolve"
    assert result["item"]["status"] == "resolved"
    assert result["item"]["payload"]["resolve_note"] == "handled"


@pytest.mark.asyncio
async def test_flag_true_dismiss_review_queue_item():
    db = _db(
        review_queue=[
            {"review_id": "rq1", "status": "open", "message": "x", "payload": {}}
        ]
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.dismiss_review_queue_item(
            review_id="rq1",
            body=routes.ReviewQueueDismissBody(reason="duplicate"),
            ctx=CTX,
            db=db,
        )
    assert result["item"]["status"] == "dismissed"
    assert result["item"]["payload"]["dismiss_reason"] == "duplicate"


@pytest.mark.asyncio
async def test_flag_true_manual_busy_upsert_persists_and_enqueues_sync_conflict():
    db = _db(
        resources=[{"resource_id": "r1", "type": "room", "name": "Salt"}],
        bookings=[
            {
                "booking_id": "b1",
                "status": "confirmed",
                "resource_id": "r1",
                "occupied_start_time": "15:00",
                "occupied_end_time": "16:00",
                "slot": {"date": "2026-10-20", "start_time": "15:00", "end_time": "15:45"},
            }
        ],
    )
    body = routes.ManualBusyIntervalUpsert(
        date="2026-10-20",
        start_time="15:00",
        end_time="16:00",
        note="maintenance hold",
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.upsert_manual_busy_interval(
            "r1", "int-manual-1", body, ctx=CTX, db=db
        )
    assert result["phase"] == "manual_busy"
    assert result["sync_conflict_review_count"] == 1
    assert result["interval"]["source"] == "manual"
    assert db._busy_by_id["int-manual-1"]["start_time"] == "15:00"
    assert len(db._review_queue_list) == 1
    assert db._review_queue_list[0]["type"] == "sync_conflict"
    assert db._review_queue_list[0]["booking_id"] == "b1"

    with patch.object(routes.settings, "multi_resource_scheduling", True):
        again = await routes.upsert_manual_busy_interval(
            "r1", "int-manual-1", body, ctx=CTX, db=db
        )
    assert again["sync_conflict_review_count"] == 1
    assert len(db._review_queue_list) == 1


@pytest.mark.asyncio
async def test_flag_true_manual_busy_cannot_overwrite_outlook_interval():
    db = _db(
        resources=[{"resource_id": "r1", "type": "room", "name": "Salt"}],
        busy_intervals=[
            {
                "interval_id": "int-outlook",
                "resource_id": "r1",
                "date": "2026-10-20",
                "start_time": "15:00",
                "end_time": "16:00",
                "source": "outlook",
            }
        ],
    )
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        with pytest.raises(HTTPException) as exc:
            await routes.upsert_manual_busy_interval(
                "r1",
                "int-outlook",
                routes.ManualBusyIntervalUpsert(
                    date="2026-10-20", start_time="15:00", end_time="16:00"
                ),
                ctx=CTX,
                db=db,
            )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_flag_true_create_manual_busy_generates_interval_id():
    db = _db(resources=[{"resource_id": "r1", "type": "room", "name": "Salt"}])
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.create_manual_busy_interval(
            "r1",
            routes.ManualBusyIntervalUpsert(
                date="2026-10-20", start_time="09:00", end_time="10:00"
            ),
            ctx=CTX,
            db=db,
        )
    assert result["interval"]["interval_id"]
    assert result["sync_conflict_review_count"] == 0


@pytest.mark.asyncio
async def test_flag_true_patch_outlook_connection_settings():
    conn = {
        "connection_id": "c1",
        "microsoft_email": "n@example.com",
        "authoritative_for_resource_ids": [],
        "visibility_only": False,
        "is_active": True,
        "refresh_token_encrypted": "secret",
    }
    db = _db(
        connections=[conn],
        resources=[{"resource_id": "r1", "name": "Salt", "weekly_hours": []}],
    )

    async def _update_one(q, update):
        cid = q.get("connection_id")
        db._connections_by_id[cid] = {
            **db._connections_by_id[cid],
            **update["$set"],
        }

    async def _find_one_after(q, *a, **k):
        return db._connections_by_id.get(q.get("connection_id"))

    db.outlook_calendar_connections.update_one = AsyncMock(side_effect=_update_one)
    db.outlook_calendar_connections.find_one = AsyncMock(side_effect=_find_one_after)

    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.patch_outlook_connection_settings(
            "c1",
            routes.OutlookConnectionSettingsUpdate(
                authoritative_for_resource_ids=["r1"],
                visibility_only=True,
            ),
            ctx=CTX,
            db=db,
        )
    assert result["authoritative_for_resource_ids"] == ["r1"]
    assert result["visibility_only"] is True
    assert "refresh_token_encrypted" not in result


@pytest.mark.asyncio
async def test_flag_true_resource_schedule_change_preview_detects_booking():
    from datetime import date, timedelta

    future = (date.today() + timedelta(days=7)).isoformat()
    weekday = date.fromisoformat(future).weekday()
    db = _db(
        resources=[
            {
                "resource_id": "r1",
                "name": "Salt",
                "weekly_hours": [
                    {
                        "day_of_week": weekday,
                        "start_time": "09:00",
                        "end_time": "18:00",
                        "is_available": True,
                    }
                ],
                "last_start_time": "17:00",
            }
        ],
        services=[
            {
                "service_id": "s1",
                "duration_minutes": 60,
                "prep_minutes": 0,
                "recovery_minutes": 0,
            }
        ],
        bookings=[
            {
                "booking_id": "b1",
                "status": "confirmed",
                "resource_id": "r1",
                "service_id": "s1",
                "slot": {"date": future, "start_time": "16:00", "end_time": "17:00"},
            }
        ],
    )
    tighter_hours = [
        routes.PractitionerAvailability(
            day_of_week=weekday,
            start_time="09:00",
            end_time="15:00",
            is_available=True,
        )
    ]
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        preview = await routes.preview_resource_schedule_change(
            "r1",
            routes.ResourceUpdate(weekly_hours=tighter_hours),
            ctx=CTX,
            db=db,
        )
    assert preview["affected_count"] == 1
    assert preview["items"][0]["booking_id"] == "b1"


@pytest.mark.asyncio
async def test_flag_true_resource_patch_enqueues_schedule_change_review():
    from datetime import date, timedelta

    future = (date.today() + timedelta(days=7)).isoformat()
    weekday = date.fromisoformat(future).weekday()
    existing = {
        "resource_id": "r1",
        "name": "Salt",
        "weekly_hours": [
            {
                "day_of_week": weekday,
                "start_time": "09:00",
                "end_time": "18:00",
                "is_available": True,
            }
        ],
    }
    db = _db(
        resources=[existing],
        services=[
            {
                "service_id": "s1",
                "duration_minutes": 60,
                "prep_minutes": 0,
                "recovery_minutes": 0,
            }
        ],
        bookings=[
            {
                "booking_id": "b1",
                "status": "confirmed",
                "resource_id": "r1",
                "service_id": "s1",
                "slot": {"date": future, "start_time": "16:00", "end_time": "17:00"},
            }
        ],
    )

    async def _update_one(q, update):
        rid = q.get("resource_id")
        db._resources_by_id[rid] = {**db._resources_by_id[rid], **update["$set"]}

    async def _find_one_after(q, *a, **k):
        return db._resources_by_id.get(q.get("resource_id"))

    db.resources.update_one = AsyncMock(side_effect=_update_one)
    db.resources.find_one = AsyncMock(side_effect=_find_one_after)

    tighter_hours = [
        routes.PractitionerAvailability(
            day_of_week=weekday,
            start_time="09:00",
            end_time="15:00",
            is_available=True,
        )
    ]
    with patch.object(routes.settings, "multi_resource_scheduling", True):
        result = await routes.update_resource(
            "r1",
            routes.ResourceUpdate(weekly_hours=tighter_hours),
            preview=False,
            enqueue_reviews=True,
            ctx=CTX,
            db=db,
        )
    assert result["saved"] is True
    assert result["schedule_change_impact"]["affected_count"] == 1
    assert result["schedule_change_reviews_enqueued"] == 1
    assert len(db._review_queue_list) == 1
    assert db._review_queue_list[0]["type"] == "schedule_change_impact"
    assert db._review_queue_list[0]["booking_id"] == "b1"
