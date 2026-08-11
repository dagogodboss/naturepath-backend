"""Persist a practitioner's Outlook busy intervals for booking conflict checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from core.config import settings
from infrastructure.external.microsoft_graph import (
    MicrosoftGraphClient,
    OutlookTokenCipher,
    event_to_busy_intervals,
)


def graph_client() -> MicrosoftGraphClient:
    return MicrosoftGraphClient(
        client_id=settings.microsoft_client_id or "",
        client_secret=settings.microsoft_client_secret or "",
        tenant_id=settings.microsoft_tenant_id,
        redirect_uri=settings.microsoft_redirect_uri or "",
    )


async def sync_outlook_connection(db: Any, connection: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    client = graph_client()
    cipher = OutlookTokenCipher(settings.jwt_secret_key)
    refresh_token = cipher.decrypt(connection["refresh_token_encrypted"])
    token = await client.refresh(refresh_token)
    access_token = token["access_token"]
    next_refresh = token.get("refresh_token") or refresh_token
    start = now - timedelta(days=1)
    end = now + timedelta(days=180)
    events = await client.list_calendar_view(access_token, start=start, end=end)

    intervals = []
    for event in events:
        for interval in event_to_busy_intervals(event, settings.clinic_timezone):
            interval.update(
                {
                    "practitioner_id": connection["practitioner_id"],
                    "connection_id": connection["connection_id"],
                    "source": "outlook",
                    "synced_at": now.isoformat(),
                }
            )
            intervals.append(interval)

    await db.outlook_calendar_events.delete_many(
        {"connection_id": connection["connection_id"]}
    )
    if intervals:
        await db.outlook_calendar_events.insert_many(intervals)
    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection["connection_id"]},
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
