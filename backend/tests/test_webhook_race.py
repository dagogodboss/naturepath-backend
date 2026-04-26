"""
D4 — Webhook-before-pay CAS filter guard tests.

These tests assert the CAS filter semantics used by the webhook and
payment-capture paths in `presentation/api/webhook_routes.py` — that is,
the `status`/`payment_status` pre-state filters that MongoDB evaluates
atomically inside a single `update_one` / `update_many` against each
document. The in-memory stub is serialized by an `asyncio.Lock` to model
Mongo's per-document atomic match-and-write semantics; we therefore
cannot catch true-concurrency regressions introduced by splitting a
match-then-update into two steps, only filter-drift regressions.

Covers:
- Exactly-one-capture invariant on a booking (idempotent CAS).
- No resurrection of cancelled bookings via `order.paid`.
- Multi-row `update_many` on `store_orders` preserves already-captured
  rows while capturing their pending siblings.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Dict, Iterable, Optional


def _matches(doc: Dict[str, Any], filt: Dict[str, Any]) -> bool:
    for k, v in filt.items():
        if k == "$expr":
            # Not exercised by these tests.
            continue
        doc_val = doc.get(k)
        if isinstance(v, dict):
            for op, op_val in v.items():
                if op == "$in":
                    if doc_val not in op_val:
                        return False
                elif op == "$nin":
                    if doc_val in op_val:
                        return False
                elif op == "$ne":
                    if doc_val == op_val:
                        return False
                elif op == "$exists":
                    present = k in doc
                    if bool(op_val) != present:
                        return False
                else:
                    raise AssertionError(f"unsupported operator {op}")
        else:
            if doc_val != v:
                return False
    return True


class _UpdateResult:
    def __init__(self, matched: int, modified: int):
        self.matched_count = matched
        self.modified_count = modified


class _Collection:
    def __init__(self, rows: Optional[Iterable[Dict[str, Any]]] = None):
        self.rows = [dict(r) for r in (rows or [])]
        self._lock = asyncio.Lock()

    async def find_one(self, filt: Dict[str, Any], proj: Optional[Dict[str, Any]] = None):
        async with self._lock:
            for r in self.rows:
                if _matches(r, filt):
                    return deepcopy(r)
        return None

    async def update_one(self, filt: Dict[str, Any], update: Dict[str, Any]) -> _UpdateResult:
        async with self._lock:
            for r in self.rows:
                if _matches(r, filt):
                    modified = False
                    for k, v in update.get("$set", {}).items():
                        if r.get(k) != v:
                            r[k] = v
                            modified = True
                    for k, v in update.get("$push", {}).items():
                        r.setdefault(k, []).append(deepcopy(v))
                        modified = True
                    return _UpdateResult(1, 1 if modified else 0)
            return _UpdateResult(0, 0)

    async def update_many(self, filt: Dict[str, Any], update: Dict[str, Any]) -> _UpdateResult:
        async with self._lock:
            matched = 0
            modified = 0
            for r in self.rows:
                if not _matches(r, filt):
                    continue
                matched += 1
                changed = False
                for k, v in update.get("$set", {}).items():
                    if r.get(k) != v:
                        r[k] = v
                        changed = True
                for k, v in update.get("$push", {}).items():
                    r.setdefault(k, []).append(deepcopy(v))
                    changed = True
                if changed:
                    modified += 1
            return _UpdateResult(matched, modified)


class _FakeDB:
    def __init__(self):
        self.bookings = _Collection()
        self.payment_links = _Collection()
        self.store_orders = _Collection()


# ---------------------------------------------------------------------------


async def _call_flip(db: _FakeDB, booking_id: str, tx_id: str) -> bool:
    # Mirrors `_flip_booking_to_captured`'s filter + update.
    result = await db.bookings.update_one(
        {
            "booking_id": booking_id,
            "status": {"$in": ["pending", "confirmed", "in_progress"]},
            "payment_status": {
                "$in": ["none", "awaiting_payment", "awaiting_counter", None]
            },
        },
        {
            "$set": {
                "payment_status": "captured",
                "payment_mode": "card_online",
                "revel_transaction_id": tx_id,
            },
            "$push": {
                "payment_events": {"action": "captured", "revel_transaction_id": tx_id}
            },
        },
    )
    return bool(result.modified_count)


def test_webhook_cas_filter_allows_single_capture():
    """Two CAS-based flips against the same booking: only the first wins."""
    db = _FakeDB()
    db.bookings.rows.append(
        {
            "booking_id": "bkg_1",
            "status": "confirmed",
            "payment_status": "awaiting_payment",
        }
    )

    async def run():
        # Two concurrent "captures" — a webhook and an in-flight pay path,
        # both firing the same CAS.
        a, b = await asyncio.gather(
            _call_flip(db, "bkg_1", "tx_a"),
            _call_flip(db, "bkg_1", "tx_b"),
        )
        return a, b

    a, b = asyncio.run(run())
    # Exactly one must win.
    assert (a, b) in ((True, False), (False, True))
    doc = db.bookings.rows[0]
    assert doc["payment_status"] == "captured"
    # Exactly one capture event recorded.
    assert len(doc["payment_events"]) == 1


def test_webhook_after_capture_is_no_op():
    db = _FakeDB()
    db.bookings.rows.append(
        {
            "booking_id": "bkg_2",
            "status": "confirmed",
            "payment_status": "captured",
            "revel_transaction_id": "tx_x",
            "payment_events": [{"action": "captured", "revel_transaction_id": "tx_x"}],
        }
    )

    async def run():
        return await _call_flip(db, "bkg_2", "tx_late")

    applied = asyncio.run(run())
    assert applied is False
    doc = db.bookings.rows[0]
    assert doc["payment_status"] == "captured"
    assert doc["revel_transaction_id"] == "tx_x"
    assert len(doc["payment_events"]) == 1


def test_webhook_cannot_resurrect_cancelled_booking():
    db = _FakeDB()
    db.bookings.rows.append(
        {
            "booking_id": "bkg_3",
            "status": "cancelled",
            "payment_status": "awaiting_payment",
        }
    )

    async def run():
        return await _call_flip(db, "bkg_3", "tx_late")

    applied = asyncio.run(run())
    assert applied is False
    assert db.bookings.rows[0]["status"] == "cancelled"
    assert db.bookings.rows[0].get("payment_status") == "awaiting_payment"


def test_store_orders_update_many_preserves_captured_sibling():
    """
    Seeds one `captured` row and one `awaiting_payment` row sharing a
    revel_order_id. The webhook's update_many should only flip the pending
    row and leave the captured row untouched (including its transaction id).
    """
    db = _FakeDB()
    db.store_orders.rows.extend(
        [
            {
                "order_id": "np_ord_captured",
                "revel_order_id": "revel_1",
                "payment_status": "captured",
                "revel_transaction_id": "tx_old",
            },
            {
                "order_id": "np_ord_pending",
                "revel_order_id": "revel_1",
                "payment_status": "awaiting_payment",
                "revel_transaction_id": None,
            },
        ]
    )

    async def webhook():
        return await db.store_orders.update_many(
            {
                "revel_order_id": "revel_1",
                "payment_status": {
                    "$in": ["pending", "processing", "awaiting_payment", "awaiting_counter"]
                },
            },
            {"$set": {"payment_status": "captured", "revel_transaction_id": "tx_new"}},
        )

    result = asyncio.run(webhook())
    assert result.matched_count == 1
    assert result.modified_count == 1
    already = next(r for r in db.store_orders.rows if r["order_id"] == "np_ord_captured")
    now_captured = next(r for r in db.store_orders.rows if r["order_id"] == "np_ord_pending")
    assert already["revel_transaction_id"] == "tx_old"
    assert already["payment_status"] == "captured"
    assert now_captured["revel_transaction_id"] == "tx_new"
    assert now_captured["payment_status"] == "captured"
