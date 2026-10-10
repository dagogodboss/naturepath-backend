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
            if key
            not in {
                "aliases",
                "reviews",
                "assign_to_all_practitioners",
                "requires_discovery",
                "requires_prerequisite",
                "is_prerequisite",
            }
        }
        fields.update(
            {
                "is_discovery_entry": bool(entry.get("is_discovery_entry", False)),
                "display_order": int(entry.get("display_order", 90)),
                "updated_at": now,
            }
        )
        # Apply starting policy once. Later admin edits must survive the next boot.
        if not existing or "requires_prerequisite" not in existing:
            fields["requires_prerequisite"] = bool(entry.get("requires_prerequisite", True))
            fields["requires_discovery"] = bool(entry.get("requires_discovery", True))
            fields["is_prerequisite"] = bool(entry.get("is_prerequisite", False))

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

    discovery = await db.services.find_one(
        {"name": "Discovery Call"},
        {"_id": 0, "service_id": 1},
    )
    if discovery and discovery.get("service_id"):
        existing_policy = await db.site_settings.find_one({"key": "booking_policy"})
        if not existing_policy or not existing_policy.get("prerequisite_service_id"):
            await db.site_settings.update_one(
                {"key": "booking_policy"},
                {
                    "$set": {
                        "key": "booking_policy",
                        "prerequisite_service_id": discovery["service_id"],
                        "updated_at": now,
                    }
                },
                upsert=True,
            )
