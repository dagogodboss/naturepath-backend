#!/usr/bin/env python3
"""
Phase 6 prove on staging Mongo: Nichole Discovery busy at 15:00 CT must not hide Salt 15:00.

Uses BookingUseCase.get_service_available_slots with MULTI_RESOURCE_SCHEDULING=true.
Optionally inserts a tagged synthetic busy on Nichole for a chosen Tuesday, then removes it.

Usage:
  DB_NAME=natural_path_staging MULTI_RESOURCE_SCHEDULING=true \\
    PYTHONPATH=backend python -m scripts.prove_discovery_neq_salt_staging \\
    --date 2026-10-21 --report-json ../qa/reports/multi-resource-proof/...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from application.multi_resource_booking import occupied_times_for_session  # noqa: E402
from application.use_cases.booking_use_case import BookingUseCase  # noqa: E402
from core.config import settings  # noqa: E402
from domain.entities.models import generate_id  # noqa: E402
from infrastructure.repositories.mongo_booking_repository import MongoBookingRepository  # noqa: E402
from infrastructure.repositories.mongo_event_repository import MongoEventRepository  # noqa: E402
from infrastructure.repositories.mongo_payment_repository import MongoPaymentRepository  # noqa: E402
from infrastructure.repositories.mongo_practitioner_repository import (  # noqa: E402
    MongoPractitionerRepository,
)
from infrastructure.repositories.mongo_service_repository import MongoServiceRepository  # noqa: E402
from infrastructure.repositories.mongo_user_repository import MongoUserRepository  # noqa: E402
from infrastructure.repositories.mongo_availability_slot_repository import (  # noqa: E402
    MongoAvailabilitySlotRepository,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _find_service_id(db: Any, *, discovery: bool) -> Optional[str]:
    if discovery:
        q = {
            "$or": [
                {"is_discovery_entry": True},
                {"name": {"$regex": "discovery", "$options": "i"}},
            ],
            "is_active": True,
        }
    else:
        q = {
            "name": {"$regex": "^salt", "$options": "i"},
            "is_active": True,
        }
    doc = await db.services.find_one(q, {"service_id": 1, "name": 1})
    return doc.get("service_id") if doc else None


async def _nichole_resource_id(db: Any) -> Optional[str]:
    doc = await db.resources.find_one(
        {"kind": "practitioner", "active": True},
        {"resource_id": 1, "name": 1},
    )
    return doc.get("resource_id") if doc else None


def _build_use_case(db: Any) -> BookingUseCase:
    return BookingUseCase(
        MongoBookingRepository(db),
        MongoAvailabilitySlotRepository(db),
        MongoServiceRepository(db),
        MongoPractitionerRepository(db),
        MongoUserRepository(db),
        MongoPaymentRepository(db),
        MongoEventRepository(db),
        cache=None,
    )


async def prove(
    db: Any,
    date_str: str,
    *,
    inject_synthetic: bool,
    use_real_busy_only: bool,
) -> dict[str, Any]:
    if not settings.multi_resource_scheduling:
        return {
            "ok": False,
            "error": "multi_resource_scheduling_false",
            "hint": "Set MULTI_RESOURCE_SCHEDULING=true",
        }

    nichole_rid = await _nichole_resource_id(db)
    discovery_id = await _find_service_id(db, discovery=True)
    salt_id = await _find_service_id(db, discovery=False)

    report: dict[str, Any] = {
        "kind": "discovery_neq_salt_staging_prove",
        "generated_at": _utc_now_iso(),
        "db_name": settings.db_name,
        "date": date_str,
        "nichole_resource_id": nichole_rid,
        "discovery_service_id": discovery_id,
        "salt_service_id": salt_id,
    }

    if not all([nichole_rid, discovery_id, salt_id]):
        report["ok"] = False
        report["error"] = "missing_seed_ids"
        return report

    synthetic_id: Optional[str] = None
    injected = False
    if inject_synthetic and not use_real_busy_only:
        discovery_svc = await db.services.find_one({"service_id": discovery_id})
        prep = int(discovery_svc.get("prep_minutes") or 0)
        session = int(
            discovery_svc.get("customer_duration_minutes")
            or discovery_svc.get("duration_minutes")
            or 30
        )
        recovery = int(discovery_svc.get("recovery_minutes") or 15)
        occupied = occupied_times_for_session(
            date_str=date_str,
            start_time="15:00",
            prep_minutes=prep,
            session_minutes=session,
            recovery_minutes=recovery,
        )
        synthetic_id = generate_id()
        doc = {
            "interval_id": synthetic_id,
            "resource_id": str(nichole_rid),
            "date": date_str,
            "start_time": occupied["start_time"],
            "end_time": occupied["end_time"],
            "show_as": "busy",
            "authoritative": True,
            "category_name": "Discovery",
            "source": "staging_prove_synthetic",
            "created_at": _utc_now_iso(),
        }
        await db.resource_busy_intervals.insert_one(doc)
        injected = True
        report["synthetic_busy"] = {
            "interval_id": synthetic_id,
            "occupied": occupied,
        }

    real_busy = await db.resource_busy_intervals.find(
        {
            "resource_id": str(nichole_rid),
            "date": date_str,
        }
    ).to_list(length=50)
    report["nichole_busy_on_date"] = [
        {
            "start_time": b.get("start_time"),
            "end_time": b.get("end_time"),
            "category_name": b.get("category_name"),
            "source": b.get("source"),
        }
        for b in real_busy
    ]

    use_case = _build_use_case(db)
    discovery_slots = await use_case.get_service_available_slots(discovery_id, date_str)
    salt_slots = await use_case.get_service_available_slots(salt_id, date_str)
    d_starts = [s["start_time"] for s in discovery_slots]
    s_starts = [s["start_time"] for s in salt_slots]

    report["discovery_slot_starts"] = d_starts
    report["salt_slot_starts"] = s_starts
    report["checks"] = {
        "discovery_15_00_blocked": "15:00" not in d_starts,
        "salt_15_00_offered": "15:00" in s_starts,
    }
    report["ok"] = (
        report["checks"]["discovery_15_00_blocked"]
        and report["checks"]["salt_15_00_offered"]
    )
    report["injected_synthetic"] = injected

    if synthetic_id:
        await db.resource_busy_intervals.delete_one({"interval_id": synthetic_id})
        report["synthetic_cleaned_up"] = True

    return report


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        default="2026-10-21",
        help="Clinic-local date (Tuesday recommended for Discovery no_mondays)",
    )
    parser.add_argument(
        "--real-busy-only",
        action="store_true",
        help="Skip synthetic insert; use only Outlook/sync busy intervals",
    )
    parser.add_argument("--report-json", required=True)
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        report = await prove(
            db,
            args.date,
            inject_synthetic=not args.real_busy_only,
            use_real_busy_only=args.real_busy_only,
        )
        out = Path(args.report_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps(report, indent=2))
        if not report.get("ok"):
            sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
