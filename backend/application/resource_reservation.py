"""
Atomic per-resource occupancy reservations (issue #9 A2/A3).

Lock identity is (resource_id, date, occupied_start, occupied_end), not
practitioner/date/session-start. Pending holds expire with the slot lock TTL;
confirmed occupancy has no expiry.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from application.multi_resource_slots import minutes_from_hhmm
from domain.entities.models import generate_id, utc_now

logger = logging.getLogger(__name__)

DEFAULT_HOLD_SECONDS = 300
RESERVATION_PENDING = "pending"
RESERVATION_CONFIRMED = "confirmed"


def intervals_overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def _parse_iso(value: Any) -> Optional[datetime]:
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


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reservation_is_active(
    row: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
) -> bool:
    status = str(row.get("status") or "").lower()
    if status == RESERVATION_CONFIRMED:
        return True
    if status != RESERVATION_PENDING:
        return False
    expires = _parse_iso(row.get("expires_at"))
    if expires is None:
        return True
    clock = _as_utc(now or datetime.now(timezone.utc))
    return _as_utc(expires) > clock


def row_overlaps_occupied(
    row: Mapping[str, Any],
    occupied_start: str,
    occupied_end: str,
) -> bool:
    try:
        a0 = minutes_from_hhmm(str(row.get("occupied_start") or row.get("start_time")))
        a1 = minutes_from_hhmm(str(row.get("occupied_end") or row.get("end_time")))
        b0 = minutes_from_hhmm(occupied_start)
        b1 = minutes_from_hhmm(occupied_end)
    except ValueError:
        return False
    return intervals_overlap(a0, a1, b0, b1)


async def _load_resource_day_rows(
    col: Any,
    *,
    resource_id: str,
    date_str: str,
) -> List[Dict[str, Any]]:
    try:
        return await col.find(
            {"resource_id": resource_id, "date": date_str},
            {"_id": 0},
        ).to_list(length=500)
    except Exception:
        logger.exception(
            "Failed to load resource_reservations for %s on %s",
            resource_id,
            date_str,
        )
        raise


async def find_overlapping_reservations(
    db: Any,
    *,
    resource_id: str,
    date_str: str,
    occupied_start: str,
    occupied_end: str,
    exclude_booking_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    if db is None:
        return []
    col = getattr(db, "resource_reservations", None)
    if col is None:
        return []
    rows = await _load_resource_day_rows(
        col, resource_id=resource_id, date_str=date_str
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        if exclude_booking_id and str(row.get("booking_id") or "") == str(
            exclude_booking_id
        ):
            continue
        if not reservation_is_active(row, now=now):
            continue
        if row_overlaps_occupied(row, occupied_start, occupied_end):
            out.append(row)
    return out


async def acquire_resource_reservation(
    db: Any,
    *,
    resource_id: str,
    date_str: str,
    occupied_start: str,
    occupied_end: str,
    booking_id: str,
    owner_user_id: str,
    hold_seconds: int = DEFAULT_HOLD_SECONDS,
    status: str = RESERVATION_PENDING,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Bounded atomic-ish reserve via insert + conflict recheck.

    Returns the reservation doc. Raises ValueError on conflict or DB failure.
    Idempotent for the same booking_id overlapping the same window.
    """
    if db is None or not resource_id:
        raise ValueError("Selected time is no longer available")
    col = getattr(db, "resource_reservations", None)
    if col is None:
        raise ValueError("Selected time is no longer available")

    clock = now or utc_now()
    if isinstance(clock, datetime) and clock.tzinfo is None:
        clock_utc = clock.replace(tzinfo=timezone.utc)
    else:
        clock_utc = clock if isinstance(clock, datetime) else datetime.now(timezone.utc)

    # Move/refresh own row first (idempotent re-lock, confirm, or reschedule).
    existing_own = await col.find(
        {"booking_id": booking_id, "resource_id": resource_id},
        {"_id": 0},
    ).to_list(length=20)
    if existing_own:
        primary = existing_own[0]
        # Drop duplicate own rows if any (should not happen).
        for extra in existing_own[1:]:
            try:
                await col.delete_many({"reservation_id": extra.get("reservation_id")})
            except Exception:
                logger.exception(
                    "Failed to prune duplicate reservation for %s", booking_id
                )
        patch: Dict[str, Any] = {
            "occupied_start": occupied_start,
            "occupied_end": occupied_end,
            "date": date_str,
            "owner_user_id": owner_user_id,
            "status": status,
            "updated_at": clock_utc.isoformat(),
        }
        if status == RESERVATION_PENDING:
            patch["expires_at"] = (
                clock_utc + timedelta(seconds=int(hold_seconds))
            ).isoformat()
        else:
            patch["expires_at"] = None
        # Conflict-check before committing the move so a failed move keeps the
        # prior window when update is skipped — load prior, check, then set.
        prior = dict(primary)
        await col.update_one(
            {"reservation_id": primary["reservation_id"]},
            {"$set": patch},
        )
        conflicts = await find_overlapping_reservations(
            db,
            resource_id=resource_id,
            date_str=date_str,
            occupied_start=occupied_start,
            occupied_end=occupied_end,
            exclude_booking_id=booking_id,
            now=clock_utc,
        )
        if conflicts:
            # Restore prior reservation window (failed move retains old hold).
            restore = {
                "occupied_start": prior.get("occupied_start"),
                "occupied_end": prior.get("occupied_end"),
                "date": prior.get("date"),
                "status": prior.get("status"),
                "expires_at": prior.get("expires_at"),
                "updated_at": clock_utc.isoformat(),
            }
            await col.update_one(
                {"reservation_id": primary["reservation_id"]},
                {"$set": restore},
            )
            raise ValueError("Selected time is no longer available")
        refreshed = dict(primary)
        refreshed.update(patch)
        return refreshed

    conflicts = await find_overlapping_reservations(
        db,
        resource_id=resource_id,
        date_str=date_str,
        occupied_start=occupied_start,
        occupied_end=occupied_end,
        exclude_booking_id=booking_id,
        now=clock_utc,
    )
    if conflicts:
        raise ValueError("Selected time is no longer available")

    reservation_id = generate_id()
    doc: Dict[str, Any] = {
        "reservation_id": reservation_id,
        "resource_id": resource_id,
        "date": date_str,
        "occupied_start": occupied_start,
        "occupied_end": occupied_end,
        "booking_id": booking_id,
        "owner_user_id": owner_user_id,
        "status": status,
        "expires_at": (
            (clock_utc + timedelta(seconds=int(hold_seconds))).isoformat()
            if status == RESERVATION_PENDING
            else None
        ),
        "created_at": clock_utc.isoformat(),
        "updated_at": clock_utc.isoformat(),
    }
    try:
        await col.insert_one(dict(doc))
    except Exception:
        # Unique booking race or missing insert_one on fake — fall back to update.
        logger.exception("resource reservation insert failed for %s", booking_id)
        raise ValueError("Selected time is no longer available") from None

    # Double-check under concurrency (issue #9 A2 real-Mongo).
    # Lexicographically smallest reservation_id wins. A single yield+recheck is
    # not enough: each contender can briefly observe only its own insert and
    # both return success. Retry until the overlapping set is stable, prune
    # losers, and confirm our row still exists before returning.
    my_key = str(reservation_id)
    for attempt in range(8):
        await asyncio.sleep(0 if attempt == 0 else 0.002)
        day_rows = await _load_resource_day_rows(
            col, resource_id=resource_id, date_str=date_str
        )
        overlapping = [
            row
            for row in day_rows
            if reservation_is_active(row, now=clock_utc)
            and row_overlaps_occupied(row, occupied_start, occupied_end)
        ]
        if not any(str(r.get("reservation_id") or "") == my_key for r in overlapping):
            # Peer winner already pruned us.
            raise ValueError("Selected time is no longer available")

        winner_id = min(str(r.get("reservation_id") or "") for r in overlapping)
        if my_key != winner_id:
            try:
                await col.delete_many({"reservation_id": reservation_id})
            except Exception:
                logger.exception(
                    "Failed to roll back reservation %s", reservation_id
                )
            raise ValueError("Selected time is no longer available")

        for row in overlapping:
            other_id = str(row.get("reservation_id") or "")
            if other_id and other_id != winner_id:
                try:
                    await col.delete_many({"reservation_id": other_id})
                except Exception:
                    logger.exception(
                        "Failed to prune losing reservation %s", other_id
                    )

        # Re-read: done only when no overlapping peers remain.
        day_rows = await _load_resource_day_rows(
            col, resource_id=resource_id, date_str=date_str
        )
        peers = [
            row
            for row in day_rows
            if reservation_is_active(row, now=clock_utc)
            and row_overlaps_occupied(row, occupied_start, occupied_end)
            and str(row.get("reservation_id") or "") != my_key
        ]
        if not peers:
            still_mine = await col.find_one(
                {"reservation_id": reservation_id}, {"_id": 0}
            )
            if not still_mine:
                raise ValueError("Selected time is no longer available")
            return doc

    try:
        await col.delete_many({"reservation_id": reservation_id})
    except Exception:
        logger.exception("Failed to roll back reservation %s", reservation_id)
    raise ValueError("Selected time is no longer available")


async def promote_reservation_confirmed(
    db: Any,
    *,
    booking_id: str,
    resource_id: str,
) -> None:
    if db is None:
        return
    col = getattr(db, "resource_reservations", None)
    if col is None:
        return
    await col.update_many(
        {"booking_id": booking_id, "resource_id": resource_id},
        {
            "$set": {
                "status": RESERVATION_CONFIRMED,
                "expires_at": None,
                "updated_at": utc_now().isoformat(),
            }
        },
    )


async def release_resource_reservation(
    db: Any,
    *,
    booking_id: str,
    resource_id: Optional[str] = None,
) -> int:
    if db is None:
        return 0
    col = getattr(db, "resource_reservations", None)
    if col is None:
        return 0
    query: Dict[str, Any] = {"booking_id": booking_id}
    if resource_id:
        query["resource_id"] = resource_id
    result = await col.delete_many(query)
    return int(getattr(result, "deleted_count", 0) or 0)


async def expire_pending_reservations(
    db: Any,
    *,
    now: Optional[datetime] = None,
) -> int:
    """Delete expired pending reservations (idempotent)."""
    if db is None:
        return 0
    col = getattr(db, "resource_reservations", None)
    if col is None:
        return 0
    clock = now or datetime.now(timezone.utc)
    iso = _as_utc(clock).isoformat()
    result = await col.delete_many(
        {
            "status": RESERVATION_PENDING,
            "expires_at": {"$lt": iso},
        }
    )
    return int(getattr(result, "deleted_count", 0) or 0)


async def expire_pending_booking_busy(
    db: Any,
    *,
    now: Optional[datetime] = None,
) -> int:
    """
    Remove source=booking busy rows whose pending hold has expired.

    Confirmed occupancy (expires_at null/missing with booking confirmed) is kept:
    only rows with expires_at in the past are deleted.
    """
    if db is None:
        return 0
    col = getattr(db, "resource_busy_intervals", None)
    if col is None:
        return 0
    clock = now or datetime.now(timezone.utc)
    iso = _as_utc(clock).isoformat()
    result = await col.delete_many(
        {
            "source": "booking",
            "expires_at": {"$lt": iso},
        }
    )
    return int(getattr(result, "deleted_count", 0) or 0)


def active_reservation_busy_rows(
    reservations: Sequence[Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
    exclude_booking_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Project active reservations into busy-interval shape for the slot engine."""
    out: List[Dict[str, Any]] = []
    for row in reservations:
        if exclude_booking_id and str(row.get("booking_id") or "") == str(
            exclude_booking_id
        ):
            continue
        if not reservation_is_active(row, now=now):
            continue
        out.append(
            {
                "resource_id": row.get("resource_id"),
                "date": row.get("date"),
                "start_time": row.get("occupied_start"),
                "end_time": row.get("occupied_end"),
                "source": "booking",
                "authoritative": True,
                "booking_id": row.get("booking_id"),
                "show_as": "busy",
                "is_cancelled": False,
            }
        )
    return out
