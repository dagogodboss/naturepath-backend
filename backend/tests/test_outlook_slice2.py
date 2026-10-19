"""
Issue #9 Slice 2: Outlook B1 (atomic snapshot), B2 (app-only admin sync),
B3 (Salt visibility copies on Nichole).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from application.outlook_category_sync import (
    build_resource_busy_documents,
    map_event_categories_to_resource_ids,
    persist_resource_busy_from_events,
)
from core.config import settings
from domain.entities.models import ReviewQueueItemType
from domain.multi_resource_defaults import (
    CATEGORY_SALT_LEGACY,
    CATEGORY_SALT_SESSION,
    build_locked_outlook_connection_templates,
    build_nichole_authoritative_category_maps,
)
from presentation.api import scheduling_admin_routes as routes

NICHOLE = "res-nichole"
SALT = "res-salt"

NICHOLE_MAPS = [
    m.model_dump() for m in build_nichole_authoritative_category_maps(NICHOLE, SALT)
]

NICHOLE_CONNECTION = {
    "connection_id": "conn-nichole",
    "visibility_only": False,
    "authoritative_for_resource_ids": [NICHOLE],
    "category_maps": NICHOLE_MAPS,
    "visibility_copy_category_names": [CATEGORY_SALT_SESSION, CATEGORY_SALT_LEGACY],
}


def _graph_event(
    *,
    event_id: str = "evt-1",
    categories: list | None = None,
    show_as: str = "busy",
    is_cancelled: bool = False,
    start: str = "2026-10-20T15:00:00",
    end: str = "2026-10-20T16:00:00",
    subject: str = "Test",
) -> dict:
    return {
        "id": event_id,
        "categories": categories or [],
        "showAs": show_as,
        "isCancelled": is_cancelled,
        "subject": subject,
        "start": {"dateTime": start, "timeZone": "America/Chicago"},
        "end": {"dateTime": end, "timeZone": "America/Chicago"},
    }


# ---- B1: atomic / fail-safe snapshot -----------------------------------------


class _BusyCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.delete_queries = []
        self.insert_batches = []
        self.fail_insert = False

    async def delete_many(self, query):
        self.delete_queries.append(query)
        kept = []
        for row in self.rows:
            if not self._matches(row, query):
                kept.append(row)
        self.rows = kept

    async def insert_many(self, docs):
        if self.fail_insert:
            raise RuntimeError("insert failed mid-sync")
        batch = [dict(d) for d in docs]
        self.insert_batches.append(batch)
        self.rows.extend(batch)

    def _matches(self, row, query):
        for key, expected in query.items():
            if key == "$or":
                if not any(self._matches(row, clause) for clause in expected):
                    return False
                continue
            if key == "$and":
                if not all(self._matches(row, clause) for clause in expected):
                    return False
                continue
            actual = row.get(key)
            if isinstance(expected, dict):
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
                if "$exists" in expected:
                    exists = key in row and row[key] is not None
                    if bool(expected["$exists"]) != exists:
                        return False
                if "$lt" in expected and not (actual is not None and actual < expected["$lt"]):
                    return False
                if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
                    return False
            elif actual != expected:
                return False
        return True


class _ConnectionsCol:
    def __init__(self, doc):
        self.doc = dict(doc)
        self.updates = []

    async def update_one(self, query, update):
        self.updates.append((query, update))
        cid = query.get("connection_id")
        if cid and cid != self.doc.get("connection_id"):
            return SimpleNamespace(matched_count=0, modified_count=0)
        # Evaluate $or generation CAS filters when present.
        or_clauses = query.get("$or")
        if or_clauses is not None:
            active = self.doc.get("active_busy_generation")
            ok = False
            for clause in or_clauses:
                if "active_busy_generation" not in clause:
                    continue
                cond = clause["active_busy_generation"]
                if isinstance(cond, dict):
                    if cond.get("$exists") is False and "active_busy_generation" not in self.doc:
                        ok = True
                    if cond.get("$lt") is not None and active is not None and active < cond["$lt"]:
                        ok = True
                elif cond is None and active is None:
                    ok = True
            if active is None and any(
                isinstance(c.get("active_busy_generation"), dict)
                and c["active_busy_generation"].get("$exists") is False
                for c in or_clauses
            ):
                ok = True
            if active is None:
                # Missing field satisfies $exists:false or None equality.
                ok = True
            if not ok and active is not None:
                for clause in or_clauses:
                    cond = clause.get("active_busy_generation")
                    if isinstance(cond, dict) and "$lt" in cond and active < cond["$lt"]:
                        ok = True
            if not ok:
                return SimpleNamespace(matched_count=1, modified_count=0)
        self.doc.update(update.get("$set") or {})
        return SimpleNamespace(matched_count=1, modified_count=1)

    async def find_one(self, query, projection=None):
        if query.get("connection_id") == self.doc.get("connection_id"):
            return dict(self.doc)
        return None


class _Resources:
    def find(self, *args, **kwargs):
        class _Cursor:
            async def to_list(self, length=500):
                return [{"resource_id": NICHOLE}, {"resource_id": SALT}]

        return _Cursor()


class _ReviewCol:
    def __init__(self):
        self.rows = []
        self.delete_queries = []

    async def delete_many(self, query):
        self.delete_queries.append(query)
        self.rows = [
            r
            for r in self.rows
            if not (
                r.get("connection_id") == query.get("connection_id")
                and r.get("status") == (query.get("status") or r.get("status"))
            )
        ]

    async def insert_many(self, rows):
        self.rows.extend(dict(r) for r in rows)


def _db_for_persist(*, prior_busy=None, connection=None):
    conn = dict(connection or NICHOLE_CONNECTION)
    busy = _BusyCol(prior_busy)
    connections = _ConnectionsCol(conn)
    review = _ReviewCol()
    db = MagicMock()
    db.resources = _Resources()
    db.resource_busy_intervals = busy
    db.outlook_calendar_connections = connections
    db.review_queue = review
    db.bookings = MagicMock()
    db.bookings.find = MagicMock(
        return_value=SimpleNamespace(to_list=AsyncMock(return_value=[]))
    )
    return db, busy, connections


@pytest.mark.asyncio
async def test_b1_insert_failure_preserves_prior_busy_snapshot():
    prior = [
        {
            "resource_id": NICHOLE,
            "date": "2026-10-20",
            "start_time": "10:00",
            "end_time": "10:30",
            "connection_id": "conn-nichole",
            "source": "outlook",
            "event_id": "old",
            "sync_generation": 1,
        }
    ]
    db, busy, connections = _db_for_persist(prior_busy=prior)
    busy.fail_insert = True
    connections.doc["active_busy_generation"] = 1

    with pytest.raises(RuntimeError, match="insert failed"):
        await persist_resource_busy_from_events(
            db,
            NICHOLE_CONNECTION,
            [_graph_event(categories=["Discovery"], event_id="new")],
            clinic_timezone="America/Chicago",
        )

    assert any(r.get("event_id") == "old" for r in busy.rows)
    assert not any(r.get("event_id") == "new" for r in busy.rows)
    # Must not delete-then-insert: no wipe of prior generation before insert succeeds.
    assert connections.doc.get("active_busy_generation") == 1


@pytest.mark.asyncio
async def test_b1_readers_never_see_empty_window_during_refresh():
    prior = [
        {
            "resource_id": NICHOLE,
            "date": "2026-10-20",
            "start_time": "10:00",
            "end_time": "10:30",
            "connection_id": "conn-nichole",
            "source": "outlook",
            "event_id": "old",
            "sync_generation": 1,
        }
    ]
    db, busy, connections = _db_for_persist(prior_busy=prior)
    connections.doc["active_busy_generation"] = 1

    original_insert = busy.insert_many

    async def insert_and_observe(docs):
        # During insert, prior rows must still be readable (no prior delete).
        assert any(r.get("event_id") == "old" for r in busy.rows)
        await original_insert(docs)
        # After insert and before cleanup, union may exist — never empty.
        assert len(busy.rows) >= 1

    busy.insert_many = insert_and_observe  # type: ignore[method-assign]

    await persist_resource_busy_from_events(
        db,
        NICHOLE_CONNECTION,
        [_graph_event(categories=["Discovery"], event_id="new")],
        clinic_timezone="America/Chicago",
    )

    assert any(r.get("event_id") == "new" for r in busy.rows)
    assert not any(r.get("event_id") == "old" for r in busy.rows)


@pytest.mark.asyncio
async def test_b1_older_sync_cannot_overwrite_newer_generation():
    db, busy, connections = _db_for_persist(prior_busy=[])
    connections.doc["active_busy_generation"] = 9_000_000_000_000

    # Force a stale generation claim attempt via patched time.
    with patch(
        "application.outlook_category_sync._next_sync_generation",
        return_value=1,
    ):
        result = await persist_resource_busy_from_events(
            db,
            NICHOLE_CONNECTION,
            [_graph_event(categories=["Discovery"], event_id="stale")],
            clinic_timezone="America/Chicago",
        )

    assert result.get("skipped_stale_generation") is True
    assert connections.doc["active_busy_generation"] == 9_000_000_000_000
    assert not any(r.get("event_id") == "stale" for r in busy.rows)


# ---- B2: mode-correct admin sync ---------------------------------------------


@pytest.mark.asyncio
async def test_b2_admin_sync_application_mode_without_refresh_token():
    conn = {
        "connection_id": "clients-conn",
        "is_active": True,
        "auth_mode": "application",
        "mailbox_email": "Clients@thenaturalpathla.com",
        # intentionally no refresh_token_encrypted
    }
    db = MagicMock()
    db.outlook_calendar_connections = SimpleNamespace(
        find_one=AsyncMock(return_value=conn)
    )

    with (
        patch.object(routes.settings, "outlook_device_code_oauth_enabled", False),
        patch.object(routes.settings, "multi_resource_scheduling", True),
        patch.object(routes.settings, "microsoft_client_id", "app-id"),
        patch.object(routes.settings, "microsoft_client_secret", "app-secret"),
        patch(
            "presentation.api.scheduling_admin_routes.sync_outlook_connection",
            new_callable=AsyncMock,
            return_value={"status": "ok", "event_count": 0},
        ) as sync_mock,
    ):
        result = await routes.admin_sync_outlook_connection(
            "clients-conn",
            _admin={"user_id": "admin-1"},
            db=db,
        )

    assert result["status"] == "ok"
    sync_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_b2_admin_sync_application_does_not_require_device_code_flag():
    conn = {
        "connection_id": "clients-conn",
        "is_active": True,
        "auth_mode": "application",
        "mailbox_email": "Clients@thenaturalpathla.com",
    }
    db = MagicMock()
    db.outlook_calendar_connections = SimpleNamespace(
        find_one=AsyncMock(return_value=conn)
    )

    with (
        patch.object(routes.settings, "outlook_device_code_oauth_enabled", False),
        patch.object(routes.settings, "multi_resource_scheduling", False),
        patch.object(routes.settings, "outlook_app_only_sync_enabled", True),
        patch.object(routes.settings, "microsoft_client_id", "app-id"),
        patch.object(routes.settings, "microsoft_client_secret", "app-secret"),
        patch(
            "presentation.api.scheduling_admin_routes.sync_outlook_connection",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ),
    ):
        result = await routes.admin_sync_outlook_connection(
            "clients-conn",
            _admin={"user_id": "admin-1"},
            db=db,
        )
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_b2_admin_sync_delegated_still_requires_refresh_token():
    conn = {
        "connection_id": "nichole-conn",
        "is_active": True,
        "auth_mode": "delegated",
        "mailbox_email": "nmoore@thenaturalpathla.com",
    }
    db = MagicMock()
    db.outlook_calendar_connections = SimpleNamespace(
        find_one=AsyncMock(return_value=conn)
    )

    with (
        patch.object(routes.settings, "outlook_device_code_oauth_enabled", True),
        patch.object(routes.settings, "multi_resource_scheduling", True),
    ):
        with pytest.raises(HTTPException) as exc:
            await routes.admin_sync_outlook_connection(
                "nichole-conn",
                _admin={"user_id": "admin-1"},
                db=db,
            )
    assert exc.value.status_code == 404
    assert "OAuth" in str(exc.value.detail) or "token" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_b2_connection_public_exposes_mode_without_secrets():
    pub = routes._outlook_connection_public(
        {
            "connection_id": "c1",
            "mailbox_email": "Clients@thenaturalpathla.com",
            "auth_mode": "application",
            "is_active": True,
            "refresh_token_encrypted": "secret-must-not-leak",
            "last_sync_status": "ok",
            "last_synced_at": "2026-10-19T00:00:00+00:00",
            "authoritative_for_resource_ids": [SALT],
        }
    )
    assert pub["auth_mode"] == "application"
    assert pub["connection_method"] == "application"
    assert "administrator" in pub["connection_method_label"].lower()
    assert pub["has_delegated_credentials"] is False
    assert pub["requires_individual_reconnect"] is False
    assert "refresh_token_encrypted" not in pub
    assert "secret" not in str(pub)


# ---- B3: visibility copies ---------------------------------------------------


def test_b3_salt_category_on_nichole_is_visibility_only():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(
            categories=[CATEGORY_SALT_SESSION],
            subject="Salt Session (copy) — do not use title",
        ),
        category_maps=NICHOLE_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
        visibility_copy_category_names=[CATEGORY_SALT_SESSION, CATEGORY_SALT_LEGACY],
    )
    assert mapping.occupy is False
    assert mapping.authoritative is False
    assert mapping.review_type is None


def test_b3_salt_legacy_category_on_nichole_is_visibility_only():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=[CATEGORY_SALT_LEGACY]),
        category_maps=NICHOLE_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
        visibility_copy_category_names=[CATEGORY_SALT_SESSION, CATEGORY_SALT_LEGACY],
    )
    assert mapping.occupy is False


def test_b3_title_alone_does_not_mark_visibility_copy():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=[], subject="Salt Session at 3pm"),
        category_maps=NICHOLE_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
        visibility_copy_category_names=[CATEGORY_SALT_SESSION, CATEGORY_SALT_LEGACY],
    )
    # Mystery busy remains fail-closed (Phase 0).
    assert mapping.occupy is True
    assert set(mapping.resource_ids) == {NICHOLE}
    assert mapping.review_type == ReviewQueueItemType.UNMAPPED_CATEGORY


def test_b3_unknown_busy_on_nichole_still_blocks_and_reviews():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=["Random Tag"]),
        category_maps=NICHOLE_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
        visibility_copy_category_names=[CATEGORY_SALT_SESSION, CATEGORY_SALT_LEGACY],
    )
    assert mapping.occupy is True
    assert set(mapping.resource_ids) == {NICHOLE}
    assert mapping.review_type == ReviewQueueItemType.UNMAPPED_CATEGORY


def test_b3_discovery_still_blocks_nichole_not_salt():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=["Discovery"]),
        category_maps=NICHOLE_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
        visibility_copy_category_names=[CATEGORY_SALT_SESSION, CATEGORY_SALT_LEGACY],
    )
    assert set(mapping.resource_ids) == {NICHOLE}
    assert SALT not in mapping.resource_ids


def test_b3_visibility_copy_does_not_double_count_salt_capacity():
    built = build_resource_busy_documents(
        [
            _graph_event(
                event_id="salt-copy",
                categories=[CATEGORY_SALT_SESSION],
                start="2026-10-20T15:00:00",
                end="2026-10-20T16:00:00",
            )
        ],
        NICHOLE_CONNECTION,
        clinic_timezone="America/Chicago",
        synced_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )
    assert built.intervals == []
    assert built.review_items == []


def test_b3_locked_nichole_template_marks_salt_visibility_copies():
    templates = build_locked_outlook_connection_templates(NICHOLE, SALT)
    nichole = templates["nichole_authoritative"]
    names = {
        str(n).casefold()
        for n in (nichole.get("visibility_copy_category_names") or [])
    }
    assert CATEGORY_SALT_SESSION.casefold() in names
    assert CATEGORY_SALT_LEGACY.casefold() in names
    # Prefer shared Clients@ — Salt occupancy maps stay on Clients@ template.
    clients = templates["clients_salt_authoritative"]
    assert clients["authoritative_for_resource_ids"] == [SALT]
    assert not clients.get("visibility_only")


def test_b3_category_map_visibility_only_flag():
    maps = [
        {"category_name": "Discovery", "resource_ids": [NICHOLE]},
        {
            "category_name": CATEGORY_SALT_SESSION,
            "resource_ids": [SALT],
            "visibility_only": True,
        },
    ]
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=[CATEGORY_SALT_SESSION]),
        category_maps=maps,
        authoritative_for_resource_ids=[NICHOLE],
    )
    assert mapping.occupy is False
    assert mapping.authoritative is False
