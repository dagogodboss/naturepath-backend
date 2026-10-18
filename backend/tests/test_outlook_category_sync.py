"""Phase 2 scaffold: Outlook category → resource busy mapping (flag-gated)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.outlook_category_sync import (
    MultiResourceSyncConfigError,
    build_resource_busy_documents,
    map_event_categories_to_resource_ids,
    normalize_category_name,
    persist_resource_busy_from_events,
    validate_multi_resource_sync_ready,
)
from application.outlook_sync import OutlookSyncError, sync_outlook_connection
from core.config import settings
from domain.entities.models import ReviewQueueItemType
from domain.multi_resource_defaults import build_clients_salt_authoritative_category_maps
from infrastructure.external.microsoft_graph import MicrosoftGraphClient

NICHOLE = "res-nichole"
SALT = "res-salt"

CATEGORY_MAPS = [
    {"category_name": "Discovery", "resource_ids": [NICHOLE]},
    {"category_name": "Consultation", "resource_ids": [NICHOLE]},
    {"category_name": "Salt", "resource_ids": [SALT]},
    {
        "category_name": "Business closure",
        "resource_ids": [NICHOLE, SALT],
        "blocks_all_authoritative": True,
    },
]

AUTH_CONNECTION = {
    "connection_id": "conn-1",
    "practitioner_id": "prac-1",
    "visibility_only": False,
    "authoritative_for_resource_ids": [NICHOLE],
    "category_maps": CATEGORY_MAPS,
}


def _graph_event(
    *,
    event_id: str = "evt-1",
    categories: list | None = None,
    show_as: str = "busy",
    is_cancelled: bool = False,
    start: str = "2026-10-20T15:00:00",
    end: str = "2026-10-20T15:45:00",
) -> dict:
    return {
        "id": event_id,
        "categories": categories or [],
        "showAs": show_as,
        "isCancelled": is_cancelled,
        "subject": "Test",
        "start": {"dateTime": start, "timeZone": "America/Chicago"},
        "end": {"dateTime": end, "timeZone": "America/Chicago"},
    }


def test_normalize_category_name_casefold():
    assert normalize_category_name("  Salt ") == "salt"
    assert normalize_category_name("Business Closure") == normalize_category_name(
        "business closure"
    )


def test_discovery_blocks_practitioner_not_salt():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=["Discovery"]),
        category_maps=CATEGORY_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
    )
    assert mapping.occupy is True
    assert set(mapping.resource_ids) == {NICHOLE}
    assert SALT not in mapping.resource_ids
    assert mapping.review_type is None


def test_salt_blocks_room_not_practitioner():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=["Salt"]),
        category_maps=CATEGORY_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
    )
    assert set(mapping.resource_ids) == {SALT}
    assert NICHOLE not in mapping.resource_ids
    assert mapping.review_type is None


def test_locked_salt_session_on_clients_mailbox_blocks_salt_only():
    clients_maps = [
        m.model_dump()
        for m in build_clients_salt_authoritative_category_maps(SALT, NICHOLE)
    ]
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=["Salt Session"]),
        category_maps=clients_maps,
        authoritative_for_resource_ids=[SALT],
    )
    assert set(mapping.resource_ids) == {SALT}
    assert mapping.review_type is None


def test_mystery_busy_on_clients_mailbox_blocks_salt_not_nichole():
    clients_maps = [
        m.model_dump()
        for m in build_clients_salt_authoritative_category_maps(SALT, NICHOLE)
    ]
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=[]),
        category_maps=clients_maps,
        authoritative_for_resource_ids=[SALT],
    )
    assert set(mapping.resource_ids) == {SALT}
    assert NICHOLE not in mapping.resource_ids
    assert mapping.review_type == ReviewQueueItemType.UNMAPPED_CATEGORY


def test_salt_casefold_match():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=["salt"]),
        category_maps=CATEGORY_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
    )
    assert set(mapping.resource_ids) == {SALT}


def test_business_closure_blocks_both():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=["Business closure"]),
        category_maps=CATEGORY_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
    )
    assert set(mapping.resource_ids) == {NICHOLE, SALT}


def test_unmapped_busy_blocks_practitioner_and_enqueues_review():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=["Random Tag"], event_id="evt-u"),
        category_maps=CATEGORY_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
    )
    assert set(mapping.resource_ids) == {NICHOLE}
    assert SALT not in mapping.resource_ids
    assert mapping.review_type == ReviewQueueItemType.UNMAPPED_CATEGORY


def test_unmapped_empty_categories_same_rule():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=[]),
        category_maps=CATEGORY_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
    )
    assert set(mapping.resource_ids) == {NICHOLE}
    assert mapping.review_type == ReviewQueueItemType.UNMAPPED_CATEGORY


def test_free_and_cancelled_do_not_occupy():
    free = map_event_categories_to_resource_ids(
        _graph_event(categories=["Discovery"], show_as="free"),
        category_maps=CATEGORY_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
    )
    cancelled = map_event_categories_to_resource_ids(
        _graph_event(categories=["Discovery"], is_cancelled=True),
        category_maps=CATEGORY_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
    )
    assert free.occupy is False
    assert cancelled.occupy is False


def test_visibility_only_never_occupies():
    mapping = map_event_categories_to_resource_ids(
        _graph_event(categories=["Salt"]),
        category_maps=CATEGORY_MAPS,
        authoritative_for_resource_ids=[NICHOLE],
        visibility_only=True,
    )
    assert mapping.occupy is False
    assert mapping.authoritative is False


def test_build_documents_discovery_vs_salt_matrix():
    events = [
        _graph_event(
            event_id="disc",
            categories=["Discovery"],
            start="2026-10-20T15:00:00",
            end="2026-10-20T15:45:00",
        ),
        _graph_event(
            event_id="salt",
            categories=["Salt"],
            start="2026-10-20T15:00:00",
            end="2026-10-20T16:00:00",
        ),
        _graph_event(
            event_id="unk",
            categories=[],
            start="2026-10-20T10:00:00",
            end="2026-10-20T10:30:00",
        ),
    ]
    built = build_resource_busy_documents(
        events,
        AUTH_CONNECTION,
        clinic_timezone="America/Chicago",
        synced_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )
    by_event: dict[str, set[str]] = {}
    for row in built.intervals:
        by_event.setdefault(row["event_id"], set()).add(row["resource_id"])

    assert by_event["disc"] == {NICHOLE}
    assert by_event["salt"] == {SALT}
    assert by_event["unk"] == {NICHOLE}
    assert len(built.review_items) == 1
    assert built.review_items[0]["type"] == ReviewQueueItemType.UNMAPPED_CATEGORY.value
    assert built.review_items[0]["event_id"] == "unk"


def test_validate_fail_closed_without_maps():
    with pytest.raises(MultiResourceSyncConfigError, match="category_maps"):
        validate_multi_resource_sync_ready(
            {
                "authoritative_for_resource_ids": [NICHOLE],
                "category_maps": [],
            }
        )


def test_validate_fail_closed_missing_resource_docs():
    with pytest.raises(MultiResourceSyncConfigError, match="missing resources"):
        validate_multi_resource_sync_ready(
            AUTH_CONNECTION,
            known_resource_ids=[NICHOLE],  # Salt missing
        )


def test_persist_refuses_wipe_when_config_invalid():
    class _Busy:
        def __init__(self):
            self.deleted = False

        async def delete_many(self, query):
            self.deleted = True

        async def insert_many(self, rows):
            return None

    class _Resources:
        def find(self, *args, **kwargs):
            class _Cursor:
                async def to_list(self, length=500):
                    return [{"resource_id": NICHOLE}, {"resource_id": SALT}]

            return _Cursor()

    db = MagicMock()
    db.resources = _Resources()
    db.resource_busy_intervals = _Busy()
    db.review_queue = MagicMock()

    bad = {
        "connection_id": "c1",
        "visibility_only": False,
        "authoritative_for_resource_ids": [],
        "category_maps": CATEGORY_MAPS,
    }
    with pytest.raises(MultiResourceSyncConfigError):
        asyncio.run(
            persist_resource_busy_from_events(
                db,
                bad,
                [_graph_event(categories=["Discovery"])],
                clinic_timezone="America/Chicago",
            )
        )
    assert db.resource_busy_intervals.deleted is False


def test_list_calendar_view_select_includes_categories():
    client = MicrosoftGraphClient(
        client_id="id",
        client_secret="secret",
        tenant_id="common",
        redirect_uri="https://example.com/callback",
    )
    start = datetime(2026, 10, 15, tzinfo=timezone.utc)
    end = datetime(2026, 10, 16, tzinfo=timezone.utc)

    import httpx

    ok = httpx.Response(
        200,
        request=httpx.Request(
            "GET", "https://graph.microsoft.com/v1.0/me/calendar/calendarView"
        ),
        json={"value": []},
    )
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=ok)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "infrastructure.external.microsoft_graph.httpx.AsyncClient",
        return_value=mock_http,
    ):
        asyncio.run(client.list_calendar_view("token", start=start, end=end))

    params = mock_http.get.await_args.kwargs["params"]
    assert "categories" in params["$select"]
    assert "subject" in params["$select"]


def test_sync_outlook_skips_resource_path_when_flag_false():
    """Default flag off: exact legacy path; no resource busy writer."""

    class _Connections:
        def __init__(self):
            self.updates = []

        async def update_one(self, query, update):
            self.updates.append((query, update))

    class _Events:
        def __init__(self):
            self.deleted = None
            self.inserted = None

        async def delete_many(self, query):
            self.deleted = query

        async def insert_many(self, rows):
            self.inserted = rows

    db = MagicMock()
    db.outlook_calendar_connections = _Connections()
    db.outlook_calendar_events = _Events()
    db.resource_busy_intervals = MagicMock()
    db.resource_busy_intervals.delete_many = AsyncMock()

    connection = {
        "connection_id": "c1",
        "practitioner_id": "p1",
        "refresh_token_encrypted": "cipher-text",
        **{k: v for k, v in AUTH_CONNECTION.items() if k != "connection_id"},
        "connection_id": "c1",
    }
    mock_client = MagicMock()
    mock_client.refresh = AsyncMock(
        return_value={"access_token": "a", "refresh_token": "r"}
    )
    mock_client.list_calendar_view = AsyncMock(
        return_value=[
            _graph_event(
                categories=["Discovery"],
                start="2026-10-20T15:00:00+00:00",
                end="2026-10-20T15:45:00+00:00",
            )
        ]
    )
    mock_cipher = MagicMock()
    mock_cipher.decrypt.return_value = "refresh"
    mock_cipher.encrypt.return_value = "encrypted"

    assert settings.multi_resource_scheduling is False
    with (
        patch("application.outlook_sync.graph_client", return_value=mock_client),
        patch("application.outlook_sync.OutlookTokenCipher", return_value=mock_cipher),
        patch(
            "application.outlook_sync.persist_resource_busy_from_events",
            new_callable=AsyncMock,
        ) as persist_mock,
    ):
        result = asyncio.run(sync_outlook_connection(db, connection))

    assert result["status"] == "ok"
    persist_mock.assert_not_called()
    db.resource_busy_intervals.delete_many.assert_not_called()
    assert db.outlook_calendar_events.deleted == {"connection_id": "c1"}
    assert db.outlook_calendar_events.inserted


def test_sync_outlook_flag_true_fail_closed_missing_maps():
    class _Connections:
        def __init__(self):
            self.updates = []

        async def update_one(self, query, update):
            self.updates.append((query, update))

    class _Events:
        def __init__(self):
            self.deleted = False

        async def delete_many(self, query):
            self.deleted = True

        async def insert_many(self, rows):
            return None

    db = MagicMock()
    db.outlook_calendar_connections = _Connections()
    db.outlook_calendar_events = _Events()
    # Skip resource-id existence probe; fail on missing category_maps.
    db.resources = None

    connection = {
        "connection_id": "c1",
        "practitioner_id": "p1",
        "refresh_token_encrypted": "cipher-text",
        "visibility_only": False,
        "authoritative_for_resource_ids": [NICHOLE],
        "category_maps": [],
    }
    mock_client = MagicMock()
    mock_client.refresh = AsyncMock(
        return_value={"access_token": "a", "refresh_token": "r"}
    )
    mock_client.list_calendar_view = AsyncMock(return_value=[])
    mock_cipher = MagicMock()
    mock_cipher.decrypt.return_value = "refresh"
    mock_cipher.encrypt.return_value = "encrypted"

    with (
        patch("application.outlook_sync.graph_client", return_value=mock_client),
        patch("application.outlook_sync.OutlookTokenCipher", return_value=mock_cipher),
        patch.object(settings, "multi_resource_scheduling", True),
    ):
        with pytest.raises(OutlookSyncError, match="category_maps"):
            asyncio.run(sync_outlook_connection(db, connection))

    assert db.outlook_calendar_events.deleted is False
    assert db.outlook_calendar_connections.updates
    assert (
        db.outlook_calendar_connections.updates[0][1]["$set"]["last_sync_status"]
        == "error"
    )


@pytest.mark.asyncio
async def test_persist_enqueues_sync_conflict_for_confirmed_booking():
    """Flag-on persist path: overlapping confirmed booking → sync_conflict review."""

    class _BusyCol:
        def __init__(self):
            self.deleted = []
            self.inserted = []

        async def delete_many(self, query):
            self.deleted.append(query)

        async def insert_many(self, rows):
            self.inserted.extend(rows)

    class _ReviewCol:
        def __init__(self):
            self.deleted = []
            self.inserted = []
            self.rows = []

        async def delete_many(self, query):
            self.deleted.append(query)

        async def insert_many(self, rows):
            self.inserted.extend(rows)
            self.rows.extend(rows)

        async def find_one(self, query, projection=None):
            for row in self.rows:
                if row.get("booking_id") != query.get("booking_id"):
                    continue
                if row.get("type") != query.get("type"):
                    continue
                if row.get("status") != query.get("status"):
                    continue
                payload = row.get("payload") or {}
                blocking = payload.get("blocking_interval") or {}
                if (
                    query.get("payload.blocking_interval.start_time")
                    and blocking.get("start_time")
                    != query["payload.blocking_interval.start_time"]
                ):
                    continue
                return row
            return None

        async def insert_one(self, doc):
            self.rows.append(doc)

    class _BookingsCursor:
        def __init__(self, rows):
            self._rows = rows

        async def to_list(self, length=500):
            return list(self._rows)

    class _BookingsCol:
        def find(self, query, projection=None):
            matched = []
            for row in self._rows:
                if row.get("status") != query.get("status"):
                    continue
                if row.get("resource_id") != query.get("resource_id"):
                    continue
                slot = row.get("slot") or {}
                if slot.get("date") != query.get("slot.date"):
                    continue
                matched.append(row)
            return _BookingsCursor(matched)

        _rows = [
            {
                "booking_id": "b-salt-confirmed",
                "status": "confirmed",
                "resource_id": SALT,
                "occupied_start_time": "15:00",
                "occupied_end_time": "16:00",
                "slot": {
                    "date": "2026-10-20",
                    "start_time": "15:00",
                    "end_time": "15:45",
                },
            }
        ]

    class _Resources:
        def find(self, *args, **kwargs):
            class _Cursor:
                async def to_list(self, length=500):
                    return [{"resource_id": NICHOLE}, {"resource_id": SALT}]

            return _Cursor()

    busy_col = _BusyCol()
    review_col = _ReviewCol()
    db = MagicMock()
    db.resources = _Resources()
    db.resource_busy_intervals = busy_col
    db.review_queue = review_col
    db.bookings = _BookingsCol()

    events = [
        _graph_event(
            event_id="salt-block",
            categories=["Salt"],
            start="2026-10-20T15:00:00",
            end="2026-10-20T16:00:00",
        )
    ]
    result = await persist_resource_busy_from_events(
        db,
        AUTH_CONNECTION,
        events,
        clinic_timezone="America/Chicago",
        synced_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )

    assert result["resource_interval_count"] >= 1
    assert result["sync_conflict_review_count"] == 1
    sync_rows = [r for r in review_col.rows if r["type"] == "sync_conflict"]
    assert len(sync_rows) == 1
    assert sync_rows[0]["booking_id"] == "b-salt-confirmed"
