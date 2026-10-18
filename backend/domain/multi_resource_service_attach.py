"""
Locked service → resource scheduling targets for Phase 6 staging backfill.

Pure planning only — no Mongo writes. See docs/plans/phase-1-data-model.md §2.2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

ResourceRole = Literal["nichole", "salt"]

# Exact catalog names (plus known aliases) from service_catalog.py.
_NICHOLE_NAMES = frozenset(
    {
        "Discovery Call",
        "Natural Health Education Hour",
        "Wellness Consultation",
        "1-Hour Consultation",
        "2-Hours Extended Consultation",
        "Follow-up Consultation",
        "30-Minute Follow Up Consultation",
        "Direct-to-Consumer Lab Testing",
    }
)

_SALT_NAMES = frozenset({"Salt Session (Halotherapy)"})


@dataclass(frozen=True)
class ServiceSchedulingTarget:
    resource_role: ResourceRole
    prep_minutes: int
    recovery_minutes: int
    no_mondays: bool = False
    customer_duration_minutes: Optional[int] = None  # default: keep service.duration_minutes


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def classify_service_name(name: str) -> Optional[ResourceRole]:
    n = _normalize_name(name)
    if not n:
        return None
    if n in _SALT_NAMES or n.lower().startswith("salt session"):
        return "salt"
    if n in _NICHOLE_NAMES:
        return "nichole"
    # Nichole consults / education / labs by substring (staging safety net).
    lower = n.lower()
    if "consultation" in lower or "discovery" in lower:
        return "nichole"
    if "lab testing" in lower or "education hour" in lower:
        return "nichole"
    return None


def scheduling_target_for_name(name: str) -> Optional[ServiceSchedulingTarget]:
    """Return locked prep/recovery/resource role for a catalog service name."""
    n = _normalize_name(name)
    if not n:
        return None

    if n in _SALT_NAMES or n.lower().startswith("salt session"):
        return ServiceSchedulingTarget(
            resource_role="salt",
            prep_minutes=0,
            recovery_minutes=15,
        )

    if n == "Discovery Call" or "discovery" in n.lower():
        return ServiceSchedulingTarget(
            resource_role="nichole",
            prep_minutes=0,
            recovery_minutes=15,
            no_mondays=True,
        )

    if n in ("Wellness Consultation", "1-Hour Consultation"):
        return ServiceSchedulingTarget(
            resource_role="nichole",
            prep_minutes=15,
            recovery_minutes=15,
            no_mondays=True,
        )

    if n == "2-Hours Extended Consultation":
        return ServiceSchedulingTarget(
            resource_role="nichole",
            prep_minutes=10,
            recovery_minutes=15,
            no_mondays=True,
        )

    if n in ("Follow-up Consultation", "30-Minute Follow Up Consultation"):
        return ServiceSchedulingTarget(
            resource_role="nichole",
            prep_minutes=0,
            recovery_minutes=15,
            no_mondays=True,
        )

    if n == "Natural Health Education Hour" or "education hour" in n.lower():
        return ServiceSchedulingTarget(
            resource_role="nichole",
            prep_minutes=0,
            recovery_minutes=15,
            no_mondays=False,
        )

    if n == "Direct-to-Consumer Lab Testing" or "lab testing" in n.lower():
        return ServiceSchedulingTarget(
            resource_role="nichole",
            prep_minutes=0,
            recovery_minutes=0,
            no_mondays=False,
        )

    role = classify_service_name(n)
    if role == "nichole":
        return ServiceSchedulingTarget(
            resource_role="nichole",
            prep_minutes=0,
            recovery_minutes=15,
            no_mondays=True,
        )
    return None


def build_service_scheduling_patch(
    service: dict[str, Any],
    *,
    nichole_resource_id: str,
    salt_resource_id: str,
) -> Optional[dict[str, Any]]:
    """
    Compute $set fields for one service doc, or None if name is unrecognized.
    Idempotent: patch reflects target state from locked defaults.
    """
    target = scheduling_target_for_name(str(service.get("name") or ""))
    if target is None:
        return None

    rid = (
        nichole_resource_id
        if target.resource_role == "nichole"
        else salt_resource_id
    )
    duration = int(service.get("duration_minutes") or 0)
    customer = (
        target.customer_duration_minutes
        if target.customer_duration_minutes is not None
        else duration
    )

    flags = dict(service.get("flags") or {})
    if target.no_mondays:
        flags["no_mondays"] = True

    patch: dict[str, Any] = {
        "required_resource_id": rid,
        "prep_minutes": target.prep_minutes,
        "recovery_minutes": target.recovery_minutes,
        "customer_duration_minutes": customer,
        "flags": flags,
    }
    return patch


def patch_differs(service: dict[str, Any], patch: dict[str, Any]) -> bool:
    """True if service doc is not already at patch values."""
    for key, val in patch.items():
        current = service.get(key)
        if key == "flags":
            if dict(current or {}) != dict(val):
                return True
            continue
        if current != val:
            return True
    return False
