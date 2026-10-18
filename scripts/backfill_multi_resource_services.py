#!/usr/bin/env python3
"""
Backfill services.required_resource_id + prep/recovery for multi-resource staging.

Uses locked name → resource rules from domain.multi_resource_service_attach.
Does NOT enable MULTI_RESOURCE_SCHEDULING. Default is dry-run; pass --apply to write.

Prerequisite: seed Nichole + Salt resources (seed_multi_resource_resources --apply).

Usage (from backend package root):
  PYTHONPATH=backend python -m scripts.backfill_multi_resource_services
  PYTHONPATH=backend python -m scripts.backfill_multi_resource_services --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from core.config import MULTI_RESOURCE_SCHEDULING, settings  # noqa: E402
from domain.multi_resource_service_attach import (  # noqa: E402
    build_service_scheduling_patch,
    patch_differs,
)
from domain.entities.models import ResourceType  # noqa: E402

NICHOLE_RESOURCE_NAME = "Dr. Nichole"
SALT_RESOURCE_NAME = "Salt room"


async def _resolve_resource_ids(db) -> tuple[Optional[str], Optional[str], list[str]]:
    notes: list[str] = []
    nichole = await db.resources.find_one(
        {
            "$or": [
                {"name": NICHOLE_RESOURCE_NAME, "type": ResourceType.PRACTITIONER.value},
                {"type": ResourceType.PRACTITIONER.value, "active": True},
            ]
        },
        {"_id": 0, "resource_id": 1, "name": 1},
        sort=[("updated_at", -1)],
    )
    salt = await db.resources.find_one(
        {
            "$or": [
                {"name": SALT_RESOURCE_NAME, "type": ResourceType.ROOM.value},
                {"type": ResourceType.ROOM.value, "name": {"$regex": "^Salt", "$options": "i"}},
            ]
        },
        {"_id": 0, "resource_id": 1, "name": 1},
        sort=[("updated_at", -1)],
    )
    n_id = nichole["resource_id"] if nichole else None
    s_id = salt["resource_id"] if salt else None
    if not n_id:
        notes.append("missing Nichole practitioner resource — run seed_multi_resource_resources --apply")
    if not s_id:
        notes.append("missing Salt room resource — run seed_multi_resource_resources --apply")
    return n_id, s_id, notes


async def backfill_services(db, *, dry_run: bool) -> dict[str, Any]:
    nichole_id, salt_id, notes = await _resolve_resource_ids(db)
    counts: dict[str, Any] = {
        "dry_run": dry_run,
        "flag_multi_resource_scheduling": MULTI_RESOURCE_SCHEDULING,
        "nichole_resource_id": nichole_id,
        "salt_resource_id": salt_id,
        "services_seen": 0,
        "would_update": 0,
        "updated": 0,
        "already_ok": 0,
        "unrecognized": 0,
        "skipped_no_resources": False,
        "planned": [],
        "notes": notes,
    }
    if not nichole_id or not salt_id:
        counts["skipped_no_resources"] = True
        return counts

    cursor = db.services.find(
        {"is_active": {"$ne": False}},
        {"_id": 0, "service_id": 1, "name": 1, "duration_minutes": 1,
         "required_resource_id": 1, "prep_minutes": 1, "recovery_minutes": 1,
         "customer_duration_minutes": 1, "flags": 1},
    )
    async for svc in cursor:
        counts["services_seen"] += 1
        patch = build_service_scheduling_patch(
            svc,
            nichole_resource_id=nichole_id,
            salt_resource_id=salt_id,
        )
        if patch is None:
            counts["unrecognized"] += 1
            continue
        if not patch_differs(svc, patch):
            counts["already_ok"] += 1
            continue
        entry = {
            "service_id": svc.get("service_id"),
            "name": svc.get("name"),
            "patch": patch,
        }
        counts["planned"].append(entry)
        counts["would_update"] += 1
        if not dry_run:
            await db.services.update_one(
                {"service_id": svc["service_id"]},
                {"$set": patch},
            )
            counts["updated"] += 1

    return counts


def _print_report(counts: dict[str, Any]) -> None:
    print("=== backfill_multi_resource_services ===")
    for key in (
        "dry_run",
        "flag_multi_resource_scheduling",
        "nichole_resource_id",
        "salt_resource_id",
        "services_seen",
        "would_update",
        "updated",
        "already_ok",
        "unrecognized",
        "skipped_no_resources",
    ):
        print(f"  {key}: {counts.get(key)}")
    for note in counts.get("notes") or []:
        print(f"  NOTE: {note}")
    for row in counts.get("planned") or []:
        print(f"  PLAN {row.get('name')!r} ({row.get('service_id')}): {row.get('patch')}")
    if counts.get("skipped_no_resources"):
        print("SKIPPED: resources not found — no service writes.")
    elif counts.get("dry_run"):
        print("MODE: dry-run (no writes). Re-run with --apply to persist.")
    else:
        print("MODE: apply (service patches written).")
    if not MULTI_RESOURCE_SCHEDULING:
        print(
            "NOTE: MULTI_RESOURCE_SCHEDULING is false — backfill is safe; "
            "booking still uses legacy path until staging flag is enabled."
        )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill service required_resource_id + prep/recovery (dry-run default)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan only (default when --apply omitted)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist service scheduling fields",
    )
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("use either --dry-run or --apply, not both")
    dry_run = not args.apply

    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        counts = await backfill_services(db, dry_run=dry_run)
        _print_report(counts)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
