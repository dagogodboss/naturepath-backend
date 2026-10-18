"""
Pure helpers for multi-resource occupied spans (Phase 1 scaffold).

Occupied length for app bookings:
    occupied = prep_minutes + customer_duration_minutes + recovery_minutes

Outlook-imported events use event start–end as full occupation (no buffers) —
that rule lives in Phase 2 sync, not here.
"""
from __future__ import annotations


def occupied_minutes(
    prep_minutes: int,
    customer_duration_minutes: int,
    recovery_minutes: int,
) -> int:
    """Return total occupied minutes for an app booking on a resource."""
    if prep_minutes < 0 or customer_duration_minutes < 0 or recovery_minutes < 0:
        raise ValueError("prep, customer, and recovery minutes must be non-negative")
    if customer_duration_minutes == 0:
        raise ValueError("customer_duration_minutes must be positive")
    return prep_minutes + customer_duration_minutes + recovery_minutes


def resolve_customer_duration_minutes(
    duration_minutes: int,
    customer_duration_minutes: int | None = None,
) -> int:
    """Prefer explicit customer_duration_minutes; fall back to legacy duration_minutes."""
    if customer_duration_minutes is not None:
        if customer_duration_minutes <= 0:
            raise ValueError("customer_duration_minutes must be positive")
        return customer_duration_minutes
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    return duration_minutes
