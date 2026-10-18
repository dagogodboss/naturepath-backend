#!/usr/bin/env python3
"""
Seed multi-resource scheduling resources (Phase 1 scaffold).

Creates (idempotent upsert by stable name / linked_practitioner_id):
  - Nichole practitioner resource from an existing practitioners row
  - Salt room resource with LOCKED Mon–Fri 10:30–18:00 hours, last start 17:00

Does NOT auto-run on server boot. Does NOT delete. Does NOT change booking
or Outlook sync behavior.

Modes (apply OFF by default):
  --dry-run   Default. Print counts only; no writes / no indexes.
  --apply     Persist Nichole + Salt resource upserts (and indexes if requested).

Usage (from the backend package root that contains scripts/ and backend/):
  PYTHONPATH=backend python -m scripts.seed_multi_resource_resources
  PYTHONPATH=backend python -m scripts.seed_multi_resource_resources --dry-run
  PYTHONPATH=backend python -m scripts.seed_multi_resource_resources --apply
  PYTHONPATH=backend python -m scripts.seed_multi_resource_resources --apply --create-indexes

Optional:
  --practitioner-id <id>   Prefer this practitioner when seeding Nichole
  --create-indexes         Create Phase 1 indexes (only with --apply; still no runtime wiring)
  --backfill-services      After resource upsert, run service attach backfill (requires --apply)

Service attach backfill alone:
  PYTHONPATH=backend python -m scripts.backfill_multi_resource_services [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from core.config import MULTI_RESOURCE_SCHEDULING, settings  # noqa: E402
from domain.entities.models import (  # noqa: E402
    PractitionerAvailability,
    Resource,
    ResourceSlotGrid,
    ResourceType,
)
from domain.multi_resource_defaults import (  # noqa: E402
    SALT_OUTLOOK_MAILBOX,
    build_locked_outlook_connection_templates,
)

# Stable names used for idempotent upserts (Phase 0 LOCKED Salt defaults).
NICHOLE_RESOURCE_NAME = "Dr. Nichole"
SALT_RESOURCE_NAME = "Salt room"

# Mon–Fri 10:30–18:00 (day_of_week 0=Monday … 4=Friday) — LOCKED Q6
# Starts from 10:30; last start 17:00; occupied may run to 18:00.
_SALT_WEEKLY_HOURS = [
    PractitionerAvailability(
        day_of_week=d, start_time="10:30", end_time="18:00", is_available=True
    )
    for d in range(5)
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_resource_id(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"naturalpath:resource:{key}"))


def _availability_to_dicts(rows: list) -> list[dict]:
    out = []
    for row in rows:
        if hasattr(row, "model_dump"):
            out.append(row.model_dump())
        elif isinstance(row, dict):
            out.append(
                {
                    "day_of_week": int(row.get("day_of_week", 0)),
                    "start_time": str(row.get("start_time", "09:00")),
                    "end_time": str(row.get("end_time", "17:00")),
                    "is_available": bool(row.get("is_available", True)),
                }
            )
    return out


async def _pick_practitioner(db, practitioner_id: Optional[str]) -> Optional[dict]:
    if practitioner_id:
        return await db.practitioners.find_one(
            {"practitioner_id": practitioner_id}, {"_id": 0}
        )
    # Prefer a featured / first practitioner with availability as Nichole seed.
    featured = await db.practitioners.find_one(
        {"is_featured": True}, {"_id": 0}, sort=[("created_at", 1)]
    )
    if featured:
        return featured
    return await db.practitioners.find_one({}, {"_id": 0}, sort=[("created_at", 1)])


def build_nichole_resource(practitioner: dict) -> Resource:
    hours = _availability_to_dicts(practitioner.get("availability") or [])
    return Resource(
        resource_id=_stable_resource_id(
            f"practitioner:{practitioner['practitioner_id']}"
        ),
        type=ResourceType.PRACTITIONER,
        name=NICHOLE_RESOURCE_NAME,
        timezone=settings.clinic_timezone,
        active=True,
        weekly_hours=[PractitionerAvailability(**h) for h in hours],
        linked_practitioner_id=practitioner["practitioner_id"],
        linked_practitioner_user_id=practitioner.get("user_id"),
        capacity=1,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )


def build_salt_resource() -> Resource:
    # LOCKED Q1/Q6: exclusive capacity 1; M–F 10:30–18:00; last start 17:00;
    # starts anytime (fine grid); occupied = 45 customer + 15 cleanup (seeded on service).
    return Resource(
        resource_id=_stable_resource_id("room:salt"),
        type=ResourceType.ROOM,
        name=SALT_RESOURCE_NAME,
        timezone=settings.clinic_timezone,
        active=True,
        weekly_hours=list(_SALT_WEEKLY_HOURS),
        slot_grid=ResourceSlotGrid(start_increment_minutes=15),
        last_start_time="17:00",
        capacity=1,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )


async def ensure_indexes(db) -> list[str]:
    """Create Phase 1 indexes. Idempotent. Not called unless --create-indexes."""
    created: list[str] = []
    await db.resources.create_index("resource_id", unique=True)
    created.append("resources.resource_id")
    await db.resources.create_index("type")
    created.append("resources.type")
    await db.resources.create_index("active")
    created.append("resources.active")
    await db.resource_busy_intervals.create_index(
        [("resource_id", 1), ("date", 1), ("start_time", 1)]
    )
    created.append("resource_busy_intervals.(resource_id,date,start_time)")
    await db.resource_busy_intervals.create_index(
        [("connection_id", 1), ("event_id", 1), ("date", 1), ("resource_id", 1)],
        unique=True,
        sparse=True,
    )
    created.append("resource_busy_intervals.outlook_sparse_unique")
    await db.review_queue.create_index([("status", 1), ("created_at", 1)])
    created.append("review_queue.(status,created_at)")
    await db.services.create_index("required_resource_id", sparse=True)
    created.append("services.required_resource_id")
    return created


async def seed_resources(
    db,
    *,
    dry_run: bool,
    practitioner_id: Optional[str] = None,
    create_indexes: bool = False,
) -> dict[str, Any]:
    """
    Upsert Nichole + Salt resources. Never deletes.
    Returns counts for printing.
    """
    counts: dict[str, Any] = {
        "flag_multi_resource_scheduling": MULTI_RESOURCE_SCHEDULING,
        "practitioners_seen": await db.practitioners.count_documents({}),
        "resources_before": await db.resources.count_documents({}),
        "nichole_would_create": 0,
        "nichole_would_update": 0,
        "salt_would_create": 0,
        "salt_would_update": 0,
        "nichole_written": 0,
        "salt_written": 0,
        "indexes_created": [],
        "dry_run": dry_run,
        "skipped_reason": None,
    }

    practitioner = await _pick_practitioner(db, practitioner_id)
    if not practitioner:
        counts["skipped_reason"] = "no practitioner found to seed Nichole resource"
        return counts

    nichole = build_nichole_resource(practitioner)
    salt = build_salt_resource()

    existing_nichole = await db.resources.find_one(
        {
            "$or": [
                {"resource_id": nichole.resource_id},
                {"linked_practitioner_id": nichole.linked_practitioner_id},
                {"name": NICHOLE_RESOURCE_NAME, "type": ResourceType.PRACTITIONER.value},
            ]
        },
        {"_id": 0, "resource_id": 1},
    )
    existing_salt = await db.resources.find_one(
        {
            "$or": [
                {"resource_id": salt.resource_id},
                {"name": SALT_RESOURCE_NAME, "type": ResourceType.ROOM.value},
            ]
        },
        {"_id": 0, "resource_id": 1},
    )

    if existing_nichole:
        counts["nichole_would_update"] = 1
        nichole_id = existing_nichole["resource_id"]
    else:
        counts["nichole_would_create"] = 1
        nichole_id = nichole.resource_id

    if existing_salt:
        counts["salt_would_update"] = 1
        salt_id = existing_salt["resource_id"]
    else:
        counts["salt_would_create"] = 1
        salt_id = salt.resource_id

    if create_indexes and not dry_run:
        counts["indexes_created"] = await ensure_indexes(db)
    elif create_indexes and dry_run:
        counts["indexes_created"] = ["(dry-run) would create Phase 1 indexes"]

    if dry_run:
        counts["resources_after"] = counts["resources_before"]
        counts["outlook_connection_templates"] = build_locked_outlook_connection_templates(
            nichole.resource_id,
            salt.resource_id,
        )
        counts["salt_outlook_mailbox_locked"] = SALT_OUTLOOK_MAILBOX
        return counts

    nichole_doc = nichole.model_dump(mode="json")
    nichole_doc["resource_id"] = nichole_id
    nichole_doc["type"] = ResourceType.PRACTITIONER.value
    nichole_doc["updated_at"] = _utc_now().isoformat()
    if existing_nichole:
        nichole_doc.pop("created_at", None)
        await db.resources.update_one(
            {"resource_id": nichole_id},
            {"$set": nichole_doc},
        )
    else:
        nichole_doc["created_at"] = _utc_now().isoformat()
        await db.resources.insert_one(nichole_doc)
    counts["nichole_written"] = 1

    salt_doc = salt.model_dump(mode="json")
    salt_doc["resource_id"] = salt_id
    salt_doc["type"] = ResourceType.ROOM.value
    salt_doc["updated_at"] = _utc_now().isoformat()
    if existing_salt:
        salt_doc.pop("created_at", None)
        await db.resources.update_one(
            {"resource_id": salt_id},
            {"$set": salt_doc},
        )
    else:
        salt_doc["created_at"] = _utc_now().isoformat()
        await db.resources.insert_one(salt_doc)
    counts["salt_written"] = 1

    counts["resources_after"] = await db.resources.count_documents({})
    counts["outlook_connection_templates"] = build_locked_outlook_connection_templates(
        nichole_id,
        salt_id,
    )
    counts["salt_outlook_mailbox_locked"] = SALT_OUTLOOK_MAILBOX
    return counts


def _print_counts(counts: dict[str, Any]) -> None:
    print("=== seed_multi_resource_resources ===")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    if counts.get("skipped_reason"):
        print(f"SKIPPED: {counts['skipped_reason']}")
    templates = counts.get("outlook_connection_templates")
    if templates:
        print("  outlook (ops — apply to outlook_calendar_connections after OAuth):")
        for key, tpl in templates.items():
            print(f"    [{key}] mailbox={tpl.get('mailbox_email')}")
            print(
                f"      authoritative_for_resource_ids={tpl.get('authoritative_for_resource_ids')}"
            )
            print(f"      category_map_names={[m.get('category_name') for m in tpl.get('category_maps', [])]}")
    if counts.get("salt_outlook_mailbox_locked"):
        print(f"  salt_outlook_authority: {counts['salt_outlook_mailbox_locked']}")
    if not MULTI_RESOURCE_SCHEDULING:
        print(
            "NOTE: MULTI_RESOURCE_SCHEDULING is false — "
            "seed is safe but runtime booking/Outlook paths ignore resources."
        )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Seed Nichole + Salt resources (Phase 1 scaffold; not auto-run). "
            "Default is --dry-run; pass --apply to write."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts only; do not write or create indexes (default when --apply omitted)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist resource upserts (and indexes if --create-indexes). Off by default.",
    )
    parser.add_argument(
        "--practitioner-id",
        default=None,
        help="Practitioner id to link as Nichole resource",
    )
    parser.add_argument(
        "--create-indexes",
        action="store_true",
        help="Also create Phase 1 Mongo indexes (requires --apply; ignored on dry-run)",
    )
    parser.add_argument(
        "--backfill-services",
        action="store_true",
        help="After --apply resource upsert, backfill services (requires --apply)",
    )
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("use either --dry-run or --apply, not both")
    if args.backfill_services and not args.apply:
        parser.error("--backfill-services requires --apply")
    # Apply off by default: dry-run unless --apply.
    dry_run = not args.apply

    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        counts = await seed_resources(
            db,
            dry_run=dry_run,
            practitioner_id=args.practitioner_id,
            create_indexes=args.create_indexes,
        )
        _print_counts(counts)
        if dry_run:
            print("MODE: dry-run (no writes). Re-run with --apply to persist.")
        else:
            print("MODE: apply (resources written).")
        if args.backfill_services and not dry_run and not counts.get("skipped_reason"):
            import importlib.util

            bf_path = _THIS_DIR / "backfill_multi_resource_services.py"
            spec = importlib.util.spec_from_file_location("_bf_mrs", bf_path)
            bf_mod = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(bf_mod)
            bf = await bf_mod.backfill_services(db, dry_run=False)
            print("=== backfill_multi_resource_services (via --backfill-services) ===")
            for key in (
                "would_update",
                "updated",
                "already_ok",
                "unrecognized",
                "skipped_no_resources",
            ):
                print(f"  {key}: {bf.get(key)}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
