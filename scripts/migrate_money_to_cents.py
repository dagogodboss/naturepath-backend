"""
Money migration for store_orders / bookings.

Safe authoritative rollout:
- `*_cents` becomes source-of-truth.
- Legacy float fields are kept in sync from cents.
- Missing cents are backfilled from legacy float values.

Usage:
    python -m scripts.migrate_money_to_cents [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# Make `backend/` importable so `from core...` works in both test and prod.
_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from core.config import settings  # noqa: E402

_STORE_FIELDS = ("subtotal", "tax", "total", "refund_amount", "refund_amount_reserved")
_BOOKING_FIELDS = ("total_price", "payment_amount", "refund_amount")


def _to_cents(value) -> int | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def _migrate_collection(db, collection_name: str, fields: tuple[str, ...], dry_run: bool):
    projection = {"_id": 1, "currency": 1}
    for f in fields:
        projection[f] = 1
        projection[f"{f}_cents"] = 1
    cursor = db[collection_name].find({}, projection)
    n_seen = 0
    n_updated = 0
    n_backfilled_cents = 0
    n_synced_legacy = 0
    n_drift_rows = 0
    async for doc in cursor:
        n_seen += 1
        update_set: dict = {}
        for f in fields:
            cents_field = f"{f}_cents"
            cents_val = doc.get(cents_field)
            legacy_val = doc.get(f)
            if cents_val is None and legacy_val is not None:
                derived = _to_cents(legacy_val)
                if derived is not None:
                    update_set[cents_field] = derived
                    cents_val = derived
                    n_backfilled_cents += 1
            if cents_val is not None:
                legacy_synced = float((Decimal(int(cents_val)) / Decimal("100")).quantize(Decimal("0.01")))
                if legacy_val is None or abs(float(legacy_val) - legacy_synced) > 0.0001:
                    update_set[f] = legacy_synced
                    n_synced_legacy += 1
                    if legacy_val is not None:
                        n_drift_rows += 1
        if "currency" not in doc:
            update_set["currency"] = settings.default_currency if hasattr(settings, "default_currency") else "USD"
        if not update_set:
            continue
        update_set["money_migration_version"] = 2
        n_updated += 1
        if dry_run:
            continue
        await db[collection_name].update_one({"_id": doc["_id"]}, {"$set": update_set})
    return {
        "seen": n_seen,
        "updated": n_updated,
        "backfilled_cents": n_backfilled_cents,
        "synced_legacy": n_synced_legacy,
        "drift_rows": n_drift_rows,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        for coll, fields in [
            ("store_orders", _STORE_FIELDS),
            ("bookings", _BOOKING_FIELDS),
        ]:
            stats = await _migrate_collection(db, coll, fields, args.dry_run)
            suffix = " (DRY RUN)" if args.dry_run else ""
            print(
                f"{coll}: scanned={stats['seen']} updated={stats['updated']} "
                f"backfilled_cents={stats['backfilled_cents']} "
                f"synced_legacy={stats['synced_legacy']} drift_rows={stats['drift_rows']}{suffix}"
            )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
