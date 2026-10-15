"""
Clinic booking model: one practitioner weekly schedule covers every active service.

Historically only catalog rows with assign_to_all_practitioners (Education Hour)
were $addToSet onto practitioners.services. Slot lookup filters by that array, so
Discovery/Salt/etc. looked empty even when hours existed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence


def practitioner_has_weekly_schedule(practitioner: Dict[str, Any]) -> bool:
    """True when the practitioner publishes at least one weekly availability window."""
    availability = practitioner.get("availability") or []
    if not isinstance(availability, list):
        return False
    for row in availability:
        if not isinstance(row, dict):
            continue
        if row.get("is_available", True) is False:
            continue
        if row.get("start_time") and row.get("end_time"):
            return True
    return False


def merge_service_ids(existing: Sequence[str] | None, service_ids: Sequence[str]) -> List[str]:
    """Stable union of service ids (existing order preserved, then new ids)."""
    merged: List[str] = []
    seen = set()
    for sid in list(existing or []) + list(service_ids or []):
        if not sid or sid in seen:
            continue
        seen.add(sid)
        merged.append(sid)
    return merged


async def sync_active_services_onto_scheduled_practitioners(db) -> Dict[str, Any]:
    """
    Ensure every active bookable service is linked to practitioners who publish
    weekly hours. Idempotent; safe on every API boot.
    """
    service_ids = [
        doc["service_id"]
        async for doc in db.services.find(
            {"is_active": True, "service_id": {"$exists": True, "$ne": ""}},
            {"_id": 0, "service_id": 1},
        )
        if doc.get("service_id")
    ]
    if not service_ids:
        return {"service_count": 0, "practitioners_updated": 0}

    practitioners = [
        doc
        async for doc in db.practitioners.find(
            {},
            {"_id": 0, "practitioner_id": 1, "services": 1, "availability": 1},
        )
    ]
    updated = 0
    for practitioner in practitioners:
        if not practitioner_has_weekly_schedule(practitioner):
            continue
        pid = practitioner.get("practitioner_id")
        if not pid:
            continue
        next_services = merge_service_ids(practitioner.get("services"), service_ids)
        if next_services == list(practitioner.get("services") or []):
            continue
        await db.practitioners.update_one(
            {"practitioner_id": pid},
            {"$set": {"services": next_services}},
        )
        updated += 1
    return {"service_count": len(service_ids), "practitioners_updated": updated}
