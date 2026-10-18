"""Persist Microsoft OAuth tokens on outlook_calendar_connections rows."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core.config import settings
from infrastructure.external.microsoft_graph import OutlookTokenCipher


async def persist_outlook_oauth_tokens(
    db: Any,
    *,
    connection: Dict[str, Any],
    refresh_token: str,
    access_token: str,
    profile: Dict[str, Any],
    user_id: Optional[str] = None,
    activate_pending: bool = True,
) -> Dict[str, Any]:
    """
    Encrypt refresh token, update profile fields, optionally activate oauth_pending placeholders.
    Returns the connection_id written.
    """
    connection_id = connection["connection_id"]
    now = datetime.now(timezone.utc).isoformat()
    cipher = OutlookTokenCipher(settings.jwt_secret_key)
    microsoft_email = profile.get("mail") or profile.get("userPrincipalName")

    patch: Dict[str, Any] = {
        "refresh_token_encrypted": cipher.encrypt(refresh_token),
        "microsoft_user_id": profile.get("id"),
        "updated_at": now,
    }
    if microsoft_email:
        patch["microsoft_email"] = microsoft_email
    if user_id:
        patch["user_id"] = user_id
    if activate_pending and connection.get("oauth_pending"):
        patch["is_active"] = True
        patch["oauth_pending"] = False

    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection_id},
        {
            "$set": patch,
            "$unset": {
                "oauth_device_code_session": "",
                "last_sync_error": "",
            },
        },
    )

    if settings.microsoft_graph_webhook_url:
        from application.outlook_sync import graph_client

        client = graph_client()
        client_state = secrets.token_urlsafe(32)
        try:
            subscription = await client.create_subscription(
                access_token,
                notification_url=settings.microsoft_graph_webhook_url,
                expiration=datetime.now(timezone.utc) + timedelta(days=3),
                client_state=client_state,
            )
            await db.outlook_calendar_connections.update_one(
                {"connection_id": connection_id},
                {
                    "$set": {
                        "subscription_id": subscription.get("id"),
                        "subscription_expires_at": subscription.get("expirationDateTime"),
                        "subscription_client_state": client_state,
                    }
                },
            )
        except Exception as exc:
            await db.outlook_calendar_connections.update_one(
                {"connection_id": connection_id},
                {"$set": {"subscription_error": str(exc)[:500]}},
            )

    from workers.outlook_calendar_worker import sync_outlook_connection_task

    sync_outlook_connection_task.delay(connection_id)
    return {"connection_id": connection_id, "microsoft_email": microsoft_email}
