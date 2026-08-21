"""Idempotent production migration for the curated customer service catalog."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from application.service_catalog import SERVICE_CATALOG


async def ensure_service_catalog(db) -> None:
    """Upsert curated services without deleting operational or review data."""
    now = datetime.now(timezone.utc).isoformat()

    for entry in SERVICE_CATALOG:
        name = entry["name"]
        aliases = entry.get("aliases") or []
        existing = await db.services.find_one({"name": {"$in": [name, *aliases]}})
        # Deterministic IDs make concurrent Cloud Run cold starts converge on the
        # same unique service_id instead of inserting duplicate catalog rows.
        service_id = (
            existing.get("service_id")
            if existing
            else str(uuid.uuid5(uuid.NAMESPACE_URL, f"naturalpath:service:{name}"))
        )

        fields = {
            key: value
            for key, value in entry.items()
            if key not in {"aliases", "reviews", "assign_to_all_practitioners"}
        }
        fields.update(
            {
                "is_discovery_entry": bool(entry.get("is_discovery_entry", False)),
                "requires_discovery": bool(entry.get("requires_discovery", True)),
                "display_order": int(entry.get("display_order", 90)),
                "updated_at": now,
            }
        )

        await db.services.update_one(
            {"service_id": service_id},
            {
                "$set": fields,
                "$setOnInsert": {
                    "service_id": service_id,
                    "rating_average": 0.0,
                    "rating_count": 0,
                    "created_at": existing.get("created_at", now) if existing else now,
                },
            },
            upsert=True,
        )

        if entry.get("assign_to_all_practitioners"):
            await db.practitioners.update_many(
                {}, {"$addToSet": {"services": service_id}}
            )
