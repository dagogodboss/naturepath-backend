import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from application.outlook_device_oauth import (
    poll_device_code_for_connection,
    start_device_code_for_connection,
)
from infrastructure.external.microsoft_graph import MicrosoftGraphClient


def test_request_device_code_posts_to_devicecode_endpoint():
    client = MicrosoftGraphClient(
        client_id="cid",
        client_secret="sec",
        tenant_id="tenant",
        redirect_uri="https://example.com/cb",
    )
    ok = httpx.Response(
        200,
        request=httpx.Request("POST", f"{client.authority}/devicecode"),
        json={
            "device_code": "dev",
            "user_code": "ABCD-1234",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
            "interval": 5,
        },
    )
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=ok)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("infrastructure.external.microsoft_graph.httpx.AsyncClient", return_value=mock_http):
        payload = asyncio.run(client.request_device_code())

    assert payload["user_code"] == "ABCD-1234"
    mock_http.post.assert_awaited_once()


def test_start_device_code_persists_session_on_connection():
    db = MagicMock()
    db.outlook_calendar_connections.update_one = AsyncMock()

    connection = {"connection_id": "c1"}
    mock_client = MagicMock()
    mock_client.request_device_code = AsyncMock(
        return_value={
            "device_code": "dev-secret",
            "user_code": "WXYZ-9999",
            "verification_uri": "https://microsoft.com/devicelogin",
            "verification_uri_complete": "https://microsoft.com/devicelogin?otc=WXYZ-9999",
            "expires_in": 600,
            "interval": 5,
            "message": "To sign in, use a browser...",
        }
    )

    with patch("application.outlook_device_oauth.graph_client", return_value=mock_client):
        result = asyncio.run(start_device_code_for_connection(db, connection))

    assert result["status"] == "pending_user"
    assert result["device_code"]["user_code"] == "WXYZ-9999"
    db.outlook_calendar_connections.update_one.assert_awaited_once()
    session = db.outlook_calendar_connections.update_one.await_args[0][1]["$set"][
        "oauth_device_code_session"
    ]
    assert session["user_code"] == "WXYZ-9999"
    assert "device_code_encrypted" in session


def test_poll_device_code_pending_does_not_clear_session():
    db = MagicMock()
    db.outlook_calendar_connections.update_one = AsyncMock()
    now = datetime.now(timezone.utc)
    connection = {
        "connection_id": "c1",
        "oauth_device_code_session": {
            "device_code_encrypted": "enc",
            "user_code": "A",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "interval_seconds": 5,
        },
    }

    request = httpx.Request("POST", "https://login.microsoftonline.com/token")
    pending = httpx.HTTPStatusError(
        "pending",
        request=request,
        response=httpx.Response(
            400,
            request=request,
            json={"error": "authorization_pending"},
        ),
    )

    mock_cipher = MagicMock()
    mock_cipher.decrypt.return_value = "dev"
    mock_client = MagicMock()
    mock_client.poll_device_code = AsyncMock(side_effect=pending)

    with (
        patch("application.outlook_device_oauth.OutlookTokenCipher", return_value=mock_cipher),
        patch("application.outlook_device_oauth.graph_client", return_value=mock_client),
    ):
        result = asyncio.run(poll_device_code_for_connection(db, connection))

    assert result["status"] == "authorization_pending"
    db.outlook_calendar_connections.update_one.assert_not_awaited()
