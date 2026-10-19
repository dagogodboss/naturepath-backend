"""Persist a practitioner's Outlook busy intervals for booking conflict checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from application.outlook_category_sync import (
    MultiResourceSyncConfigError,
    _read_active_busy_generation,
    persist_resource_busy_from_events,
)
from core.config import settings
from infrastructure.external.microsoft_graph import (
    MicrosoftGraphClient,
    OutlookTokenCipher,
    event_to_busy_intervals,
)

# Test seam: awaited after final prepublication ownership read (Codex B1 window).
_legacy_pre_publish_hook: Optional[Callable[..., Awaitable[None]]] = None
# Test seam: awaited after successful legacy CAS, before older-generation cleanup
# (Codex B1: delayed cleanup must not delete newer generations).
_legacy_post_cas_hook: Optional[Callable[..., Awaitable[None]]] = None


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


def _connection_uses_app_only(connection: Dict[str, Any]) -> bool:
    if str(connection.get("auth_mode") or "").lower() == "application":
        return True
    return bool(settings.outlook_app_only_sync_enabled) and bool(
        connection.get("mailbox_email") or connection.get("microsoft_email")
    )


async def sync_outlook_connection(db: Any, connection: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    connection_id = connection["connection_id"]
    client = graph_client()
    cipher = OutlookTokenCipher(settings.jwt_secret_key)
    next_refresh: str | None = None
    try:
        start = now - timedelta(days=1)
        end = now + timedelta(days=180)
        if _connection_uses_app_only(connection):
            mailbox = (
                connection.get("mailbox_email") or connection.get("microsoft_email") or ""
            ).strip()
            if not mailbox:
                raise OutlookSyncError(
                    "Application calendar sync requires mailbox_email on the connection.",
                    status_code=502,
                )
            token = await client.client_credentials_token()
            access_token = token["access_token"]
            events = await client.list_user_calendar_view(
                access_token, mailbox, start=start, end=end
            )
        else:
            refresh_token = cipher.decrypt(connection["refresh_token_encrypted"])
            token = await client.refresh(refresh_token)
            access_token = token["access_token"]
            next_refresh = token.get("refresh_token") or refresh_token
            events = await client.list_calendar_view(access_token, start=start, end=end)
    except OutlookSyncError:
        raise
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
            if _connection_uses_app_only(connection):
                raise OutlookSyncError(
                    "Application calendar access denied. Entra admin must grant "
                    "Calendars.Read (application) admin consent for this app.",
                    status_code=502,
                ) from exc
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

    # Legacy practitioner-scoped busy (always dual-written; sole path when flag off).
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

    multi_resource_meta: Dict[str, Any] = {}
    if settings.multi_resource_scheduling:
        # Fail closed before any resource busy wipe when maps/resources missing.
        try:
            multi_resource_meta = await persist_resource_busy_from_events(
                db,
                connection,
                events,
                clinic_timezone=settings.clinic_timezone,
                synced_at=now,
            )
        except MultiResourceSyncConfigError as exc:
            await _mark_sync_error(db, connection_id, exc)
            raise OutlookSyncError(str(exc), status_code=502) from exc

        # Stale concurrent loser must not publish legacy events or "ok" freshness
        # while a newer sync owns the busy snapshot (issue #9 B1 follow-up).
        if multi_resource_meta.get("skipped_stale_generation"):
            return {
                "status": "skipped_stale_generation",
                "event_count": 0,
                "last_synced_at": connection.get("last_synced_at"),
                **multi_resource_meta,
            }

    publish_generation = multi_resource_meta.get("active_busy_generation")
    fenced_legacy = (
        settings.multi_resource_scheduling and publish_generation is not None
    )
    if fenced_legacy:
        # Generation-fence publication: re-check ownership immediately before
        # any legacy/success writes (Codex: fence must not be an earlier read).
        active_now = await _read_active_busy_generation(db, connection_id)
        if active_now is not None and int(active_now) != int(publish_generation):
            return {
                "status": "skipped_stale_generation",
                "event_count": 0,
                "last_synced_at": connection.get("last_synced_at"),
                "skipped_stale_generation": True,
                "resource_interval_count": 0,
                "review_item_count": 0,
                "sync_conflict_review_count": 0,
            }
        # Codex B1 window: after ownership read, before legacy mutation.
        if _legacy_pre_publish_hook is not None:
            await _legacy_pre_publish_hook(
                connection_id=connection_id,
                publish_generation=int(publish_generation),
            )

    sync_patch: Dict[str, Any] = {
        "last_synced_at": now.isoformat(),
        "last_sync_status": "ok",
        "last_sync_error": None,
        "event_count": len(intervals),
        "updated_at": now.isoformat(),
    }
    if next_refresh is not None:
        sync_patch["refresh_token_encrypted"] = cipher.encrypt(next_refresh)

    if fenced_legacy:
        # Insert-then-CAS-then-delete-old so a delayed loser cannot wipe the
        # winner's practitioner-calendar events after the ownership read
        # (issue #9 B1 compatibility publication).
        gen = int(publish_generation)
        tagged = []
        for interval in intervals:
            row = dict(interval)
            row["sync_generation"] = gen
            tagged.append(row)
        if tagged:
            await db.outlook_calendar_events.insert_many(tagged)

        publish_filter: Dict[str, Any] = {
            "connection_id": connection_id,
            "active_busy_generation": gen,
        }
        publish_result = await db.outlook_calendar_connections.update_one(
            publish_filter,
            {
                "$set": {
                    **sync_patch,
                    "active_legacy_generation": gen,
                }
            },
        )
        try:
            published = int(getattr(publish_result, "modified_count", 0) or 0) > 0
            matched = int(getattr(publish_result, "matched_count", 0) or 0) > 0
        except (TypeError, ValueError):
            published = True
            matched = True

        if not published and not matched:
            await db.outlook_calendar_events.delete_many(
                {
                    "connection_id": connection_id,
                    "sync_generation": gen,
                }
            )
            return {
                "status": "skipped_stale_generation",
                "event_count": 0,
                "last_synced_at": connection.get("last_synced_at"),
                "skipped_stale_generation": True,
                "resource_interval_count": 0,
                "review_item_count": 0,
                "sync_conflict_review_count": 0,
            }

        # Codex B1: A can CAS gen N then pause; B publishes M>N and finishes.
        # A's delayed cleanup must not delete M. Fence after CAS for that window.
        if _legacy_post_cas_hook is not None:
            await _legacy_post_cas_hook(
                connection_id=connection_id,
                publish_generation=gen,
            )

        # Drop ONLY strictly older / untagged legacy rows — never newer gens.
        # `$ne` would wipe a concurrent winner that published after our CAS
        # (issue #9 Codex follow-up at 494c821).
        await db.outlook_calendar_events.delete_many(
            {
                "connection_id": connection_id,
                "$or": [
                    {"sync_generation": {"$lt": gen}},
                    {"sync_generation": {"$exists": False}},
                ],
            }
        )
    else:
        # Flag-off / no generation: legacy delete-then-insert path.
        await db.outlook_calendar_events.delete_many({"connection_id": connection_id})
        if intervals:
            await db.outlook_calendar_events.insert_many(intervals)
        await db.outlook_calendar_connections.update_one(
            {"connection_id": connection_id},
            {"$set": sync_patch},
        )

    result: Dict[str, Any] = {
        "status": "ok",
        "event_count": len(intervals),
        "last_synced_at": now.isoformat(),
    }
    if multi_resource_meta:
        result.update(multi_resource_meta)
    return result
