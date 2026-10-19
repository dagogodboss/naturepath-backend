"""
Shared resource availability policy for multi-resource booking (issue #9 A1/A6).

Fail-closed: busy lookup failure and stale/unhealthy Outlook connections must not
be treated as an empty free calendar. Notice/window settings are enforced here
so customer mutate paths are not UI-only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from application.availability_explain import (
    MIN_NOTICE,
    OUTSIDE_BOOKING_WINDOW,
    SYNC_STALE,
    SYNC_STALE_AFTER_MINUTES,
    sync_is_stale,
)
from application.multi_resource_slots import minutes_from_hhmm
from core.time_utils import clinic_now

logger = logging.getLogger(__name__)


class ResourceCalendarUnavailable(ValueError):
    """Required calendar evidence is missing, stale, or incomplete."""

    def __init__(
        self,
        message: str = (
            "Calendar availability is temporarily unavailable; please retry shortly"
        ),
        *,
        code: str = SYNC_STALE,
        resource_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.resource_id = resource_id


class BookingWindowViolation(ValueError):
    """Service min-notice or book-ahead window rejected the requested start."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class CalendarEvidence:
    """Successful-empty vs unavailable for one resource."""

    resource_id: str
    ready: bool
    reason_code: Optional[str] = None
    message: Optional[str] = None


def _parse_synced_at(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


async def load_authoritative_connections(
    db: Any, resource_id: str
) -> List[Dict[str, Any]]:
    """Connections that authoritatively cover this resource (not visibility-only)."""
    if db is None or not resource_id:
        return []
    connections_col = getattr(db, "outlook_calendar_connections", None)
    if connections_col is None:
        return []
    try:
        return await connections_col.find(
            {
                "$or": [
                    {"authoritative_for_resource_ids": resource_id},
                    {"category_maps.resource_ids": resource_id},
                ],
                "visibility_only": {"$ne": True},
            },
            {"_id": 0},
        ).to_list(50)
    except Exception:
        logger.exception(
            "Failed to load outlook connections for resource %s", resource_id
        )
        raise ResourceCalendarUnavailable(
            "Calendar connection lookup failed; please retry shortly",
            code=SYNC_STALE,
            resource_id=resource_id,
        )


def connection_is_stale(
    conn: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
    stale_after_minutes: int = SYNC_STALE_AFTER_MINUTES,
) -> bool:
    return sync_is_stale(
        last_sync_status=conn.get("last_sync_status"),
        last_synced_at=_parse_synced_at(conn.get("last_synced_at")),
        now=now or datetime.now(timezone.utc),
        stale_after_minutes=stale_after_minutes,
        outlook_required=True,
    )


async def evaluate_resource_calendar_evidence(
    db: Any,
    resource_id: str,
    *,
    now: Optional[datetime] = None,
    date_str: Optional[str] = None,
) -> CalendarEvidence:
    """
    Distinguish successful-empty (no authoritative connections → ready) from
    unavailable/incomplete/stale when connections exist.
    """
    connections = await load_authoritative_connections(db, resource_id)
    if not connections:
        return CalendarEvidence(resource_id=resource_id, ready=True)

    clock = now or datetime.now(timezone.utc)
    for conn in connections:
        if connection_is_stale(conn, now=clock):
            return CalendarEvidence(
                resource_id=resource_id,
                ready=False,
                reason_code=SYNC_STALE,
                message=(
                    "Outlook sync is unhealthy for this resource; "
                    "booking is fail-closed"
                ),
            )
        # Optional explicit sync coverage horizon (when syncer records it).
        if date_str:
            through = conn.get("synced_through_date") or conn.get("sync_end_date")
            if through and str(date_str) > str(through):
                return CalendarEvidence(
                    resource_id=resource_id,
                    ready=False,
                    reason_code=OUTSIDE_BOOKING_WINDOW,
                    message=(
                        "Requested date is beyond the successfully synced "
                        "calendar horizon"
                    ),
                )
    return CalendarEvidence(resource_id=resource_id, ready=True)


async def assert_resource_calendar_ready(
    db: Any,
    resource_id: str,
    *,
    now: Optional[datetime] = None,
    date_str: Optional[str] = None,
) -> None:
    evidence = await evaluate_resource_calendar_evidence(
        db, resource_id, now=now, date_str=date_str
    )
    if not evidence.ready:
        raise ResourceCalendarUnavailable(
            evidence.message
            or "Calendar availability is temporarily unavailable; please retry shortly",
            code=evidence.reason_code or SYNC_STALE,
            resource_id=resource_id,
        )


async def resource_sync_stale(db: Any, resource_id: str) -> bool:
    """Admin/explain helper: True when authoritative connections are unhealthy."""
    try:
        evidence = await evaluate_resource_calendar_evidence(db, resource_id)
    except ResourceCalendarUnavailable:
        return True
    return not evidence.ready


def evaluate_notice_and_window(
    service: Mapping[str, Any],
    date_str: str,
    start_time: str,
    *,
    now: Optional[datetime] = None,
) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """
    Return (code, message, details) when the start violates notice/window;
    None when allowed. Uses clinic-local wall clock.
    """
    clock = now if now is not None else clinic_now()
    clinic_local = clock.replace(tzinfo=None) if clock.tzinfo else clock
    try:
        start_m = minutes_from_hhmm(start_time)
    except ValueError:
        return (
            MIN_NOTICE,
            "Invalid start time",
            {"start_time": start_time},
        )
    slot_dt = datetime(
        *date.fromisoformat(date_str).timetuple()[:3],
        start_m // 60,
        start_m % 60,
    )
    min_notice = service.get("min_notice_minutes")
    if min_notice is not None:
        earliest = clinic_local + timedelta(minutes=int(min_notice))
        if slot_dt < earliest:
            return (
                MIN_NOTICE,
                "Start is inside the minimum booking notice window",
                {
                    "min_notice_minutes": int(min_notice),
                    "start_time": start_time,
                },
            )
    booking_window_days = service.get("booking_window_days")
    if booking_window_days is not None:
        latest_date = clinic_local.date() + timedelta(days=int(booking_window_days))
        if date.fromisoformat(date_str) > latest_date:
            return (
                OUTSIDE_BOOKING_WINDOW,
                "Date is beyond the book-ahead window",
                {
                    "booking_window_days": int(booking_window_days),
                    "date": date_str,
                },
            )
    return None


def assert_notice_and_window(
    service: Mapping[str, Any],
    date_str: str,
    start_time: str,
    *,
    now: Optional[datetime] = None,
) -> None:
    violation = evaluate_notice_and_window(
        service, date_str, start_time, now=now
    )
    if violation is None:
        return
    code, message, details = violation
    raise BookingWindowViolation(message, code=code, details=details)


def filter_slots_by_notice_and_window(
    slots: Sequence[Mapping[str, str]],
    service: Mapping[str, Any],
    date_str: str,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for slot in slots:
        start = slot.get("start_time")
        if not start:
            continue
        if evaluate_notice_and_window(service, date_str, start, now=now) is None:
            out.append(dict(slot))
    return out


def resolve_required_resource_id(
    service: Mapping[str, Any],
) -> str:
    """
    Single resolved resource for validate/reserve/persist/cleanup.

    Policy (issue #9 A5): current service.required_resource_id is authoritative
    (deliberate migration when admin reassigns the service). Callers must clear
    any prior booking.resource_id busy only after the new reservation succeeds.
    """
    rid = service.get("required_resource_id")
    if not rid:
        raise ValueError("Service has no required resource")
    return str(rid)
