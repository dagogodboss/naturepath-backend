"""Authorization-aware client directory scope."""

from __future__ import annotations

from typing import Any, Dict


CLINIC_WIDE_ROLES = {"owner", "admin", "manager"}


def client_booking_filter(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Owners/admins see clinic-wide bookings; practitioners see only their own."""
    role = str((ctx.get("user") or {}).get("role") or "").lower()
    query: Dict[str, Any] = {"customer_id": {"$ne": None}}
    if role in CLINIC_WIDE_ROLES:
        return query
    practitioner = ctx.get("practitioner")
    if not practitioner:
        raise ValueError("Practitioner profile required")
    query["practitioner_id"] = practitioner["practitioner_id"]
    return query

