"""
Required real-Mongo concurrent acceptance for issue #9 (A2 + B1).

These tests are NOT optional residual hardening. They must run against a real
MongoDB (Motor). Set TEST_MONGO_URL or MONGO_URL. Missing Mongo fails the
suite — it does not skip.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from unittest.mock import AsyncMock, MagicMock, patch

from application.multi_resource_booking import fetch_resource_busy
from application.outlook_category_sync import persist_resource_busy_from_events
from application.outlook_sync import sync_outlook_connection
from application.resource_reservation import acquire_resource_reservation
from core.config import settings
from domain.multi_resource_defaults import (
    CATEGORY_SALT_LEGACY,
    CATEGORY_SALT_SESSION,
    build_nichole_authoritative_category_maps,
)

NICHOLE = "res-nichole-real"
SALT = "res-salt-real"


def _require_mongo_url() -> str:
    url = (
        os.environ.get("TEST_MONGO_URL")
        or os.environ.get("MONGO_URL")
        or os.environ.get("MONGODB_URL")
        or ""
    ).strip()
    if not url:
        pytest.fail(
            "Required real-Mongo gate: set TEST_MONGO_URL (or MONGO_URL) for "
            "concurrent A2/B1 acceptance tests. Do not skip — these are required."
        )
    return url


@pytest.fixture
async def real_db():
    url = _require_mongo_url()
    db_name = f"naturepath_concurrency_{uuid.uuid4().hex[:10]}"
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
    except Exception as exc:
        client.close()
        pytest.fail(
            f"Required real-Mongo gate: cannot ping Mongo at configured URL ({exc}). "
            "Do not skip — start Mongo or point TEST_MONGO_URL at a reachable instance."
        )
    db = client[db_name]
    try:
        yield db
    finally:
        await client.drop_database(db_name)
        client.close()


def _nichole_connection(connection_id: str = "conn-nichole-real") -> Dict[str, Any]:
    maps = [
        m.model_dump()
        for m in build_nichole_authoritative_category_maps(NICHOLE, SALT)
    ]
    return {
        "connection_id": connection_id,
        "visibility_only": False,
        "authoritative_for_resource_ids": [NICHOLE],
        "category_maps": maps,
        "visibility_copy_category_names": [
            CATEGORY_SALT_SESSION,
            CATEGORY_SALT_LEGACY,
        ],
        "auth_mode": "application",
        "mailbox_email": "nmoore@thenaturalpathla.com",
        "practitioner_id": "pract-nichole-real",
        "is_active": True,
    }


def _graph_event(
    *,
    event_id: str,
    categories: List[str] | None = None,
    start: str = "2026-10-20T15:00:00",
    end: str = "2026-10-20T16:00:00",
) -> dict:
    return {
        "id": event_id,
        "categories": categories or ["Discovery"],
        "showAs": "busy",
        "isCancelled": False,
        "subject": event_id,
        "start": {"dateTime": start, "timeZone": "America/Chicago"},
        "end": {"dateTime": end, "timeZone": "America/Chicago"},
    }


@pytest.mark.asyncio
async def test_a2_real_mongo_exactly_one_overlapping_reservation_winner(real_db):
    """Barrier-controlled concurrent overlapping Salt locks → exactly one winner."""
    db = real_db
    date_str = "2026-10-21"
    barrier = asyncio.Barrier(2)
    results: List[Any] = []

    async def contender(booking_id: str, occupied_start: str, occupied_end: str):
        await barrier.wait()
        try:
            doc = await acquire_resource_reservation(
                db,
                resource_id=SALT,
                date_str=date_str,
                occupied_start=occupied_start,
                occupied_end=occupied_end,
                booking_id=booking_id,
                owner_user_id=f"user-{booking_id}",
            )
            results.append(("ok", booking_id, doc))
        except ValueError as exc:
            results.append(("err", booking_id, str(exc)))

    await asyncio.gather(
        contender("bk-a", "15:00", "16:00"),
        contender("bk-b", "15:15", "16:15"),
    )

    wins = [r for r in results if r[0] == "ok"]
    losses = [r for r in results if r[0] == "err"]
    assert len(wins) == 1, f"expected exactly one winner, got {results}"
    assert len(losses) == 1, f"expected exactly one loser, got {results}"
    assert "no longer available" in losses[0][2]

    remaining = await db.resource_reservations.find(
        {"resource_id": SALT, "date": date_str}, {"_id": 0}
    ).to_list(20)
    assert len(remaining) == 1
    assert remaining[0]["booking_id"] == wins[0][1]
    assert remaining[0].get("acknowledged") is True


@pytest.mark.asyncio
async def test_a2_real_mongo_delayed_inserter_cannot_revoke_acknowledged_winner(
    real_db,
):
    """
    Codex A2 window: pause B after precheck before insert; A acquires and
    returns; resume B with a smaller reservation_id — A must survive.
    """
    import application.resource_reservation as rr

    db = real_db
    date_str = "2026-10-22"
    a_done = asyncio.Event()
    b_precheck_done = asyncio.Event()
    results: Dict[str, Any] = {}
    id_a = "zzzz-winner-a"
    id_b = "aaaa-delayed-b"

    async def pre_insert_hook(*, booking_id, resource_id, date_str):
        if booking_id == "bk-b":
            b_precheck_done.set()
            await a_done.wait()

    async def run_a():
        await b_precheck_done.wait()
        try:
            doc = await acquire_resource_reservation(
                db,
                resource_id=SALT,
                date_str=date_str,
                occupied_start="15:00",
                occupied_end="16:00",
                booking_id="bk-a",
                owner_user_id="user-a",
            )
            results["a"] = ("ok", doc)
        except ValueError as exc:
            results["a"] = ("err", str(exc))
        finally:
            a_done.set()

    async def run_b():
        try:
            doc = await acquire_resource_reservation(
                db,
                resource_id=SALT,
                date_str=date_str,
                occupied_start="15:15",
                occupied_end="16:15",
                booking_id="bk-b",
                owner_user_id="user-b",
            )
            results["b"] = ("ok", doc)
        except ValueError as exc:
            results["b"] = ("err", str(exc))

    # Disable day-lock so the exact precheck→insert interleaving is reachable;
    # fencing (not timing) must protect the acknowledged winner.
    async def no_day_lock(*_a, **_k):
        return None

    # generate_id order with gather(B, A) and B paused in pre-insert hook:
    # B lock_holder, A lock_holder, A reservation_id (larger), B reservation_id (smaller).
    seq = iter(["lock-b", "lock-a", id_a, id_b])

    def gen_id():
        try:
            return next(seq)
        except StopIteration:
            return uuid.uuid4().hex

    with patch.object(rr, "_acquire_day_lock", side_effect=no_day_lock), patch.object(
        rr, "_pre_insert_hook", pre_insert_hook
    ), patch.object(rr, "generate_id", side_effect=gen_id):
        await asyncio.gather(run_b(), run_a())

    assert results.get("a", ("?",))[0] == "ok", results
    assert results.get("b", ("?",))[0] == "err", results

    remaining = await db.resource_reservations.find(
        {"resource_id": SALT, "date": date_str}, {"_id": 0}
    ).to_list(20)
    assert len(remaining) == 1
    assert remaining[0]["booking_id"] == "bk-a"
    assert remaining[0].get("acknowledged") is True
    assert remaining[0]["reservation_id"] == id_a


@pytest.mark.asyncio
async def test_a2_real_mongo_delayed_inserter_cannot_revoke_confirmed(
    real_db,
):
    """Delayed pending insert must not prune an already-confirmed peer."""
    import application.resource_reservation as rr
    from application.resource_reservation import (
        RESERVATION_CONFIRMED,
        promote_reservation_confirmed,
    )

    db = real_db
    date_str = "2026-10-23"
    a_done = asyncio.Event()
    b_precheck_done = asyncio.Event()

    async def pre_insert_hook(*, booking_id, resource_id, date_str):
        if booking_id == "bk-b":
            b_precheck_done.set()
            await a_done.wait()

    async def no_day_lock(*_a, **_k):
        return None

    async def run_a():
        await b_precheck_done.wait()
        await acquire_resource_reservation(
            db,
            resource_id=SALT,
            date_str=date_str,
            occupied_start="15:00",
            occupied_end="16:00",
            booking_id="bk-a",
            owner_user_id="user-a",
            status=RESERVATION_CONFIRMED,
        )
        await promote_reservation_confirmed(
            db, booking_id="bk-a", resource_id=SALT
        )
        a_done.set()

    async def run_b():
        with pytest.raises(ValueError, match="no longer available"):
            await acquire_resource_reservation(
                db,
                resource_id=SALT,
                date_str=date_str,
                occupied_start="15:15",
                occupied_end="16:15",
                booking_id="bk-b",
                owner_user_id="user-b",
            )

    with patch.object(rr, "_acquire_day_lock", side_effect=no_day_lock), patch.object(
        rr, "_pre_insert_hook", pre_insert_hook
    ):
        await asyncio.gather(run_b(), run_a())

    remaining = await db.resource_reservations.find(
        {"resource_id": SALT, "date": date_str}, {"_id": 0}
    ).to_list(20)
    assert len(remaining) == 1
    assert remaining[0]["booking_id"] == "bk-a"
    assert remaining[0]["status"] == RESERVATION_CONFIRMED


@pytest.mark.asyncio
async def test_b1_real_mongo_overlapping_sync_preserves_newer_generation(real_db):
    """Concurrent persist: newer generation survives both cleanup orderings."""
    from application import outlook_category_sync as ocs

    db = real_db
    connection = _nichole_connection()
    await db.outlook_calendar_connections.insert_one(dict(connection))
    await db.resources.insert_many(
        [
            {"resource_id": NICHOLE, "active": True},
            {"resource_id": SALT, "active": True},
        ]
    )

    barrier = asyncio.Barrier(2)
    counter = {"n": 1000}
    results: List[Dict[str, Any]] = []
    original_claim = ocs._claim_busy_sync_generation

    def next_gen() -> int:
        counter["n"] += 1
        return counter["n"]

    async def claim_with_barrier(db_arg, connection_id, generation_arg):
        won = await original_claim(db_arg, connection_id, generation_arg)
        await barrier.wait()
        return won

    async def run_sync(event_id: str):
        meta = await persist_resource_busy_from_events(
            db,
            connection,
            [_graph_event(event_id=event_id, categories=["Discovery"])],
            clinic_timezone="America/Chicago",
            synced_at=datetime.now(timezone.utc),
        )
        results.append(meta)

    with patch.object(ocs, "_next_sync_generation", side_effect=next_gen), patch.object(
        ocs, "_claim_busy_sync_generation", side_effect=claim_with_barrier
    ):
        await asyncio.gather(run_sync("evt-a"), run_sync("evt-b"))

    conn = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection["connection_id"]}
    )
    active = int(conn["active_busy_generation"])
    assert active in (1001, 1002)
    assert any(r.get("skipped_stale_generation") is False for r in results)
    # Newer-or-equal winner's rows only — never a wiped dual-empty window.
    rows = await db.resource_busy_intervals.find(
        {"connection_id": connection["connection_id"], "source": "outlook"},
        {"_id": 0},
    ).to_list(50)
    assert rows, "overlapping syncs must not wipe all busy rows"
    assert {int(r["sync_generation"]) for r in rows} == {active}
    assert len({r.get("event_id") for r in rows}) == 1


@pytest.mark.asyncio
async def test_b1_real_mongo_busy_read_consistent_under_concurrent_claim(real_db):
    """
    Mid-read generation change must not yield false-empty busy.
    Seed gen1 busy, then claim gen2 during a read; reader retries / sees gen2.
    """
    from application import multi_resource_booking as mrb
    from application import outlook_category_sync as ocs

    db = real_db
    connection = _nichole_connection()
    connection["active_busy_generation"] = 1
    await db.outlook_calendar_connections.insert_one(dict(connection))
    await db.resources.insert_many(
        [
            {"resource_id": NICHOLE, "active": True},
            {"resource_id": SALT, "active": True},
        ]
    )
    date_str = "2026-10-20"
    await db.resource_busy_intervals.insert_one(
        {
            "resource_id": NICHOLE,
            "date": date_str,
            "start_time": "15:00",
            "end_time": "16:00",
            "connection_id": connection["connection_id"],
            "source": "outlook",
            "event_id": "gen1-busy",
            "sync_generation": 1,
        }
    )

    barrier = asyncio.Barrier(2)
    read_result: Dict[str, Any] = {}
    original_load = mrb._load_active_busy_generations
    load_calls = {"n": 0}

    async def load_with_barrier(db_arg, resource_id):
        load_calls["n"] += 1
        gens = await original_load(db_arg, resource_id)
        if load_calls["n"] == 1:
            # Release writer after gens_before; writer claims gen 2 before
            # the busy-row fetch / gens_after recheck.
            await barrier.wait()
        return gens

    async def reader():
        with patch.object(
            mrb, "_load_active_busy_generations", side_effect=load_with_barrier
        ):
            read_result["rows"] = await fetch_resource_busy(db, NICHOLE, date_str)

    async def writer():
        await barrier.wait()
        with patch.object(ocs, "_next_sync_generation", return_value=2):
            await persist_resource_busy_from_events(
                db,
                connection,
                [_graph_event(event_id="gen2-busy", categories=["Discovery"])],
                clinic_timezone="America/Chicago",
                synced_at=datetime.now(timezone.utc),
            )

    await asyncio.gather(reader(), writer())

    rows = read_result["rows"]
    ids = {r.get("event_id") for r in rows}
    # Must not be false-empty: retry lands on gen2 (or consistent gen1).
    assert ids, "busy read returned false-empty during concurrent claim"
    assert "gen1-busy" in ids or "gen2-busy" in ids
    if "gen2-busy" in ids:
        assert "gen1-busy" not in ids


@pytest.mark.asyncio
async def test_b1_real_mongo_stale_completion_does_not_overwrite_newer_ok(real_db):
    """Older sync must not publish ok freshness after a newer sync succeeded."""
    db = real_db
    connection = _nichole_connection()
    await db.outlook_calendar_connections.insert_one(dict(connection))
    await db.resources.insert_many(
        [
            {"resource_id": NICHOLE, "active": True},
            {"resource_id": SALT, "active": True},
        ]
    )
    await db.outlook_calendar_events.create_index("connection_id")

    from application import outlook_category_sync as ocs

    # Winner B publishes first at gen 20.
    with patch.object(ocs, "_next_sync_generation", return_value=20):
        meta_b = await persist_resource_busy_from_events(
            db,
            connection,
            [_graph_event(event_id="winner-b", categories=["Discovery"])],
            clinic_timezone="America/Chicago",
            synced_at=datetime.now(timezone.utc),
        )
    assert meta_b.get("skipped_stale_generation") is False
    winner_ts = "2026-10-19T12:00:00+00:00"
    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection["connection_id"]},
        {
            "$set": {
                "last_synced_at": winner_ts,
                "last_sync_status": "ok",
                "last_sync_error": None,
            }
        },
    )

    # Loser A tries to complete sync at older generation 5.
    conn_doc = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection["connection_id"]}, {"_id": 0}
    )
    assert conn_doc is not None

    with patch.object(settings, "multi_resource_scheduling", True), patch(
        "application.outlook_sync.graph_client"
    ) as mock_graph_factory, patch.object(
        ocs, "_next_sync_generation", return_value=5
    ):
        client = MagicMock()
        client.client_credentials_token = AsyncMock(
            return_value={"access_token": "t"}
        )
        client.list_user_calendar_view = AsyncMock(
            return_value=[_graph_event(event_id="loser-a", categories=["Discovery"])]
        )
        mock_graph_factory.return_value = client
        result = await sync_outlook_connection(db, conn_doc)

    assert result.get("status") == "skipped_stale_generation"
    refreshed = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection["connection_id"]}
    )
    assert refreshed["last_synced_at"] == winner_ts
    assert int(refreshed["active_busy_generation"]) == 20
    busy = await db.resource_busy_intervals.find(
        {"connection_id": connection["connection_id"], "source": "outlook"},
        {"_id": 0},
    ).to_list(20)
    assert {r.get("event_id") for r in busy} == {"winner-b"}


@pytest.mark.asyncio
async def test_b1_real_mongo_insert_failure_preserves_prior_busy(real_db):
    db = real_db
    connection = _nichole_connection()
    connection["active_busy_generation"] = 7
    await db.outlook_calendar_connections.insert_one(dict(connection))
    await db.resources.insert_many(
        [
            {"resource_id": NICHOLE, "active": True},
            {"resource_id": SALT, "active": True},
        ]
    )
    await db.resource_busy_intervals.insert_one(
        {
            "resource_id": NICHOLE,
            "date": "2026-10-20",
            "start_time": "10:00",
            "end_time": "11:00",
            "connection_id": connection["connection_id"],
            "source": "outlook",
            "event_id": "prior",
            "sync_generation": 7,
        }
    )

    from application import outlook_category_sync as ocs

    real_busy = db.resource_busy_intervals

    class _BoomBusy:
        """Proxy that fails insert_many while preserving prior rows for reads."""

        def __getattr__(self, name: str):
            return getattr(real_busy, name)

        async def insert_many(self, *_a, **_k):
            raise RuntimeError("insert failed mid-sync")

    db.resource_busy_intervals = _BoomBusy()  # type: ignore[assignment]
    with patch.object(ocs, "_next_sync_generation", return_value=8):
        with pytest.raises(RuntimeError, match="insert failed"):
            await persist_resource_busy_from_events(
                db,
                connection,
                [_graph_event(event_id="new", categories=["Discovery"])],
                clinic_timezone="America/Chicago",
                synced_at=datetime.now(timezone.utc),
            )
    db.resource_busy_intervals = real_busy

    conn = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection["connection_id"]}
    )
    assert int(conn["active_busy_generation"]) == 7
    rows = await db.resource_busy_intervals.find({}, {"_id": 0}).to_list(20)
    assert {r.get("event_id") for r in rows} == {"prior"}


@pytest.mark.asyncio
async def test_b1_real_mongo_legitimate_empty_snapshot(real_db):
    db = real_db
    connection = _nichole_connection()
    connection["active_busy_generation"] = 3
    await db.outlook_calendar_connections.insert_one(dict(connection))
    await db.resources.insert_many(
        [
            {"resource_id": NICHOLE, "active": True},
            {"resource_id": SALT, "active": True},
        ]
    )
    # Prior gen-3 busy present; empty gen-4 claim should clear older and leave empty.
    await db.resource_busy_intervals.insert_one(
        {
            "resource_id": NICHOLE,
            "date": "2026-10-20",
            "start_time": "10:00",
            "end_time": "11:00",
            "connection_id": connection["connection_id"],
            "source": "outlook",
            "event_id": "old",
            "sync_generation": 3,
        }
    )

    from application import outlook_category_sync as ocs

    with patch.object(ocs, "_next_sync_generation", return_value=4):
        result = await persist_resource_busy_from_events(
            db,
            connection,
            [],  # legitimate empty calendar
            clinic_timezone="America/Chicago",
            synced_at=datetime.now(timezone.utc),
        )
    assert result.get("skipped_stale_generation") is False
    assert result.get("active_busy_generation") == 4
    assert result.get("resource_interval_count") == 0

    rows = await fetch_resource_busy(db, NICHOLE, "2026-10-20")
    assert rows == []


@pytest.mark.asyncio
async def test_b1_real_mongo_delayed_legacy_publish_cannot_wipe_winner(real_db):
    """
    Codex B1 compatibility window: pause A after final ownership read; complete
    B; resume A's legacy publish — winner metadata AND legacy rows must survive.
    """
    import application.outlook_category_sync as ocs
    import application.outlook_sync as o_sync

    db = real_db
    connection = _nichole_connection()
    await db.outlook_calendar_connections.insert_one(dict(connection))
    await db.resources.insert_many(
        [
            {"resource_id": NICHOLE, "active": True},
            {"resource_id": SALT, "active": True},
        ]
    )
    await db.outlook_calendar_events.create_index("connection_id")

    a_owned = asyncio.Event()
    b_done = asyncio.Event()
    results: Dict[str, Any] = {}

    async def legacy_hook(*, connection_id, publish_generation):
        # Only the older sync (gen 5) pauses in the ownership→mutate window.
        if int(publish_generation) == 5:
            a_owned.set()
            await b_done.wait()

    async def run_a_stale():
        conn_doc = await db.outlook_calendar_connections.find_one(
            {"connection_id": connection["connection_id"]}, {"_id": 0}
        )
        with patch.object(settings, "multi_resource_scheduling", True), patch(
            "application.outlook_sync.graph_client"
        ) as mock_graph_factory, patch.object(
            ocs, "_next_sync_generation", return_value=5
        ):
            client = MagicMock()
            client.client_credentials_token = AsyncMock(
                return_value={"access_token": "t"}
            )
            client.list_user_calendar_view = AsyncMock(
                return_value=[
                    _graph_event(event_id="loser-a-legacy", categories=["Discovery"])
                ]
            )
            mock_graph_factory.return_value = client
            results["a"] = await sync_outlook_connection(db, conn_doc)

    async def run_b_winner():
        await a_owned.wait()
        conn_doc = await db.outlook_calendar_connections.find_one(
            {"connection_id": connection["connection_id"]}, {"_id": 0}
        )
        with patch.object(settings, "multi_resource_scheduling", True), patch(
            "application.outlook_sync.graph_client"
        ) as mock_graph_factory, patch.object(
            ocs, "_next_sync_generation", return_value=20
        ):
            client = MagicMock()
            client.client_credentials_token = AsyncMock(
                return_value={"access_token": "t"}
            )
            client.list_user_calendar_view = AsyncMock(
                return_value=[
                    _graph_event(event_id="winner-b-legacy", categories=["Discovery"])
                ]
            )
            mock_graph_factory.return_value = client
            results["b"] = await sync_outlook_connection(db, conn_doc)
        b_done.set()

    with patch.object(o_sync, "_legacy_pre_publish_hook", legacy_hook):
        await asyncio.gather(run_a_stale(), run_b_winner())

    assert results["b"].get("status") == "ok"
    assert results["a"].get("status") == "skipped_stale_generation"

    refreshed = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection["connection_id"]}
    )
    assert int(refreshed["active_busy_generation"]) == 20
    assert refreshed.get("last_sync_status") == "ok"
    assert int(refreshed.get("active_legacy_generation") or 0) == 20

    legacy = await db.outlook_calendar_events.find(
        {"connection_id": connection["connection_id"]}, {"_id": 0}
    ).to_list(50)
    legacy_ids = {r.get("event_id") or r.get("outlook_event_id") for r in legacy}
    # event_to_busy_intervals may not keep event_id — also accept sync_generation.
    gens = {int(r["sync_generation"]) for r in legacy if r.get("sync_generation") is not None}
    assert gens == {20}, f"legacy gens={gens} rows={legacy}"
    assert not any(
        (r.get("event_id") == "loser-a-legacy")
        or (r.get("sync_generation") == 5)
        for r in legacy
    )
    busy = await db.resource_busy_intervals.find(
        {"connection_id": connection["connection_id"], "source": "outlook"},
        {"_id": 0},
    ).to_list(20)
    assert {r.get("event_id") for r in busy} == {"winner-b-legacy"}


@pytest.mark.asyncio
async def test_b1_real_mongo_delayed_legacy_cleanup_cannot_wipe_newer(real_db):
    """
    Codex B1 cleanup window (static interleaving at 494c821):

      1) Sync A CAS-publishes legacy generation 5 successfully
      2) A pauses BEFORE older-generation cleanup
      3) Sync B publishes generation 20 and completes (incl. its cleanup)
      4) A resumes cleanup — must NOT delete B's newer legacy rows/metadata

    Prior `$ne` cleanup deleted gen 20 while metadata still named B healthy.
    """
    import application.outlook_category_sync as ocs
    import application.outlook_sync as o_sync

    db = real_db
    connection = _nichole_connection()
    await db.outlook_calendar_connections.insert_one(dict(connection))
    await db.resources.insert_many(
        [
            {"resource_id": NICHOLE, "active": True},
            {"resource_id": SALT, "active": True},
        ]
    )
    await db.outlook_calendar_events.create_index("connection_id")

    a_cas_done = asyncio.Event()
    b_done = asyncio.Event()
    results: Dict[str, Any] = {}

    async def post_cas_hook(*, connection_id, publish_generation):
        # Only the older sync (gen 5) pauses after successful CAS.
        if int(publish_generation) == 5:
            a_cas_done.set()
            await b_done.wait()

    async def run_a_cas_then_cleanup():
        conn_doc = await db.outlook_calendar_connections.find_one(
            {"connection_id": connection["connection_id"]}, {"_id": 0}
        )
        with patch.object(settings, "multi_resource_scheduling", True), patch(
            "application.outlook_sync.graph_client"
        ) as mock_graph_factory, patch.object(
            ocs, "_next_sync_generation", return_value=5
        ):
            client = MagicMock()
            client.client_credentials_token = AsyncMock(
                return_value={"access_token": "t"}
            )
            client.list_user_calendar_view = AsyncMock(
                return_value=[
                    _graph_event(
                        event_id="loser-a-cas-cleanup", categories=["Discovery"]
                    )
                ]
            )
            mock_graph_factory.return_value = client
            results["a"] = await sync_outlook_connection(db, conn_doc)

    async def run_b_winner():
        await a_cas_done.wait()
        # A has CAS'd gen 5; its gen-5 rows exist. B must publish 20 and finish.
        mid = await db.outlook_calendar_connections.find_one(
            {"connection_id": connection["connection_id"]}
        )
        assert int(mid.get("active_legacy_generation") or 0) == 5
        assert int(mid["active_busy_generation"]) == 5

        conn_doc = await db.outlook_calendar_connections.find_one(
            {"connection_id": connection["connection_id"]}, {"_id": 0}
        )
        with patch.object(settings, "multi_resource_scheduling", True), patch(
            "application.outlook_sync.graph_client"
        ) as mock_graph_factory, patch.object(
            ocs, "_next_sync_generation", return_value=20
        ):
            client = MagicMock()
            client.client_credentials_token = AsyncMock(
                return_value={"access_token": "t"}
            )
            client.list_user_calendar_view = AsyncMock(
                return_value=[
                    _graph_event(
                        event_id="winner-b-after-a-cas", categories=["Discovery"]
                    )
                ]
            )
            mock_graph_factory.return_value = client
            results["b"] = await sync_outlook_connection(db, conn_doc)
        b_done.set()

    with patch.object(o_sync, "_legacy_post_cas_hook", post_cas_hook):
        await asyncio.gather(run_a_cas_then_cleanup(), run_b_winner())

    assert results["b"].get("status") == "ok"
    # A may still report ok (its CAS succeeded earlier); correctness is on rows.
    assert results["a"].get("status") in ("ok", "skipped_stale_generation")

    refreshed = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection["connection_id"]}
    )
    assert int(refreshed["active_busy_generation"]) == 20
    assert refreshed.get("last_sync_status") == "ok"
    assert int(refreshed.get("active_legacy_generation") or 0) == 20

    legacy = await db.outlook_calendar_events.find(
        {"connection_id": connection["connection_id"]}, {"_id": 0}
    ).to_list(50)
    gens = {
        int(r["sync_generation"])
        for r in legacy
        if r.get("sync_generation") is not None
    }
    assert gens == {20}, f"legacy gens={gens} rows={legacy}"
    assert not any(
        (r.get("event_id") == "loser-a-cas-cleanup")
        or (r.get("sync_generation") == 5)
        for r in legacy
    )
    busy = await db.resource_busy_intervals.find(
        {"connection_id": connection["connection_id"], "source": "outlook"},
        {"_id": 0},
    ).to_list(20)
    assert {r.get("event_id") for r in busy} == {"winner-b-after-a-cas"}
