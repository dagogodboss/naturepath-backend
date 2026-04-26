"""
payment_events — append-only ledger of every payment state transition.

Callers should record an event for every state change (capture, refund, void,
hold_expired, manual_paid, failed). The collection is append-only — never
update an existing row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


async def record_payment_event(
    db,
    *,
    ref_type: str,
    ref_id: str,
    action: str,
    amount: Optional[float] = None,
    currency: str = "USD",
    source: str = "api",
    provider: str = "revel",
    external_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    event_id = str(uuid.uuid4())
    doc = {
        "event_id": event_id,
        "provider": provider,
        "source": source,
        "ref_type": ref_type,
        "ref_id": ref_id,
        "action": action,
        "amount": float(amount) if amount is not None else None,
        "amount_cents": (
            int(round(float(amount) * 100)) if amount is not None else None
        ),
        "currency": (currency or "USD").upper(),
        "external_id": external_id,
        "metadata": metadata or {},
        "at": datetime.now(timezone.utc),
    }
    await db.payment_events.insert_one(doc)
    return event_id
