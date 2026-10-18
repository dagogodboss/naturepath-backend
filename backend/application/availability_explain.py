"""
Structured “why unavailable” explainer (Phase 5 scaffold).

Pure functions only. Callers pass already-scoped busy intervals for the
required resource — Discovery busy on Nichole must not be mixed into Salt.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from application.multi_resource_slots import (
    free_intervals_for_resource,
    minutes_from_hhmm,
    occupied_interval_for_session_start,
    open_windows_for_date,
    service_forbids_weekday,
)
from domain.scheduling_occupation import resolve_customer_duration_minutes

# Stable reason codes (UI / i18n). See docs/plans/phase-5-why-unavailable.md.
SERVICE_WEEKDAY_CLOSED = "SERVICE_WEEKDAY_CLOSED"
RESOURCE_HOURS_CLOSED = "RESOURCE_HOURS_CLOSED"
RESOURCE_EXCEPTION = "RESOURCE_EXCEPTION"
BUSY_BOOKING = "BUSY_BOOKING"
BUSY_OUTLOOK = "BUSY_OUTLOOK"
BUSY_UNMAPPED_DEFAULT = "BUSY_UNMAPPED_DEFAULT"
OCCUPATION_OVERFLOW = "OCCUPATION_OVERFLOW"
MIN_NOTICE = "MIN_NOTICE"
OUTSIDE_BOOKING_WINDOW = "OUTSIDE_BOOKING_WINDOW"
SYNC_STALE = "SYNC_STALE"
PREREQUISITE_REQUIRED = "PREREQUISITE_REQUIRED"

# PROVISIONAL (Phase 2 §8.1): sync older than this is fail-closed.
SYNC_STALE_AFTER_MINUTES = 30


def _reason(
    code: str,
    message: str,
    *,
    blocking_event_id: Optional[str] = None,
    booking_id: Optional[str] = None,
    details: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {"code": code, "message": message}
    if blocking_event_id:
        row["blocking_event_id"] = blocking_event_id
    if booking_id:
        row["booking_id"] = booking_id
    if details:
        row["details"] = dict(details)
    return row


def sync_is_stale(
    *,
    last_sync_status: Optional[str] = None,
    last_synced_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    stale_after_minutes: int = SYNC_STALE_AFTER_MINUTES,
    outlook_required: bool = True,
) -> bool:
    """True when Outlook health should fail-close capacity for a resource."""
    if not outlook_required:
        return False
    if str(last_sync_status or "").lower() == "error":
        return True
    if last_synced_at is None:
        return True
    clock = now or datetime.now(timezone.utc)
    synced = last_synced_at
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    age = clock - synced
    return age > timedelta(minutes=stale_after_minutes)


def _session_minutes(service: Mapping[str, Any]) -> int:
    return resolve_customer_duration_minutes(
        int(service.get("duration_minutes") or 0),
        service.get("customer_duration_minutes"),
    )


def _intervals_overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def _occupied_fits_open(
    occupied_start: int,
    occupied_end: int,
    open_windows: Sequence[Mapping[str, str]],
) -> bool:
    for window in open_windows:
        w0 = minutes_from_hhmm(window["start_time"])
        w1 = minutes_from_hhmm(window["end_time"])
        if occupied_start >= w0 and occupied_end <= w1:
            return True
    return False


def _busy_reason_for_interval(event: Mapping[str, Any]) -> Dict[str, Any]:
    source = str(event.get("source") or "").lower()
    event_id = event.get("event_id")
    booking_id = event.get("booking_id")
    start = event.get("start_time")
    end = event.get("end_time")
    span = f"{start}–{end}" if start and end else "this time"

    if source == "booking":
        return _reason(
            BUSY_BOOKING,
            f"App booking occupies the resource {span}",
            booking_id=str(booking_id) if booking_id else None,
            details={"start_time": start, "end_time": end},
        )

    category = event.get("category_name")
    unmapped = bool(event.get("unmapped")) or (
        source == "outlook" and not category
    )
    if unmapped or source == "outlook" and not category:
        return _reason(
            BUSY_UNMAPPED_DEFAULT,
            f"Unclassified Outlook busy occupies the resource {span}",
            blocking_event_id=str(event_id) if event_id else None,
            details={"start_time": start, "end_time": end},
        )

    if source == "manual":
        return _reason(
            RESOURCE_EXCEPTION,
            f"Resource closed or blocked {span}",
            details={"start_time": start, "end_time": end, "source": "manual"},
        )

    # Default: mapped Outlook (or unknown source treated as outlook busy).
    label = f" ({category})" if category else ""
    return _reason(
        BUSY_OUTLOOK,
        f"Outlook busy{label} occupies the resource {span}",
        blocking_event_id=str(event_id) if event_id else None,
        details={
            "start_time": start,
            "end_time": end,
            "category_name": category,
        },
    )


def _blocking_busy(
    busy_intervals: Iterable[Mapping[str, Any]],
) -> List[Mapping[str, Any]]:
    """Same filters as the slot engine: authoritative, not free/cancelled/visibility."""
    out: List[Mapping[str, Any]] = []
    for event in busy_intervals:
        if event.get("is_cancelled") is True:
            continue
        if event.get("visibility_only") is True:
            continue
        if event.get("authoritative") is False:
            continue
        if str(event.get("show_as") or "busy").lower() == "free":
            continue
        out.append(event)
    return out


def explain_availability(
    *,
    date_str: str,
    service: Mapping[str, Any],
    resource: Mapping[str, Any],
    busy_intervals: Sequence[Mapping[str, Any]] = (),
    start_time: Optional[str] = None,
    sync_stale: bool = False,
    now: Optional[datetime] = None,
    prerequisites_met: bool = True,
) -> Dict[str, Any]:
    """
    Return structured unavailability reasons for service + resource + date
    (and optional session start).

    Inputs are plain mappings so unit tests need no DB. Pass only busy rows for
    the required resource.
    """
    reasons: List[Dict[str, Any]] = []
    flags = service.get("flags") or {}
    weekly_hours = resource.get("weekly_hours") or []
    service_hours = service.get("service_hours")
    prep = int(service.get("prep_minutes") or 0)
    recovery = int(service.get("recovery_minutes") or 0)

    if service_forbids_weekday(date_str, flags=flags):
        reasons.append(
            _reason(
                SERVICE_WEEKDAY_CLOSED,
                "Service is not offered on this weekday",
                details={"date": date_str, "weekday": date.fromisoformat(date_str).weekday()},
            )
        )

    if sync_stale:
        reasons.append(
            _reason(
                SYNC_STALE,
                "Outlook sync is unhealthy for this resource; booking is fail-closed",
                details={"resource_id": resource.get("resource_id")},
            )
        )

    if not prerequisites_met:
        reasons.append(
            _reason(
                PREREQUISITE_REQUIRED,
                "A required prior booking is missing for this service",
            )
        )

    open_windows = open_windows_for_date(
        weekly_hours, date_str, service_hours=service_hours
    )

    # Day-level: no open windows after resource (+ optional service) hours.
    if not open_windows and not any(r["code"] == SERVICE_WEEKDAY_CLOSED for r in reasons):
        reasons.append(
            _reason(
                RESOURCE_HOURS_CLOSED,
                "Resource has no weekly hours on this weekday",
                details={"date": date_str},
            )
        )

    # Notice / booking window (only meaningful with a concrete start).
    if start_time and now is not None:
        min_notice = service.get("min_notice_minutes")
        booking_window_days = service.get("booking_window_days")
        try:
            start_m = minutes_from_hhmm(start_time)
        except ValueError:
            start_m = None
        if start_m is not None:
            # Clinic-local wall clock: interpret `now` date+time vs date_str+start.
            # When `now` is timezone-aware UTC we only compare calendar/time components
            # if callers pass a naive clinic-local datetime (preferred for tests).
            clinic_now = now.replace(tzinfo=None) if now.tzinfo else now
            slot_dt = datetime(
                *date.fromisoformat(date_str).timetuple()[:3],
                start_m // 60,
                start_m % 60,
            )
            if min_notice is not None:
                earliest = clinic_now + timedelta(minutes=int(min_notice))
                if slot_dt < earliest:
                    reasons.append(
                        _reason(
                            MIN_NOTICE,
                            "Start is inside the minimum booking notice window",
                            details={
                                "min_notice_minutes": int(min_notice),
                                "start_time": start_time,
                            },
                        )
                    )
            if booking_window_days is not None:
                latest_date = clinic_now.date() + timedelta(days=int(booking_window_days))
                if date.fromisoformat(date_str) > latest_date:
                    reasons.append(
                        _reason(
                            OUTSIDE_BOOKING_WINDOW,
                            "Date is beyond the book-ahead window",
                            details={
                                "booking_window_days": int(booking_window_days),
                                "date": date_str,
                            },
                        )
                    )

    if start_time:
        try:
            session_m = _session_minutes(service)
        except ValueError:
            session_m = int(service.get("duration_minutes") or 60)

        try:
            occupied = occupied_interval_for_session_start(
                start_time,
                prep_minutes=prep,
                session_minutes=session_m,
                recovery_minutes=recovery,
            )
            occ_start = minutes_from_hhmm(occupied["start_time"])
            occ_end = minutes_from_hhmm(occupied["end_time"])
            session_start_m = minutes_from_hhmm(start_time)
        except ValueError:
            reasons.append(
                _reason(
                    RESOURCE_HOURS_CLOSED,
                    "Requested start is outside a valid clock range",
                    details={"start_time": start_time},
                )
            )
            return {
                "available": False,
                "reasons": reasons,
                "date": date_str,
                "start_time": start_time,
                "resource_id": resource.get("resource_id"),
                "service_id": service.get("service_id"),
            }

        # Session start outside open windows → hours closed.
        start_in_open = False
        for window in open_windows:
            w0 = minutes_from_hhmm(window["start_time"])
            w1 = minutes_from_hhmm(window["end_time"])
            if w0 <= session_start_m < w1:
                start_in_open = True
                break
        if open_windows and not start_in_open:
            reasons.append(
                _reason(
                    RESOURCE_HOURS_CLOSED,
                    f"Start {start_time} is outside resource hours",
                    details={
                        "start_time": start_time,
                        "open_windows": list(open_windows),
                    },
                )
            )
        elif open_windows and not _occupied_fits_open(occ_start, occ_end, open_windows):
            reasons.append(
                _reason(
                    OCCUPATION_OVERFLOW,
                    (
                        f"Session+prep+recovery "
                        f"({occupied['start_time']}–{occupied['end_time']}) "
                        f"does not fit in open hours"
                    ),
                    details={
                        "occupied_start": occupied["start_time"],
                        "occupied_end": occupied["end_time"],
                        "start_time": start_time,
                    },
                )
            )

        for event in _blocking_busy(busy_intervals):
            try:
                b0 = minutes_from_hhmm(str(event["start_time"]))
                b1 = minutes_from_hhmm(str(event["end_time"]))
            except (KeyError, ValueError):
                continue
            if _intervals_overlap(occ_start, occ_end, b0, b1):
                reasons.append(_busy_reason_for_interval(event))

    available = len(reasons) == 0
    return {
        "available": available,
        "reasons": reasons,
        "date": date_str,
        "start_time": start_time,
        "resource_id": resource.get("resource_id"),
        "service_id": service.get("service_id"),
        # Convenience for day-level preview when start omitted.
        "open_windows": open_windows if not start_time else None,
        "free_intervals": (
            free_intervals_for_resource(
                weekly_hours,
                busy_intervals,
                date_str,
                service_hours=service_hours,
            )
            if not start_time and not sync_stale and available
            else None
        ),
    }
