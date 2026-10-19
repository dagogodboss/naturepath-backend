"""
Atomic per-resource occupancy reservations (issue #9 A2/A3).

Lock identity is (resource_id, date, occupied_start, occupied_end), not
practitioner/date/session-start. Pending holds expire with the slot lock TTL;
confirmed occupancy has no expiry.

Concurrency (Codex A2 follow-up):
- Optional per-(resource_id, date) lease serializes acquire when the locks
  collection is available.
- Durable fencing: an acknowledged or confirmed winner is never pruned by a
  delayed inserter, even if the delayed row has a smaller reservation_id.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

from application.multi_resource_slots import minutes_from_hhmm
from domain.entities.models import generate_id, utc_now

logger = logging.getLogger(__name__)

DEFAULT_HOLD_SECONDS = 300
RESERVATION_PENDING = "pending"
RESERVATION_CONFIRMED = "confirmed"
DAY_LOCK_TTL_SECONDS = 15

# Test seam: awaited after conflict precheck and before insert (Codex A2 window).
_pre_insert_hook: Optional[Callable[..., Awaitable[None]]] = None


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


def reservation_is_fenced(row: Mapping[str, Any]) -> bool:
    """Acknowledged or confirmed rows must not be revoked by a peer insert."""
    if str(row.get("status") or "").lower() == RESERVATION_CONFIRMED:
        return True
    return bool(row.get("acknowledged"))


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


async def _acquire_day_lock(
    db: Any,
    *,
    resource_id: str,
    date_str: str,
    holder: str,
    now: datetime,
) -> Optional[str]:
    """
    Exclusive lease on (resource_id, date). Returns holder token, or None when
    the locks collection is unavailable (unit-test fakes).
    """
    locks = getattr(db, "resource_reservation_locks", None)
    if locks is None or not hasattr(locks, "find_one_and_update"):
        return None

    lock_id = f"{resource_id}:{date_str}"
    expires = (_as_utc(now) + timedelta(seconds=DAY_LOCK_TTL_SECONDS)).isoformat()
    now_iso = _as_utc(now).isoformat()

    for _ in range(40):
        try:
            await locks.insert_one(
                {
                    "_id": lock_id,
                    "resource_id": resource_id,
                    "date": date_str,
                    "holder": holder,
                    "expires_at": expires,
                }
            )
            return holder
        except Exception:
            # Duplicate key or fake without duplicate errors — try steal/recheck.
            pass

        try:
            from pymongo import ReturnDocument

            stolen = await locks.find_one_and_update(
                {
                    "_id": lock_id,
                    "expires_at": {"$lt": now_iso},
                },
                {
                    "$set": {
                        "holder": holder,
                        "expires_at": expires,
                        "resource_id": resource_id,
                        "date": date_str,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            if stolen and str(stolen.get("holder") or "") == holder:
                return holder
        except Exception:
            logger.debug("resource day lock steal failed for %s", lock_id, exc_info=True)

        await asyncio.sleep(0.005)

    raise ValueError("Selected time is no longer available")


async def _release_day_lock(
    db: Any,
    *,
    resource_id: str,
    date_str: str,
    holder: str,
) -> None:
    locks = getattr(db, "resource_reservation_locks", None)
    if locks is None:
        return
    lock_id = f"{resource_id}:{date_str}"
    try:
        await locks.delete_one({"_id": lock_id, "holder": holder})
    except Exception:
        logger.debug("resource day lock release failed for %s", lock_id, exc_info=True)


async def _acknowledge_reservation(
    col: Any,
    *,
    reservation_id: str,
    clock_utc: datetime,
) -> Dict[str, Any]:
    """Durable fence: mark winner acknowledged before returning success."""
    await col.update_one(
        {"reservation_id": reservation_id},
        {
            "$set": {
                "acknowledged": True,
                "updated_at": clock_utc.isoformat(),
            }
        },
    )
    still = await col.find_one({"reservation_id": reservation_id}, {"_id": 0})
    if not still:
        raise ValueError("Selected time is no longer available")
    return still


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
    Bounded atomic reserve via day-lease (when available) + insert + fenced recheck.

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

    lock_holder = generate_id()
    held = await _acquire_day_lock(
        db,
        resource_id=resource_id,
        date_str=date_str,
        holder=lock_holder,
        now=clock_utc,
    )
    try:
        return await _acquire_resource_reservation_locked(
            db,
            col=col,
            resource_id=resource_id,
            date_str=date_str,
            occupied_start=occupied_start,
            occupied_end=occupied_end,
            booking_id=booking_id,
            owner_user_id=owner_user_id,
            hold_seconds=hold_seconds,
            status=status,
            clock_utc=clock_utc,
        )
    finally:
        if held:
            await _release_day_lock(
                db,
                resource_id=resource_id,
                date_str=date_str,
                holder=lock_holder,
            )


async def _acquire_resource_reservation_locked(
    db: Any,
    *,
    col: Any,
    resource_id: str,
    date_str: str,
    occupied_start: str,
    occupied_end: str,
    booking_id: str,
    owner_user_id: str,
    hold_seconds: int,
    status: str,
    clock_utc: datetime,
) -> Dict[str, Any]:
    # Move/refresh own row first (idempotent re-lock, confirm, or reschedule).
    existing_own = await col.find(
        {"booking_id": booking_id, "resource_id": resource_id},
        {"_id": 0},
    ).to_list(length=20)
    if existing_own:
        primary = existing_own[0]
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
        return await _acknowledge_reservation(
            col,
            reservation_id=str(primary["reservation_id"]),
            clock_utc=clock_utc,
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
        raise ValueError("Selected time is no longer available")

    # Codex A2 barrier window: after precheck, before insert.
    if _pre_insert_hook is not None:
        await _pre_insert_hook(
            booking_id=booking_id,
            resource_id=resource_id,
            date_str=date_str,
        )

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
        "acknowledged": False,
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
        logger.exception("resource reservation insert failed for %s", booking_id)
        raise ValueError("Selected time is no longer available") from None

    # Fenced conflict resolution (issue #9 A2). Confirmed/acknowledged peers
    # always win; delayed inserters must not revoke them. Among unfenced
    # pending peers, lexicographically smallest reservation_id wins.
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
            raise ValueError("Selected time is no longer available")

        fenced_others = [
            row
            for row in overlapping
            if str(row.get("reservation_id") or "") != my_key
            and reservation_is_fenced(row)
        ]
        if fenced_others:
            try:
                await col.delete_many({"reservation_id": reservation_id})
            except Exception:
                logger.exception(
                    "Failed to roll back reservation %s", reservation_id
                )
            raise ValueError("Selected time is no longer available")

        # Confirmed insert for this booking is itself a fence — treat as winner.
        if str(status).lower() == RESERVATION_CONFIRMED:
            for row in overlapping:
                other_id = str(row.get("reservation_id") or "")
                if (
                    other_id
                    and other_id != my_key
                    and not reservation_is_fenced(row)
                ):
                    try:
                        await col.delete_many({"reservation_id": other_id})
                    except Exception:
                        logger.exception(
                            "Failed to prune losing reservation %s", other_id
                        )
            return await _acknowledge_reservation(
                col, reservation_id=reservation_id, clock_utc=clock_utc
            )

        unfenced = [
            row
            for row in overlapping
            if not reservation_is_fenced(row)
            or str(row.get("reservation_id") or "") == my_key
        ]
        winner_id = min(str(r.get("reservation_id") or "") for r in unfenced)
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
            if not other_id or other_id == winner_id:
                continue
            if reservation_is_fenced(row):
                # Should be unreachable (fenced_others handled above).
                continue
            try:
                await col.delete_many({"reservation_id": other_id})
            except Exception:
                logger.exception(
                    "Failed to prune losing reservation %s", other_id
                )

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
            return await _acknowledge_reservation(
                col, reservation_id=reservation_id, clock_utc=clock_utc
            )
        # Peer appeared — if fenced, we lose on next loop; else continue.

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
                "acknowledged": True,
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
