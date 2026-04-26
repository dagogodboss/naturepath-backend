"""
Helpers for dual-write money migrations.

Policy:
- Read path is cents-first (authoritative).
- Legacy float fields are used only as fallback for pre-migration rows.
- Write path dual-writes cents + float so older readers keep working.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.money import Money


def read_cents_first(
    doc: Dict[str, Any],
    *,
    cents_field: str,
    legacy_field: str,
) -> Optional[int]:
    cents = doc.get(cents_field)
    if isinstance(cents, int):
        return cents
    legacy = doc.get(legacy_field)
    if legacy is None:
        return None
    try:
        return Money.from_float(legacy).to_cents()
    except Exception:
        return None


def read_amount_cents_first(
    doc: Dict[str, Any],
    *,
    cents_field: str,
    legacy_field: str,
    currency_field: str = "currency",
    default_currency: str = "USD",
) -> float:
    cents = read_cents_first(doc, cents_field=cents_field, legacy_field=legacy_field)
    currency = str(doc.get(currency_field) or default_currency)
    if cents is not None:
        return Money.from_cents(cents, currency).to_float()
    return 0.0


def dual_money_fields(
    *,
    amount: float,
    currency: str,
    legacy_field: str,
    cents_field: str,
) -> Dict[str, Any]:
    money = Money.from_float(amount, currency)
    return {
        legacy_field: money.to_float(),
        cents_field: money.to_cents(),
    }
