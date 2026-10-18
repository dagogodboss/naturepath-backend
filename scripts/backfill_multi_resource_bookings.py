#!/usr/bin/env python3
"""
One-time backfill: bookings.resource_id + occupied_* from service scheduling fields.

Uses the same occupied span rules as confirm-time booking (occupied_times_for_session).
Does NOT enable MULTI_RESOURCE_SCHEDULING. Default dry-run; pass --apply to write.

Prerequisites:
  - seed_multi_resource_resources --apply
  - backfill_multi_resource_services --apply (or services already have required_resource_id)

Usage (from backend package root):
  PYTHONPATH=backend python -m scripts.backfill_multi_resource_bookings
  PYTHONPATH=backend python -m scripts.backfill_multi_resource_bookings --apply
  PYTHONPATH=backend python -m scripts.backfill_multi_resource_bookings --apply --status confirmed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from application.multi_resource_booking import (  # noqa: E402
    clear_booking_resource_busy,
    dual_write_booking_busy,
    occupied_times_for_session,
)
from core.config import MULTI_RESOURCE_SCHEDULING, settings  # noqa: E402
from domain.multi_resource_service_attach import (  # noqa: E402
    build_service_scheduling_patch,
)

# Terminal / abandoned drafts — skip unless --include-drafts.
_SKIP_STATUSES = frozenset({"cancelled", "canceled", "no_show"})
_BUSY_STATUSES = frozenset({"pending", "confirmed", "in_progress"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _booking_start_time(booking: dict[str, Any]) -> Optional[str]:
    slot = booking.get("slot") or {}
    return slot.get("start_time") or booking.get("start_time")


def _booking_end_time(booking: dict[str, Any]) -> Optional[str]:
    slot = booking.get("slot") or {}
    return slot.get("end_time") or booking.get("end_time")


def _needs_backfill(booking: dict[str, Any], patch: dict[str, Any]) -> bool:
    for key, value in patch.items():
        if booking.get(key) != value:
            return True
    return False


def _resolve_resource_id(
    booking: dict[str, Any],
    service: dict[str, Any],
    *,
    nichole_id: Optional[str],
    salt_id: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Return (resource_id, anomaly_note)."""
    rid = booking.get("resource_id") or service.get("required_resource_id")
    if rid:
        return str(rid), None
    if not nichole_id or not salt_id:
        return None, "resources not seeded"
    attach = build_service_scheduling_patch(
        service,
        nichole_resource_id=nichole_id,
        salt_resource_id=salt_id,
    )
    if not attach or not attach.get("required_resource_id"):
        return None, f"unrecognized service {service.get('name')!r}"
    return str(attach["required_resource_id"]), None


async def _sync_resource_busy_for_booking(
    db,
    *,
    booking: dict[str, Any],
    service: dict[str, Any],
    resource_id: str,
    occupied: dict[str, str],
    dry_run: bool,
) -> str:
    """Return action label: busy_written | busy_would_write | busy_skipped."""
    slot = booking.get("slot") or {}
    date_str = slot.get("date")
    if not date_str:
        return "busy_skipped"
    status = (booking.get("status") or "").lower()
    booking_id = str(booking.get("booking_id") or "")
    if status in _SKIP_STATUSES:
        if dry_run:
            return "busy_would_clear"
        await clear_booking_resource_busy(
            db=db,
            booking_id=booking_id,
            resource_id=resource_id,
            date_str=date_str,
        )
        return "busy_cleared"
    if status not in _BUSY_STATUSES:
        return "busy_skipped"
    if dry_run:
        return "busy_would_write"
    await dual_write_booking_busy(
        db=db,
        resource_id=resource_id,
        date_str=date_str,
        occupied_start=occupied["start_time"],
        occupied_end=occupied["end_time"],
        booking_id=booking_id,
    )
    return "busy_written"


async def backfill_bookings(
    db,
    *,
    dry_run: bool,
    status_filter: Optional[str],
    include_drafts: bool,
    limit: Optional[int],
    sync_resource_busy: bool,
) -> dict[str, Any]:
    nichole = await db.resources.find_one(
        {"type": "practitioner", "active": {"$ne": False}},
        {"_id": 0, "resource_id": 1},
        sort=[("updated_at", -1)],
    )
    salt = await db.resources.find_one(
        {"type": "room", "name": {"$regex": "^Salt", "$options": "i"}},
        {"_id": 0, "resource_id": 1},
    )
    nichole_id = nichole.get("resource_id") if nichole else None
    salt_id = salt.get("resource_id") if salt else None

    query: dict[str, Any] = {}
    if status_filter:
        query["status"] = status_filter
    elif not include_drafts:
        query["status"] = {"$nin": list(_SKIP_STATUSES | {"draft"})}

    counts: dict[str, Any] = {
        "dry_run": dry_run,
        "flag_multi_resource_scheduling": MULTI_RESOURCE_SCHEDULING,
        "status_filter": status_filter,
        "include_drafts": include_drafts,
        "bookings_seen": 0,
        "would_update": 0,
        "updated": 0,
        "already_ok": 0,
        "skipped_no_slot": 0,
        "anomalies": [],
        "planned": [],
        "sync_resource_busy": sync_resource_busy,
        "resource_busy_written": 0,
        "resource_busy_would_write": 0,
        "resource_busy_cleared": 0,
        "resource_busy_skipped": 0,
        "generated_at": _utc_now_iso(),
    }

    service_cache: dict[str, dict[str, Any]] = {}
    cursor = db.bookings.find(query, {"_id": 0}).sort("created_at", 1)
    if limit:
        cursor = cursor.limit(limit)

    async for booking in cursor:
        counts["bookings_seen"] += 1
        status = (booking.get("status") or "").lower()
        if status in _SKIP_STATUSES:
            continue
        if status == "draft" and not include_drafts:
            continue

        start_time = _booking_start_time(booking)
        if not start_time:
            counts["skipped_no_slot"] += 1
            counts["anomalies"].append(
                {
                    "booking_id": booking.get("booking_id"),
                    "reason": "missing slot start_time",
                }
            )
            continue

        sid = booking.get("service_id")
        if not sid:
            counts["anomalies"].append(
                {"booking_id": booking.get("booking_id"), "reason": "missing service_id"}
            )
            continue

        if sid not in service_cache:
            svc = await db.services.find_one({"service_id": sid}, {"_id": 0})
            service_cache[sid] = svc or {}
        service = service_cache[sid]
        if not service:
            counts["anomalies"].append(
                {
                    "booking_id": booking.get("booking_id"),
                    "reason": f"service not found {sid}",
                }
            )
            continue

        resource_id, anomaly = _resolve_resource_id(
            booking, service, nichole_id=nichole_id, salt_id=salt_id
        )
        if anomaly or not resource_id:
            counts["anomalies"].append(
                {
                    "booking_id": booking.get("booking_id"),
                    "service": service.get("name"),
                    "reason": anomaly or "no resource_id",
                }
            )
            continue

        end_time = _booking_end_time(booking)
        try:
            occupied = occupied_times_for_session(service, start_time)
        except ValueError as exc:
            counts["anomalies"].append(
                {
                    "booking_id": booking.get("booking_id"),
                    "service": service.get("name"),
                    "reason": str(exc),
                }
            )
            continue

        patch: dict[str, Any] = {
            "resource_id": resource_id,
            "customer_start_time": start_time,
            "customer_end_time": end_time or occupied.get("end_time"),
            "occupied_start_time": occupied["start_time"],
            "occupied_end_time": occupied["end_time"],
        }

        booking_for_busy = {**booking, **patch}

        if _needs_backfill(booking, patch):
            entry = {
                "booking_id": booking.get("booking_id"),
                "status": booking.get("status"),
                "service": service.get("name"),
                "date": (booking.get("slot") or {}).get("date"),
                "patch": patch,
            }
            counts["planned"].append(entry)
            counts["would_update"] += 1
            if not dry_run:
                await db.bookings.update_one(
                    {"booking_id": booking["booking_id"]},
                    {"$set": patch},
                )
                counts["updated"] += 1
        else:
            counts["already_ok"] += 1

        if sync_resource_busy:
            busy_action = await _sync_resource_busy_for_booking(
                db,
                booking=booking_for_busy,
                service=service,
                resource_id=resource_id,
                occupied=occupied,
                dry_run=dry_run,
            )
            if busy_action == "busy_written":
                counts["resource_busy_written"] += 1
            elif busy_action == "busy_would_write":
                counts["resource_busy_would_write"] += 1
            elif busy_action == "busy_cleared":
                counts["resource_busy_cleared"] += 1
            elif busy_action == "busy_would_clear":
                counts["resource_busy_cleared"] += 1
            else:
                counts["resource_busy_skipped"] += 1

    return counts


def _print_report(counts: dict[str, Any]) -> None:
    print("=== backfill_multi_resource_bookings ===")
    for key in (
        "dry_run",
        "flag_multi_resource_scheduling",
        "status_filter",
        "include_drafts",
        "bookings_seen",
        "would_update",
        "updated",
        "already_ok",
        "skipped_no_slot",
        "sync_resource_busy",
        "resource_busy_written",
        "resource_busy_would_write",
        "resource_busy_cleared",
        "resource_busy_skipped",
    ):
        print(f"  {key}: {counts.get(key)}")
    anomalies = counts.get("anomalies") or []
    print(f"  anomalies: {len(anomalies)}")
    for row in anomalies[:20]:
        print(f"    ANOMALY {row}")
    if len(anomalies) > 20:
        print(f"    ... and {len(anomalies) - 20} more")
    for row in counts.get("planned") or []:
        print(
            f"  PLAN {row.get('booking_id')} {row.get('service')!r} "
            f"date={row.get('date')} patch={row.get('patch')}"
        )
    if counts.get("dry_run"):
        print("MODE: dry-run (no writes). Re-run with --apply to persist.")
    else:
        print("MODE: apply (booking patches written).")
    if not MULTI_RESOURCE_SCHEDULING:
        print(
            "NOTE: MULTI_RESOURCE_SCHEDULING is false — backfill is safe; "
            "legacy booking path unchanged until staging flag is enabled."
        )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill booking resource_id + occupied times (dry-run default)."
    )
    parser.add_argument("--apply", action="store_true", help="Persist patches")
    parser.add_argument(
        "--status",
        default=None,
        help="Only bookings with this status (e.g. confirmed)",
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Include draft bookings (default skips draft)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max bookings to scan (debug)",
    )
    parser.add_argument(
        "--report-json",
        default=None,
        help="Write full plan + anomalies JSON to this path",
    )
    parser.add_argument(
        "--no-sync-resource-busy",
        action="store_true",
        help="Skip dual-write of resource_busy_intervals (booking fields only)",
    )
    args = parser.parse_args()
    dry_run = not args.apply
    sync_resource_busy = not args.no_sync_resource_busy

    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        counts = await backfill_bookings(
            db,
            dry_run=dry_run,
            status_filter=args.status,
            include_drafts=args.include_drafts,
            limit=args.limit,
            sync_resource_busy=sync_resource_busy,
        )
        _print_report(counts)
        if args.report_json:
            out = Path(args.report_json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(counts, indent=2, default=str))
            print(f"Wrote report: {out}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
