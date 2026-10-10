"""Business-wide prerequisite service setting.

Stored in ``site_settings`` under key ``booking_policy`` so an admin can change
it without a code deploy. The chosen service is forced off the
``requires_prerequisite`` switch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


POLICY_KEY = "booking_policy"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def read_prerequisite_service_id(db) -> Optional[str]:
    """Return the stored prerequisite service id, or None when unset."""
    if db is None:
        return None
    try:
        collection = db.site_settings
    except Exception:
        return None
    find_one = getattr(collection, "find_one", None)
    if find_one is None:
        return None
    try:
        doc = await find_one({"key": POLICY_KEY}, {"_id": 0})
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    service_id = doc.get("prerequisite_service_id")
    if not service_id or not isinstance(service_id, str):
        return None
    return service_id


def default_prerequisite_service_id(services: List[Dict[str, Any]]) -> Optional[str]:
    """Discovery Call is the default prerequisite when no setting is stored."""
    for service in services:
        if service.get("is_prerequisite") is True and service.get("service_id"):
            return service["service_id"]
    for service in services:
        name = str(service.get("name") or "").strip().lower()
        if service.get("is_discovery_entry") is True or "discovery call" in name:
            if service.get("service_id"):
                return service["service_id"]
    return None


async def resolve_prerequisite_service_id(db, services: List[Dict[str, Any]]) -> Optional[str]:
    stored = await read_prerequisite_service_id(db)
    known = {service.get("service_id") for service in services}
    if stored and stored in known:
        return stored
    fallback = default_prerequisite_service_id(services)
    return fallback or stored


def coerce_service_policy_updates(
    updates: Dict[str, Any],
    service_id: str,
    prerequisite_service_id: Optional[str],
) -> Dict[str, Any]:
    """Keep the prerequisite service from requiring itself, and sync the legacy flag."""
    if "requires_prerequisite" not in updates and "requires_discovery" in updates:
        updates["requires_prerequisite"] = updates["requires_discovery"]
    if "requires_prerequisite" in updates:
        if prerequisite_service_id and service_id == prerequisite_service_id:
            updates["requires_prerequisite"] = False
        updates["requires_discovery"] = bool(updates["requires_prerequisite"])
    updates.pop("is_prerequisite", None)
    updates.pop("prerequisite_service_id", None)
    return updates


async def set_prerequisite_service(db, service_id: str, *, service_use_case=None) -> Dict[str, Any]:
    """Save the business-wide prerequisite and force that service's switch off."""
    if service_use_case is not None:
        repo = getattr(service_use_case, "service_repo", None)
        if repo is not None and hasattr(repo, "list_all"):
            services = await repo.list_all(limit=500)
        else:
            services = await service_use_case.get_all_services(active_only=False)
    else:
        cursor = db.services.find({}, {"_id": 0})
        services = await cursor.to_list(length=None)
    if not any(service.get("service_id") == service_id for service in services):
        raise ValueError("Service not found")

    now = _utcnow()
    await db.site_settings.update_one(
        {"key": POLICY_KEY},
        {
            "$set": {
                "key": POLICY_KEY,
                "prerequisite_service_id": service_id,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    for service in services:
        sid = service.get("service_id")
        if not sid:
            continue
        updates: Dict[str, Any] = {"is_prerequisite": sid == service_id}
        if sid == service_id:
            updates["requires_prerequisite"] = False
            updates["requires_discovery"] = False
        if service_use_case is not None:
            await service_use_case.update_service(sid, **updates)
        else:
            await db.services.update_one({"service_id": sid}, {"$set": updates})
    return {"prerequisite_service_id": service_id}
