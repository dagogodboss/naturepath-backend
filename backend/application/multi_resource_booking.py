"""
Booking-path bridge for multi-resource slots (Phase 3 wiring).

Gated by settings.multi_resource_scheduling (default False). When the flag is
off, callers must not use this module — legacy practitioner-global busy remains
authoritative.

PROVISIONAL until Jonathan confirms (see docs/plans/phase-0-jonathan-questions.md):
  Q3 — Last Discovery start: occupied must end ≤ 17:45. If occupied is 45 min,
       last start is 17:00 — NOT 17:15 until he confirms that "5:15" means
       customer-end only (busy may extend past session end).
  Q4 — Untagged/unmapped Outlook busy blocks the resource until review
       classifies it (already persisted as authoritative busy by Phase 2 sync).
  Q7 — Outlook/office priority for free times; app booking rows are not silently
       rewritten (payment/status). Conflicts → review_queue (see
       multi_resource_conflicts). Reschedule still updates slot only via app API.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from application.multi_resource_slots import (
    hhmm_from_minutes,
    minutes_from_hhmm,
    occupied_interval_for_session_start,
    slots_for_open_dates_preview,
)
from application.resource_availability import (
    ResourceCalendarUnavailable,
    assert_resource_calendar_ready,
    filter_slots_by_notice_and_window,
    resolve_required_resource_id,
)
from application.resource_reservation import active_reservation_busy_rows
from domain.entities.models import BusyIntervalSource, generate_id, utc_now
from domain.scheduling_occupation import resolve_customer_duration_minutes

logger = logging.getLogger(__name__)

# LOCKED Nichole: occupied must finish by 17:45 America/Chicago.
NICHOLE_OCCUPIED_FINISH_BY = "17:45"

# PROVISIONAL Q3: when resource has no last_start_time, derive last session
# start so occupied ends at NICHOLE_OCCUPIED_FINISH_BY (45m occupied → 17:00).
# Do not invent 17:15 until Jonathan confirms customer-end-only interpretation.


def session_minutes_for_service(service: Mapping[str, Any]) -> int:
    return resolve_customer_duration_minutes(
        int(service.get("duration_minutes") or 0),
        service.get("customer_duration_minutes"),
    )


def provisional_last_start_for_occupied_finish(
    *,
    prep_minutes: int,
    session_minutes: int,
    recovery_minutes: int,
    finish_by: str = NICHOLE_OCCUPIED_FINISH_BY,
) -> str:
    """
    PROVISIONAL Q3: last customer start such that occupied ends ≤ finish_by.

    Example: finish_by 17:45, occupied 45 (0+30+15 or 0+45+0) → last start 17:00.
    """
    finish_m = minutes_from_hhmm(finish_by)
    last_start_m = finish_m - session_minutes - recovery_minutes
    # Prep is before session start; occupied start = last_start - prep must still
    # land in free windows (engine enforces). Last *session* start clock:
    if last_start_m < 0:
        last_start_m = 0
    return hhmm_from_minutes(last_start_m)


def effective_last_start_time(
    resource: Mapping[str, Any],
    service: Mapping[str, Any],
) -> Optional[str]:
    """Prefer resource.last_start_time; else PROVISIONAL Q3 finish-by derivation."""
    explicit = resource.get("last_start_time")
    if explicit:
        return str(explicit)
    # Salt always seeds last_start_time=17:00. Practitioner/Discovery often
    # omits it — apply occupied-finish-by 17:45 rule (PROVISIONAL Q3).
    prep = int(service.get("prep_minutes") or 0)
    recovery = int(service.get("recovery_minutes") or 0)
    try:
        session_m = session_minutes_for_service(service)
    except ValueError:
        return NICHOLE_OCCUPIED_FINISH_BY
    return provisional_last_start_for_occupied_finish(
        prep_minutes=prep,
        session_minutes=session_m,
        recovery_minutes=recovery,
    )


def db_from_booking_repo(booking_repo: Any) -> Any:
    """Motor collections expose `.database`; test fakes may set it on the collection."""
    collection = getattr(booking_repo, "collection", None)
    if collection is None:
        return None
    db = getattr(collection, "database", None)
    if db is not None:
        return db
    # Some repos attach the db handle directly.
    return getattr(booking_repo, "db", None)


async def fetch_resource(db: Any, resource_id: str) -> Optional[Dict[str, Any]]:
    if db is None or not resource_id:
        return None
    col = getattr(db, "resources", None)
    if col is None:
        return None
    try:
        return await col.find_one({"resource_id": resource_id}, {"_id": 0})
    except Exception:
        logger.exception("Failed to load resource %s", resource_id)
        return None


def busy_intervals_for_slot_engine(
    busy_intervals: Sequence[Mapping[str, Any]],
    *,
    exclude_booking_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Busy rows fed into the slot engine.

    When rechecking the same booking (lock → confirm), ignore its own
    source=booking hold so confirm does not fail against its pending dual-write.
    """
    if not exclude_booking_id:
        return [dict(row) for row in busy_intervals]
    excluded = str(exclude_booking_id)
    out: List[Dict[str, Any]] = []
    for row in busy_intervals:
        if (
            str(row.get("source") or "").lower() == BusyIntervalSource.BOOKING.value
            and str(row.get("booking_id") or "") == excluded
        ):
            continue
        out.append(dict(row))
    return out


# Retries when active_busy_generation changes mid-read (issue #9 Codex follow-up).
_BUSY_READ_MAX_ATTEMPTS = 3


async def _load_active_busy_generations(
    db: Any,
    resource_id: str,
) -> Dict[str, int]:
    """
    Map connection_id → active_busy_generation for authoritative connections.

    Raises ResourceCalendarUnavailable on connection lookup failure (fail-closed).
    """
    from application.resource_availability import load_authoritative_connections

    connections = await load_authoritative_connections(db, resource_id)
    active_by_conn: Dict[str, int] = {}
    for conn in connections:
        cid = str(conn.get("connection_id") or "")
        if not cid:
            continue
        active = conn.get("active_busy_generation")
        if active is None:
            continue
        try:
            active_by_conn[cid] = int(active)
        except (TypeError, ValueError):
            continue
    return active_by_conn


def _filter_busy_rows_with_generations(
    rows: List[Dict[str, Any]],
    active_by_conn: Dict[str, int],
) -> List[Dict[str, Any]]:
    """
    Drop Outlook busy rows that are not the connection's active_busy_generation.

    During overlapping syncs, multiple generations may briefly coexist. Readers
    must not treat a superseded snapshot as capacity. Non-Outlook sources
    (booking holds) always pass through.
    """
    if not active_by_conn:
        return rows

    out: List[Dict[str, Any]] = []
    for row in rows:
        source = str(row.get("source") or "").lower()
        if source != BusyIntervalSource.OUTLOOK.value:
            out.append(row)
            continue
        cid = str(row.get("connection_id") or "")
        if cid not in active_by_conn:
            # Unknown connection / no active gen tracked — keep for fail-closed.
            out.append(row)
            continue
        gen = row.get("sync_generation")
        if gen is None:
            # Legacy untagged rows: keep until an active snapshot cleans them.
            out.append(row)
            continue
        try:
            if int(gen) == active_by_conn[cid]:
                out.append(row)
        except (TypeError, ValueError):
            continue
    return out


async def _filter_busy_rows_to_active_generations(
    db: Any,
    resource_id: str,
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compatibility wrapper: load generations then filter (no mid-read retry)."""
    if not rows:
        return rows
    try:
        active_by_conn = await _load_active_busy_generations(db, resource_id)
    except ResourceCalendarUnavailable:
        raise
    except Exception:
        logger.exception(
            "Failed resolving active busy generations for resource %s", resource_id
        )
        return rows
    return _filter_busy_rows_with_generations(rows, active_by_conn)


async def fetch_resource_busy(
    db: Any,
    resource_id: str,
    date_str: str,
    *,
    fail_closed: bool = True,
) -> List[Dict[str, Any]]:
    """
    Busy rows for one resource on one clinic-local date.

    PROVISIONAL Q4: untagged Outlook busy is stored as authoritative busy on the
    resource and therefore blocks slots until classified/review resolves it.
    Never mix another resource's busy into this list (Discovery ≠ Salt).

    Issue #9 A1: lookup failure must not be treated as successful-empty free.
    When fail_closed=True (default), raises ResourceCalendarUnavailable.

    Issue #9 Codex follow-up: generation + rows are read consistently. If sync
    advances active_busy_generation between the generation read and the busy
    row fetch, retry; if still inconsistent, fail closed rather than returning
    a false-empty result. A stable empty snapshot remains legitimate empty.
    """
    if db is None or not resource_id:
        if fail_closed:
            raise ResourceCalendarUnavailable(
                resource_id=resource_id or None,
            )
        return []
    col = getattr(db, "resource_busy_intervals", None)
    if col is None:
        if fail_closed:
            raise ResourceCalendarUnavailable(resource_id=resource_id)
        return []

    last_exc: Optional[BaseException] = None
    for attempt in range(_BUSY_READ_MAX_ATTEMPTS):
        try:
            gens_before = await _load_active_busy_generations(db, resource_id)
            rows = await col.find(
                {"resource_id": resource_id, "date": date_str},
                {"_id": 0},
            ).to_list(length=500)
            gens_after = await _load_active_busy_generations(db, resource_id)
        except ResourceCalendarUnavailable:
            raise
        except Exception as exc:
            last_exc = exc
            logger.exception(
                "Failed to load resource_busy_intervals for %s on %s (attempt %s)",
                resource_id,
                date_str,
                attempt + 1,
            )
            if fail_closed:
                continue
            return []

        if gens_before != gens_after:
            # Sync claimed a new generation mid-read — retry rather than
            # discarding pre-claim rows and missing the winner's insert.
            logger.info(
                "Busy read generation changed mid-flight for %s on %s "
                "(before=%s after=%s); retrying",
                resource_id,
                date_str,
                gens_before,
                gens_after,
            )
            continue

        return _filter_busy_rows_with_generations(list(rows), gens_after)

    if fail_closed:
        raise ResourceCalendarUnavailable(
            "Calendar busy lookup was inconsistent during sync; please retry shortly",
            resource_id=resource_id,
        ) from last_exc
    return []


async def fetch_resource_reservations(
    db: Any, resource_id: str, date_str: str
) -> List[Dict[str, Any]]:
    if db is None or not resource_id:
        return []
    col = getattr(db, "resource_reservations", None)
    if col is None:
        return []
    try:
        return await col.find(
            {"resource_id": resource_id, "date": date_str},
            {"_id": 0},
        ).to_list(length=500)
    except Exception as exc:
        logger.exception(
            "Failed to load resource_reservations for %s on %s",
            resource_id,
            date_str,
        )
        raise ResourceCalendarUnavailable(
            "Calendar reservation lookup failed; please retry shortly",
            resource_id=resource_id,
        ) from exc


def _pending_busy_still_active(row: Mapping[str, Any], now: datetime) -> bool:
    expires = row.get("expires_at")
    if not expires:
        return True
    text = str(expires)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        exp = datetime.fromisoformat(text)
    except ValueError:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    clock = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return exp > clock


def merge_busy_with_reservations(
    busy_intervals: Sequence[Mapping[str, Any]],
    reservations: Sequence[Mapping[str, Any]],
    *,
    exclude_booking_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Combine persisted busy + active reservations; drop expired pending busy."""
    clock = now or datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for row in busy_intervals:
        if (
            exclude_booking_id
            and str(row.get("source") or "").lower() == BusyIntervalSource.BOOKING.value
            and str(row.get("booking_id") or "") == str(exclude_booking_id)
        ):
            continue
        if (
            str(row.get("source") or "").lower() == BusyIntervalSource.BOOKING.value
            and row.get("expires_at")
            and not _pending_busy_still_active(row, clock)
        ):
            continue
        out.append(dict(row))
    out.extend(
        active_reservation_busy_rows(
            reservations,
            now=clock,
            exclude_booking_id=exclude_booking_id,
        )
    )
    return out


def compute_session_slots(
    *,
    date_str: str,
    service: Mapping[str, Any],
    resource: Mapping[str, Any],
    busy_intervals: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """Pure slot list for service+resource+busy (no DB)."""
    prep = int(service.get("prep_minutes") or 0)
    recovery = int(service.get("recovery_minutes") or 0)
    try:
        session_m = session_minutes_for_service(service)
    except ValueError:
        return []
    flags = service.get("flags") or {}
    # Inject effective last_start onto a shallow resource view for the preview facade.
    resource_view = dict(resource)
    last_start = effective_last_start_time(resource, service)
    if last_start:
        resource_view["last_start_time"] = last_start
    return slots_for_open_dates_preview(
        date_str=date_str,
        resource=resource_view,
        busy_intervals=busy_intervals,
        prep_minutes=prep,
        session_minutes=session_m,
        recovery_minutes=recovery,
        flags=flags,
        service_hours=service.get("service_hours"),
    )


async def slots_for_service_date(
    *,
    db: Any,
    service: Mapping[str, Any],
    date_str: str,
    now: Optional[datetime] = None,
) -> List[Dict[str, str]]:
    """
    Fail closed: missing/inactive required_resource_id or resource → [].

    Busy/sync failure raises ResourceCalendarUnavailable (not empty-busy=free).
    Does not fall back to practitioner-global busy (would break Discovery≠Salt).
    """
    rid = service.get("required_resource_id")
    if not rid:
        logger.warning(
            "multi_resource: service %s missing required_resource_id — empty slots",
            service.get("service_id"),
        )
        return []
    resource = await fetch_resource(db, str(rid))
    if not resource or resource.get("active") is False:
        logger.warning(
            "multi_resource: resource %s missing/inactive for service %s — empty slots",
            rid,
            service.get("service_id"),
        )
        return []
    await assert_resource_calendar_ready(db, str(rid), date_str=date_str)
    busy = await fetch_resource_busy(db, str(rid), date_str)
    reservations = await fetch_resource_reservations(db, str(rid), date_str)
    merged = merge_busy_with_reservations(busy, reservations, now=now)
    slots = compute_session_slots(
        date_str=date_str,
        service=service,
        resource=resource,
        busy_intervals=merged,
    )
    return filter_slots_by_notice_and_window(
        slots, service, date_str, now=now
    )


def slot_still_open(
    slots: Sequence[Mapping[str, str]],
    start_time: str,
    end_time: str,
) -> bool:
    return any(
        s.get("start_time") == start_time and s.get("end_time") == end_time for s in slots
    )


async def recheck_session_available(
    *,
    db: Any,
    service: Mapping[str, Any],
    date_str: str,
    start_time: str,
    end_time: str,
    exclude_booking_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Confirm-time recheck: regenerate slots and require exact session window."""
    try:
        rid = resolve_required_resource_id(service)
    except ValueError:
        return False
    resource = await fetch_resource(db, rid)
    if not resource or resource.get("active") is False:
        return False
    await assert_resource_calendar_ready(db, rid, date_str=date_str)
    busy = await fetch_resource_busy(db, rid, date_str)
    reservations = await fetch_resource_reservations(db, rid, date_str)
    merged = merge_busy_with_reservations(
        busy,
        reservations,
        exclude_booking_id=exclude_booking_id,
        now=now,
    )
    merged = busy_intervals_for_slot_engine(
        merged, exclude_booking_id=exclude_booking_id
    )
    slots = compute_session_slots(
        date_str=date_str,
        service=service,
        resource=resource,
        busy_intervals=merged,
    )
    slots = filter_slots_by_notice_and_window(
        slots, service, date_str, now=now
    )
    return slot_still_open(slots, start_time, end_time)


def occupied_times_for_session(
    service: Mapping[str, Any],
    start_time: str,
) -> Dict[str, str]:
    prep = int(service.get("prep_minutes") or 0)
    recovery = int(service.get("recovery_minutes") or 0)
    session_m = session_minutes_for_service(service)
    return occupied_interval_for_session_start(
        start_time,
        prep_minutes=prep,
        session_minutes=session_m,
        recovery_minutes=recovery,
    )


async def clear_booking_resource_busy(
    *,
    db: Any,
    booking_id: str,
    resource_id: str,
    date_str: str,
) -> None:
    """Remove source=booking busy row for a booking on one clinic-local date."""
    if db is None or not resource_id:
        return
    col = getattr(db, "resource_busy_intervals", None)
    if col is None:
        return
    try:
        await col.delete_many(
            {
                "booking_id": booking_id,
                "resource_id": resource_id,
                "date": date_str,
                "source": BusyIntervalSource.BOOKING.value,
            }
        )
    except Exception:
        logger.exception(
            "Failed to clear resource busy for booking %s on %s", booking_id, date_str
        )


async def dual_write_booking_busy(
    *,
    db: Any,
    resource_id: str,
    date_str: str,
    occupied_start: str,
    occupied_end: str,
    booking_id: str,
    expires_at: Optional[datetime] = None,
    hold_seconds: Optional[int] = None,
) -> None:
    """
    Write source=booking busy so subsequent open-dates see the hold.

    Pending holds pass expires_at (or hold_seconds) matching slot lock TTL (A3).
    Confirmed occupancy omits expires_at so cleanup leaves it alone.
    """
    if db is None or not resource_id:
        return
    col = getattr(db, "resource_busy_intervals", None)
    if col is None:
        return
    now = utc_now()
    now_iso = now.isoformat() if hasattr(now, "isoformat") else now
    exp: Optional[str] = None
    if expires_at is not None:
        exp = expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at)
    elif hold_seconds is not None:
        clock = now if isinstance(now, datetime) else datetime.now(timezone.utc)
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=timezone.utc)
        exp = (clock + timedelta(seconds=int(hold_seconds))).isoformat()
    doc = {
        "interval_id": generate_id(),
        "resource_id": resource_id,
        "date": date_str,
        "start_time": occupied_start,
        "end_time": occupied_end,
        "source": BusyIntervalSource.BOOKING.value,
        "authoritative": True,
        "booking_id": booking_id,
        "show_as": "busy",
        "is_cancelled": False,
        "expires_at": exp,
        "synced_at": now_iso,
        "created_at": now_iso,
    }
    try:
        # Idempotent on re-confirm of same booking window.
        await col.update_one(
            {
                "booking_id": booking_id,
                "resource_id": resource_id,
                "date": date_str,
                "source": BusyIntervalSource.BOOKING.value,
            },
            {"$set": doc},
            upsert=True,
        )
    except Exception:
        logger.exception(
            "Failed to dual-write resource busy for booking %s", booking_id
        )
