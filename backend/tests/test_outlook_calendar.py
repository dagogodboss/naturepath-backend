import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from application.outlook_calendar import subtract_busy_intervals
from application.outlook_sync import OutlookSyncError, sync_outlook_connection
from infrastructure.external.microsoft_graph import MicrosoftGraphClient


def test_outlook_busy_periods_are_removed_from_app_availability():
    available = [
        {"start_time": "09:00", "end_time": "10:00"},
        {"start_time": "10:00", "end_time": "11:00"},
        {"start_time": "11:00", "end_time": "12:00"},
    ]
    busy = [{"start_time": "09:30", "end_time": "10:30", "source": "outlook"}]

    assert subtract_busy_intervals(available, busy) == [
        {"start_time": "11:00", "end_time": "12:00"}
    ]


def test_free_and_cancelled_outlook_events_do_not_block_slots():
    available = [{"start_time": "09:00", "end_time": "10:00"}]
    busy = [
        {"start_time": "09:00", "end_time": "10:00", "show_as": "free"},
        {"start_time": "09:00", "end_time": "10:00", "is_cancelled": True},
    ]
    assert subtract_busy_intervals(available, busy) == available


def test_list_calendar_view_falls_back_when_default_calendar_404s():
    client = MicrosoftGraphClient(
        client_id="id",
        client_secret="secret",
        tenant_id="common",
        redirect_uri="https://example.com/callback",
    )
    start = datetime(2026, 10, 15, tzinfo=timezone.utc)
    end = datetime(2026, 10, 16, tzinfo=timezone.utc)

    request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me/calendar/calendarView")
    not_found = httpx.Response(404, request=request)
    ok = httpx.Response(
        200,
        request=httpx.Request("GET", "https://graph.microsoft.com/v1.0/me/calendarView"),
        json={"value": [{"id": "evt-1", "showAs": "busy", "isCancelled": False}]},
    )

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(side_effect=[not_found, ok])
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("infrastructure.external.microsoft_graph.httpx.AsyncClient", return_value=mock_http):
        events = asyncio.run(client.list_calendar_view("token", start=start, end=end))

    assert events == [{"id": "evt-1", "showAs": "busy", "isCancelled": False}]
    assert mock_http.get.await_count == 2


def test_sync_outlook_connection_maps_graph_404_to_outlook_sync_error():
    class _Connections:
        def __init__(self):
            self.updates = []

        async def update_one(self, query, update):
            self.updates.append((query, update))

    class _Events:
        async def delete_many(self, query):
            return None

        async def insert_many(self, rows):
            return None

    db = MagicMock()
    db.outlook_calendar_connections = _Connections()
    db.outlook_calendar_events = _Events()

    connection = {
        "connection_id": "c1",
        "practitioner_id": "p1",
        "refresh_token_encrypted": "cipher-text",
    }
    request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me/calendarView")
    response = httpx.Response(404, request=request)
    graph_error = httpx.HTTPStatusError("404", request=request, response=response)

    mock_client = MagicMock()
    mock_client.refresh = AsyncMock(return_value={"access_token": "a", "refresh_token": "r"})
    mock_client.list_calendar_view = AsyncMock(side_effect=graph_error)
    mock_cipher = MagicMock()
    mock_cipher.decrypt.return_value = "refresh"
    mock_cipher.encrypt.return_value = "encrypted"

    with (
        patch("application.outlook_sync.graph_client", return_value=mock_client),
        patch("application.outlook_sync.OutlookTokenCipher", return_value=mock_cipher),
    ):
        try:
            asyncio.run(sync_outlook_connection(db, connection))
            assert False, "expected OutlookSyncError"
        except OutlookSyncError as exc:
            assert exc.status_code == 502
            assert "calendar was not found" in str(exc).lower()

    assert db.outlook_calendar_connections.updates
    assert db.outlook_calendar_connections.updates[0][1]["$set"]["last_sync_status"] == "error"

