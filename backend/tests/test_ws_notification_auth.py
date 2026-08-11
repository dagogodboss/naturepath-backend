"""Unit tests for notification WebSocket JWT gate."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from jose import jwt

from core.config import settings
from presentation.websockets.handlers import (
    _authenticate_notification_ws,
    _extract_ws_bearer_token,
)


def _access_token(sub: str) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "email": "u@example.com",
            "role": "customer",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def test_extract_token_from_query():
    ws = MagicMock()
    ws.query_params = {"token": "abc"}
    ws.headers = {}
    assert _extract_ws_bearer_token(ws) == "abc"


def test_extract_token_from_authorization_header():
    ws = MagicMock()
    ws.query_params = {}
    ws.headers = {"authorization": "Bearer xyz"}
    assert _extract_ws_bearer_token(ws) == "xyz"


def test_authenticate_rejects_missing_token():
    ws = MagicMock()
    ws.query_params = {}
    ws.headers = {}
    assert _authenticate_notification_ws(ws, "user-1") is False


def test_authenticate_rejects_wrong_sub():
    ws = MagicMock()
    ws.query_params = {"token": _access_token("user-a")}
    ws.headers = {}
    assert _authenticate_notification_ws(ws, "user-b") is False


def test_authenticate_accepts_matching_sub():
    ws = MagicMock()
    ws.query_params = {"token": _access_token("user-1")}
    ws.headers = {}
    assert _authenticate_notification_ws(ws, "user-1") is True


def test_authenticate_rejects_non_access_token():
    refresh = jwt.encode(
        {
            "sub": "user-1",
            "type": "refresh",
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    ws = MagicMock()
    ws.query_params = {"token": refresh}
    ws.headers = {}
    assert _authenticate_notification_ws(ws, "user-1") is False
