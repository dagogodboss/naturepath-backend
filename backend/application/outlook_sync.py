"""Persist a practitioner's Outlook busy intervals for booking conflict checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx

from core.config import settings
from infrastructure.external.microsoft_graph import (
    MicrosoftGraphClient,
    OutlookTokenCipher,
    event_to_busy_intervals,
)


class OutlookSyncError(Exception):
    """Graph/token failure that should surface as a controlled API error, not 500."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def graph_client() -> MicrosoftGraphClient:
    return MicrosoftGraphClient(
        client_id=settings.microsoft_client_id or "",
        client_secret=settings.microsoft_client_secret or "",
        tenant_id=settings.microsoft_tenant_id,
        redirect_uri=settings.microsoft_redirect_uri or "",
    )


async def _mark_sync_error(db: Any, connection_id: str, exc: Exception) -> None:
    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection_id},
        {
            "$set": {
                "last_sync_status": "error",
                "last_sync_error": str(exc)[:1000],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


async def sync_outlook_connection(db: Any, connection: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    connection_id = connection["connection_id"]
    client = graph_client()
    cipher = OutlookTokenCipher(settings.jwt_secret_key)
    try:
        refresh_token = cipher.decrypt(connection["refresh_token_encrypted"])
        token = await client.refresh(refresh_token)
        access_token = token["access_token"]
        next_refresh = token.get("refresh_token") or refresh_token
        start = now - timedelta(days=1)
        end = now + timedelta(days=180)
        events = await client.list_calendar_view(access_token, start=start, end=end)
    except httpx.HTTPStatusError as exc:
        await _mark_sync_error(db, connection_id, exc)
        status = exc.response.status_code if exc.response is not None else 502
        if status == 404:
            raise OutlookSyncError(
                "Outlook calendar was not found for this Microsoft account. "
                "Confirm the mailbox has an Exchange Online calendar, then reconnect.",
                status_code=502,
            ) from exc
        if status in {401, 403}:
            raise OutlookSyncError(
                "Outlook calendar access expired or was revoked. Reconnect Outlook.",
                status_code=401,
            ) from exc
        raise OutlookSyncError(
            f"Outlook calendar sync failed ({status}). Try again shortly.",
            status_code=502,
        ) from exc
    except Exception as exc:
        await _mark_sync_error(db, connection_id, exc)
        raise OutlookSyncError(
            "Outlook calendar sync failed. Try again shortly.",
            status_code=502,
        ) from exc

    intervals = []
    for event in events:
        for interval in event_to_busy_intervals(event, settings.clinic_timezone):
            interval.update(
                {
                    "practitioner_id": connection["practitioner_id"],
                    "connection_id": connection_id,
                    "source": "outlook",
                    "synced_at": now.isoformat(),
                }
            )
            intervals.append(interval)

    await db.outlook_calendar_events.delete_many({"connection_id": connection_id})
    if intervals:
        await db.outlook_calendar_events.insert_many(intervals)
    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection_id},
        {
            "$set": {
                "refresh_token_encrypted": cipher.encrypt(next_refresh),
                "last_synced_at": now.isoformat(),
                "last_sync_status": "ok",
                "last_sync_error": None,
                "event_count": len(intervals),
                "updated_at": now.isoformat(),
            }
        },
    )
    return {"status": "ok", "event_count": len(intervals), "last_synced_at": now.isoformat()}
