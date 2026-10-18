import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from application.outlook_sync import OutlookSyncError, sync_outlook_connection
from core.config import settings


def test_sync_uses_app_only_calendar_when_auth_mode_application():
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
        "connection_id": "clients-conn",
        "practitioner_id": "p-admin",
        "auth_mode": "application",
        "mailbox_email": "Clients@thenaturalpathla.com",
    }
    event = {
        "id": "e1",
        "showAs": "busy",
        "isCancelled": False,
        "start": {"dateTime": "2026-10-18T15:00:00", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-18T16:00:00", "timeZone": "UTC"},
    }

    mock_client = MagicMock()
    mock_client.client_credentials_token = AsyncMock(return_value={"access_token": "app-token"})
    mock_client.list_user_calendar_view = AsyncMock(return_value=[event])
    mock_client.refresh = AsyncMock()
    mock_client.list_calendar_view = AsyncMock()

    mock_cipher = MagicMock()

    with (
        patch("application.outlook_sync.graph_client", return_value=mock_client),
        patch("application.outlook_sync.OutlookTokenCipher", return_value=mock_cipher),
        patch.object(settings, "multi_resource_scheduling", False),
    ):
        result = asyncio.run(sync_outlook_connection(db, connection))

    assert result["status"] == "ok"
    mock_client.client_credentials_token.assert_awaited_once()
    mock_client.list_user_calendar_view.assert_awaited_once()
    mock_client.refresh.assert_not_called()
    assert db.outlook_calendar_connections.updates
    assert "refresh_token_encrypted" not in db.outlook_calendar_connections.updates[-1][1]["$set"]


def test_app_only_graph_403_surfaces_admin_consent_message():
    class _Connections:
        async def update_one(self, query, update):
            return None

    class _Events:
        async def delete_many(self, query):
            return None

    db = MagicMock()
    db.outlook_calendar_connections = _Connections()
    db.outlook_calendar_events = _Events()

    connection = {
        "connection_id": "c1",
        "practitioner_id": "p1",
        "auth_mode": "application",
        "mailbox_email": "Clients@thenaturalpathla.com",
    }
    request = httpx.Request(
        "GET",
        "https://graph.microsoft.com/v1.0/users/Clients@thenaturalpathla.com/calendar/calendarView",
    )
    graph_error = httpx.HTTPStatusError(
        "403",
        request=request,
        response=httpx.Response(403, request=request),
    )

    mock_client = MagicMock()
    mock_client.client_credentials_token = AsyncMock(return_value={"access_token": "t"})
    mock_client.list_user_calendar_view = AsyncMock(side_effect=graph_error)

    with (
        patch("application.outlook_sync.graph_client", return_value=mock_client),
        patch("application.outlook_sync.OutlookTokenCipher", return_value=MagicMock()),
    ):
        try:
            asyncio.run(sync_outlook_connection(db, connection))
            assert False, "expected OutlookSyncError"
        except OutlookSyncError as exc:
            assert exc.status_code == 502
            assert "admin consent" in str(exc).lower()
