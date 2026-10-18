"""
Q7 safer-B: when Outlook/office authoritative busy wins over an app booking action,
enqueue review — do not silently rewrite payment or booking status.

Used from BookingUseCase confirm/reschedule (and slot recheck) when
settings.multi_resource_scheduling is True.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Sequence

from application.multi_resource_booking import fetch_resource_busy, occupied_times_for_session
from application.multi_resource_slots import minutes_from_hhmm
from domain.entities.models import (
    BusyIntervalSource,
    ReviewQueueItemStatus,
    ReviewQueueItemType,
    generate_id,
    utc_now,
)

logger = logging.getLogger(__name__)

OFFICE_CONFLICT_MESSAGE = (
    "Office calendar busy blocks this app booking; staff review required (Q7)."
)
SYNC_CONFLICT_MESSAGE = (
    "Authoritative Outlook/manual busy overlaps a confirmed app booking; "
    "staff review required (Q7)."
)


def _intervals_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def _is_blocking_row(row: Mapping[str, Any]) -> bool:
    if row.get("is_cancelled") is True:
        return False
    if row.get("visibility_only") is True:
        return False
    if row.get("authoritative") is False:
        return False
    if str(row.get("show_as") or "busy").lower() == "free":
        return False
    return True


def find_office_busy_blocking_occupied(
    busy_rows: Sequence[Mapping[str, Any]],
    *,
    occupied_start: str,
    occupied_end: str,
    exclude_booking_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    First authoritative busy row overlapping occupied that is not solely this booking.

    Outlook/manual sources always count. Booking source counts only when tied to
    another booking_id (app-app race is not office priority).
    """
    try:
        occ_s = minutes_from_hhmm(occupied_start)
        occ_e = minutes_from_hhmm(occupied_end)
    except ValueError:
        return None

    for row in busy_rows:
        if not _is_blocking_row(row):
            continue
        try:
            b_s = minutes_from_hhmm(str(row["start_time"]))
            b_e = minutes_from_hhmm(str(row["end_time"]))
        except (KeyError, ValueError):
            continue
        if not _intervals_overlap(occ_s, occ_e, b_s, b_e):
            continue

        source = str(row.get("source") or "").lower()
        if source == BusyIntervalSource.BOOKING.value:
            other_id = row.get("booking_id")
            if exclude_booking_id and other_id == exclude_booking_id:
                continue
            if other_id:
                continue  # another app booking — not office/outlook priority
            continue

        return dict(row)

    return None


def _is_outlook_or_manual_authoritative_busy(row: Mapping[str, Any]) -> bool:
    if not _is_blocking_row(row):
        return False
    source = str(row.get("source") or "").lower()
    return source in (
        BusyIntervalSource.OUTLOOK.value,
        BusyIntervalSource.MANUAL.value,
    )


def _booking_occupied_window(
    booking: Mapping[str, Any],
) -> Optional[tuple[str, str, str]]:
    """Clinic date and occupied HH:MM window for a booking row."""
    slot = booking.get("slot") or {}
    date_str = slot.get("date")
    if not date_str:
        return None
    occ_start = booking.get("occupied_start_time") or slot.get("start_time")
    occ_end = booking.get("occupied_end_time") or slot.get("end_time")
    if not occ_start or not occ_end:
        return None
    return str(date_str), str(occ_start), str(occ_end)


def confirmed_booking_overlaps_busy_interval(
    booking: Mapping[str, Any],
    busy_row: Mapping[str, Any],
) -> bool:
    """True when a confirmed booking's occupied window overlaps office/manual busy."""
    if not _is_outlook_or_manual_authoritative_busy(busy_row):
        return False
    window = _booking_occupied_window(booking)
    if not window:
        return False
    date_str, occ_start, occ_end = window
    if str(busy_row.get("date") or "") != date_str:
        return False
    resource_id = str(booking.get("resource_id") or "")
    if resource_id and str(busy_row.get("resource_id") or "") != resource_id:
        return False
    try:
        occ_s = minutes_from_hhmm(occ_start)
        occ_e = minutes_from_hhmm(occ_end)
        b_s = minutes_from_hhmm(str(busy_row["start_time"]))
        b_e = minutes_from_hhmm(str(busy_row["end_time"]))
    except (KeyError, ValueError):
        return False
    return _intervals_overlap(occ_s, occ_e, b_s, b_e)


async def upsert_open_sync_conflict_review(
    db: Any,
    *,
    booking: Mapping[str, Any],
    blocking_interval: Mapping[str, Any],
) -> Optional[str]:
    """Idempotent open sync_conflict review when sync busy overlaps confirmed booking."""
    review_col = getattr(db, "review_queue", None)
    if review_col is None:
        return None

    booking_id = str(booking.get("booking_id") or "")
    if not booking_id:
        return None
    window = _booking_occupied_window(booking)
    if not window:
        return None
    date_str, occ_start, occ_end = window
    slot = booking.get("slot") or {}
    resource_id = str(
        booking.get("resource_id") or blocking_interval.get("resource_id") or ""
    )
    event_id = blocking_interval.get("event_id")
    block_start = blocking_interval.get("start_time")

    payload = {
        "slot": {
            "date": date_str,
            "start_time": slot.get("start_time") or occ_start,
            "end_time": slot.get("end_time") or occ_end,
        },
        "occupied": {
            "start_time": occ_start,
            "end_time": occ_end,
        },
        "blocking_interval": {
            "interval_id": blocking_interval.get("interval_id"),
            "source": blocking_interval.get("source"),
            "start_time": blocking_interval.get("start_time"),
            "end_time": blocking_interval.get("end_time"),
            "event_id": event_id,
            "connection_id": blocking_interval.get("connection_id"),
        },
    }

    query: dict[str, Any] = {
        "booking_id": booking_id,
        "type": ReviewQueueItemType.SYNC_CONFLICT.value,
        "status": ReviewQueueItemStatus.OPEN.value,
        "resource_id": resource_id or None,
        "payload.slot.date": date_str,
        "payload.blocking_interval.start_time": block_start,
    }
    if event_id:
        query["event_id"] = event_id

    try:
        existing = await review_col.find_one(query, {"_id": 0})
    except Exception:
        existing = None

    now = utc_now()
    now_iso = now.isoformat() if hasattr(now, "isoformat") else str(now)

    if existing and existing.get("review_id"):
        return str(existing["review_id"])

    review_id = generate_id()
    doc = {
        "review_id": review_id,
        "type": ReviewQueueItemType.SYNC_CONFLICT.value,
        "status": ReviewQueueItemStatus.OPEN.value,
        "resource_id": resource_id or None,
        "connection_id": blocking_interval.get("connection_id"),
        "event_id": event_id,
        "booking_id": booking_id,
        "message": SYNC_CONFLICT_MESSAGE,
        "payload": payload,
        "created_at": now_iso,
        "resolved_at": None,
    }
    try:
        await review_col.insert_one(doc)
    except Exception:
        logger.exception("Failed to insert sync_conflict review for %s", booking_id)
        return None
    return review_id


async def enqueue_sync_conflicts_for_busy_intervals(
    db: Any,
    *,
    busy_intervals: Sequence[Mapping[str, Any]],
) -> int:
    """
    After Outlook/manual busy is persisted, enqueue review for overlapping
    confirmed app bookings. Does not mutate bookings or payments.
    """
    authoritative = [
        dict(row)
        for row in busy_intervals
        if _is_outlook_or_manual_authoritative_busy(row)
    ]
    if not authoritative:
        return 0

    bookings_col = getattr(db, "bookings", None)
    if bookings_col is None:
        return 0

    by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in authoritative:
        rid = str(row.get("resource_id") or "")
        date_str = str(row.get("date") or "")
        if not rid or not date_str:
            continue
        by_key.setdefault((rid, date_str), []).append(row)

    enqueued = 0
    for (resource_id, date_str), intervals in by_key.items():
        try:
            bookings = await bookings_col.find(
                {
                    "status": "confirmed",
                    "resource_id": resource_id,
                    "slot.date": date_str,
                },
                {"_id": 0},
            ).to_list(length=500)
        except Exception:
            logger.exception(
                "Failed to load confirmed bookings for %s on %s",
                resource_id,
                date_str,
            )
            continue

        for booking in bookings:
            for interval in intervals:
                if not confirmed_booking_overlaps_busy_interval(booking, interval):
                    continue
                rid = await upsert_open_sync_conflict_review(
                    db,
                    booking=booking,
                    blocking_interval=interval,
                )
                if rid:
                    enqueued += 1

    return enqueued


async def upsert_open_manual_outlook_race_review(
    db: Any,
    *,
    booking_id: str,
    resource_id: str,
    date_str: str,
    customer_start: str,
    customer_end: str,
    action: str,
    blocking_interval: Mapping[str, Any],
) -> Optional[str]:
    """Idempotent open review item; returns review_id."""
    review_col = getattr(db, "review_queue", None)
    if review_col is None:
        return None

    payload = {
        "action": action,
        "slot": {
            "date": date_str,
            "start_time": customer_start,
            "end_time": customer_end,
        },
        "blocking_interval": {
            "interval_id": blocking_interval.get("interval_id"),
            "source": blocking_interval.get("source"),
            "start_time": blocking_interval.get("start_time"),
            "end_time": blocking_interval.get("end_time"),
            "event_id": blocking_interval.get("event_id"),
            "connection_id": blocking_interval.get("connection_id"),
        },
    }

    try:
        existing = await review_col.find_one(
            {
                "booking_id": booking_id,
                "type": ReviewQueueItemType.MANUAL_OUTLOOK_RACE.value,
                "status": ReviewQueueItemStatus.OPEN.value,
                "payload.action": action,
                "payload.slot.date": date_str,
                "payload.slot.start_time": customer_start,
            },
            {"_id": 0},
        )
    except Exception:
        existing = None

    now = utc_now()
    now_iso = now.isoformat() if hasattr(now, "isoformat") else str(now)

    if existing and existing.get("review_id"):
        return str(existing["review_id"])

    review_id = generate_id()
    doc = {
        "review_id": review_id,
        "type": ReviewQueueItemType.MANUAL_OUTLOOK_RACE.value,
        "status": ReviewQueueItemStatus.OPEN.value,
        "resource_id": resource_id,
        "connection_id": blocking_interval.get("connection_id"),
        "event_id": blocking_interval.get("event_id"),
        "booking_id": booking_id,
        "message": OFFICE_CONFLICT_MESSAGE,
        "payload": payload,
        "created_at": now_iso,
        "resolved_at": None,
    }
    try:
        await review_col.insert_one(doc)
    except Exception:
        logger.exception("Failed to insert manual_outlook_race review for %s", booking_id)
        return None
    return review_id


async def flag_office_conflict_if_blocked_by_outlook(
    db: Any,
    *,
    service: Mapping[str, Any],
    date_str: str,
    start_time: str,
    end_time: str,
    booking_id: Optional[str],
    action: str,
) -> Optional[str]:
    """
    When a slot recheck fails because office busy overlaps the session occupied
    window, enqueue review (if booking_id known). Does not mutate booking rows.
    """
    if not booking_id:
        return None
    resource_id = service.get("required_resource_id")
    if not resource_id:
        return None
    try:
        occupied = occupied_times_for_session(service, start_time)
    except ValueError:
        return None

    busy = await fetch_resource_busy(db, str(resource_id), date_str)
    blocker = find_office_busy_blocking_occupied(
        busy,
        occupied_start=occupied["start_time"],
        occupied_end=occupied["end_time"],
        exclude_booking_id=booking_id,
    )
    if not blocker:
        return None

    return await upsert_open_manual_outlook_race_review(
        db,
        booking_id=booking_id,
        resource_id=str(resource_id),
        date_str=date_str,
        customer_start=start_time,
        customer_end=end_time,
        action=action,
        blocking_interval=blocker,
    )
