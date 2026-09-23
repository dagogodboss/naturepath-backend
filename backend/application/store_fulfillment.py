"""Pickup vs ship totals. Tax stays on merchandise; shipping is separate."""

from __future__ import annotations

from typing import Any, Mapping


def normalize_fulfillment_method(value: str | None) -> str:
    method = (value or "pickup").strip().lower()
    if method not in {"pickup", "ship"}:
        raise ValueError("Fulfillment must be pickup or ship")
    return method


def shipping_amount(method: str, staff_amount: float | None = None) -> float:
    """Pickup shipping is always 0. Ship uses the staff-entered amount."""
    if normalize_fulfillment_method(method) == "pickup":
        return 0.0
    amount = float(staff_amount or 0)
    if amount < 0:
        raise ValueError("Shipping amount cannot be negative")
    return round(amount, 2)


def merchandise_totals(subtotal: float, tax_rate: float, shipping: float) -> dict[str, float]:
    """Tax is computed on the merchandise subtotal only."""
    goods = round(float(subtotal), 2)
    tax = round(goods * float(tax_rate), 2)
    ship = round(float(shipping), 2)
    return {
        "subtotal": goods,
        "tax": tax,
        "shipping": ship,
        "total": round(goods + tax + ship, 2),
    }


def ship_address_errors(address: Mapping[str, Any]) -> list[str]:
    required = {
        "line1": 3,
        "city": 2,
        "state": 2,
        "postal_code": 3,
    }
    missing = []
    for field, min_len in required.items():
        if len(str(address.get(field) or "").strip()) < min_len:
            missing.append(field)
    return missing
