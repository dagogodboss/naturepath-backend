"""Minimal Microsoft Graph calendar client and token protection."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from cryptography.fernet import Fernet


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookTokenCipher:
    def __init__(self, secret: str):
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")


def _parse_graph_datetime(value: Dict[str, Any]) -> datetime:
    raw = str(value.get("dateTime") or "").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        zone_name = str(value.get("timeZone") or "UTC")
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(zone_name))
        except ZoneInfoNotFoundError:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def event_to_busy_intervals(event: Dict[str, Any], clinic_timezone: str) -> List[Dict[str, Any]]:
    """Split a Graph event into one busy interval per clinic-local day."""
    clinic_zone = ZoneInfo(clinic_timezone)
    start = _parse_graph_datetime(event.get("start") or {}).astimezone(clinic_zone)
    end = _parse_graph_datetime(event.get("end") or {}).astimezone(clinic_zone)
    if end <= start:
        return []

    intervals: List[Dict[str, Any]] = []
    day = start.date()
    while datetime.combine(day, time.min, clinic_zone) < end:
        day_start = datetime.combine(day, time.min, clinic_zone)
        next_day = day_start + timedelta(days=1)
        segment_start = max(start, day_start)
        segment_end = min(end, next_day)
        if segment_end > segment_start:
            intervals.append(
                {
                    "event_id": str(event["id"]),
                    "date": day.isoformat(),
                    "start_time": segment_start.strftime("%H:%M"),
                    "end_time": "24:00" if segment_end == next_day else segment_end.strftime("%H:%M"),
                    "show_as": str(event.get("showAs") or "busy").lower(),
                    "is_cancelled": bool(event.get("isCancelled", False)),
                    "starts_at": segment_start.isoformat(),
                    "ends_at": segment_end.isoformat(),
                }
            )
        day += timedelta(days=1)
    return intervals


def event_to_busy_interval(event: Dict[str, Any], clinic_timezone: str) -> Dict[str, Any]:
    """Backward-compatible helper for callers handling a same-day event."""
    intervals = event_to_busy_intervals(event, clinic_timezone)
    if not intervals:
        raise ValueError("Outlook event has no positive-duration interval")
    return intervals[0]


class MicrosoftGraphClient:
    scopes = "openid profile email offline_access Calendars.Read"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        redirect_uri: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id or "common"
        self.redirect_uri = redirect_uri
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0"

    def authorization_url(self, state: str) -> str:
        return f"{self.authority}/authorize?{urlencode({'client_id': self.client_id, 'response_type': 'code', 'redirect_uri': self.redirect_uri, 'response_mode': 'query', 'scope': self.scopes, 'state': state, 'prompt': 'select_account'})}"

    async def _token_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.authority}/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    **payload,
                },
            )
        response.raise_for_status()
        return response.json()

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        return await self._token_request(
            {"grant_type": "authorization_code", "code": code, "scope": self.scopes}
        )

    async def refresh(self, refresh_token: str) -> Dict[str, Any]:
        return await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": self.scopes}
        )

    async def get_me(self, access_token: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{GRAPH_BASE}/me?$select=id,displayName,mail,userPrincipalName",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        response.raise_for_status()
        return response.json()

    async def list_calendar_view(
        self,
        access_token: str,
        *,
        start: datetime,
        end: datetime,
    ) -> List[Dict[str, Any]]:
        url = f"{GRAPH_BASE}/me/calendarView"
        params = {
            "startDateTime": start.astimezone(timezone.utc).isoformat(),
            "endDateTime": end.astimezone(timezone.utc).isoformat(),
            "$select": "id,start,end,showAs,isCancelled,lastModifiedDateTime",
            "$top": "250",
        }
        events: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30) as client:
            while url:
                response = await client.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Prefer": 'outlook.timezone="UTC"',
                    },
                )
                response.raise_for_status()
                payload = response.json()
                events.extend(payload.get("value") or [])
                url = payload.get("@odata.nextLink")
                params = None
        return events

    async def create_subscription(
        self,
        access_token: str,
        *,
        notification_url: str,
        expiration: datetime,
        client_state: str,
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{GRAPH_BASE}/subscriptions",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "changeType": "created,updated,deleted",
                    "notificationUrl": notification_url,
                    "resource": "/me/events",
                    "expirationDateTime": expiration.astimezone(timezone.utc).isoformat(),
                    "clientState": client_state,
                },
            )
        response.raise_for_status()
        return response.json()
