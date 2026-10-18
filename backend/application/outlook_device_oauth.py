"""Microsoft device-code OAuth for ops mailbox connect (no redirect URI)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from application.outlook_oauth_store import persist_outlook_oauth_tokens
from application.outlook_sync import graph_client
from core.config import settings
from infrastructure.external.microsoft_graph import OutlookTokenCipher


class DeviceCodeFlowError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _session_public(session: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_code": session.get("user_code"),
        "verification_uri": session.get("verification_uri"),
        "verification_uri_complete": session.get("verification_uri_complete"),
        "expires_at": session.get("expires_at"),
        "interval_seconds": session.get("interval_seconds"),
        "message": session.get("message"),
    }


async def start_device_code_for_connection(
    db: Any,
    connection: Dict[str, Any],
) -> Dict[str, Any]:
    client = graph_client()
    payload = await client.request_device_code()
    cipher = OutlookTokenCipher(settings.jwt_secret_key)
    expires_in = int(payload.get("expires_in") or 900)
    interval = int(payload.get("interval") or 5)
    now = datetime.now(timezone.utc)
    session = {
        "device_code_encrypted": cipher.encrypt(str(payload["device_code"])),
        "user_code": payload.get("user_code"),
        "verification_uri": payload.get("verification_uri"),
        "verification_uri_complete": payload.get("verification_uri_complete"),
        "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
        "interval_seconds": interval,
        "message": payload.get("message"),
        "started_at": now.isoformat(),
    }
    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection["connection_id"]},
        {"$set": {"oauth_device_code_session": session, "updated_at": now.isoformat()}},
    )
    return {
        "connection_id": connection["connection_id"],
        "status": "pending_user",
        "device_code": _session_public(session),
    }


async def poll_device_code_for_connection(
    db: Any,
    connection: Dict[str, Any],
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    session = connection.get("oauth_device_code_session")
    if not session:
        raise DeviceCodeFlowError(
            "No device-code session for this connection. Start device-code flow first.",
            status_code=404,
        )

    expires_at = datetime.fromisoformat(str(session["expires_at"]))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if now >= expires_at:
        await db.outlook_calendar_connections.update_one(
            {"connection_id": connection["connection_id"]},
            {"$unset": {"oauth_device_code_session": ""}},
        )
        return {
            "connection_id": connection["connection_id"],
            "status": "expired",
            "device_code": _session_public(session),
        }

    cipher = OutlookTokenCipher(settings.jwt_secret_key)
    device_code = cipher.decrypt(session["device_code_encrypted"])
    client = graph_client()
    try:
        token = await client.poll_device_code(device_code)
    except httpx.HTTPStatusError as exc:
        body: Dict[str, Any] = {}
        if exc.response is not None:
            try:
                body = exc.response.json()
            except Exception:
                body = {}
        error = str(body.get("error") or "")
        if error in {"authorization_pending", "slow_down"}:
            return {
                "connection_id": connection["connection_id"],
                "status": "authorization_pending",
                "device_code": _session_public(session),
                "error": error,
            }
        if error == "expired_token":
            await db.outlook_calendar_connections.update_one(
                {"connection_id": connection["connection_id"]},
                {"$unset": {"oauth_device_code_session": ""}},
            )
            return {
                "connection_id": connection["connection_id"],
                "status": "expired",
                "device_code": _session_public(session),
            }
        raise DeviceCodeFlowError(
            f"Device-code token exchange failed: {error or exc}",
            status_code=502,
        ) from exc

    refresh_token = token.get("refresh_token")
    access_token = token.get("access_token")
    if not refresh_token or not access_token:
        raise DeviceCodeFlowError(
            "Microsoft did not return offline calendar access from device-code flow.",
            status_code=502,
        )

    profile = await client.get_me(access_token)
    stored = await persist_outlook_oauth_tokens(
        db,
        connection=connection,
        refresh_token=refresh_token,
        access_token=access_token,
        profile=profile,
        user_id=user_id,
        activate_pending=True,
    )
    return {
        "connection_id": connection["connection_id"],
        "status": "connected",
        "microsoft_email": stored.get("microsoft_email"),
        "device_code": _session_public(session),
    }
