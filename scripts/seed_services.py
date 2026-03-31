#!/usr/bin/env python3
"""
Seed or update services (benefits, ratings metadata) and service reviews in MongoDB.

Usage (from the `backend` directory that contains `seeds/` and `scripts/`):
  export MONGO_URL="mongodb+srv://USER:PASS@cluster/dbname?options"
  # or: export MONGODB_URL="..."
  PYTHONPATH=. python3 scripts/seed_services.py

Do not commit real credentials; set MONGO_URL or MONGODB_URL in your environment.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from seeds.service_catalog import SERVICE_CATALOG  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main() -> None:
    url = (os.environ.get("MONGO_URL") or os.environ.get("MONGODB_URL") or "").strip()
    if not url:
        print(
            "Set MONGO_URL or MONGODB_URL to your MongoDB connection string, then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = AsyncIOMotorClient(url)
    db = client.get_default_database()

    now = _utc_now_iso()

    for entry in SERVICE_CATALOG:
        name = entry["name"]
        reviews_in = entry.get("reviews") or []

        existing = await db.services.find_one({"name": name})
        service_id = existing["service_id"] if existing else str(uuid.uuid4())

        rating_average = 0.0
        rating_count = len(reviews_in)
        if reviews_in:
            rating_average = round(
                sum(r["rating"] for r in reviews_in) / rating_count,
                2,
            )

        set_doc = {
            "name": entry["name"],
            "description": entry["description"],
            "category": entry["category"],
            "duration_minutes": entry["duration_minutes"],
            "price": entry["price"],
            "discount_price": entry["discount_price"],
            "image_url": entry["image_url"],
            "is_featured": entry["is_featured"],
            "is_active": entry["is_active"],
            "max_capacity": entry["max_capacity"],
            "revel_product_id": entry["revel_product_id"],
            "benefits": entry.get("benefits") or [],
            "warning_copy": entry.get("warning_copy"),
            "is_discovery_entry": bool(entry.get("is_discovery_entry", False)),
            "rating_average": rating_average,
            "rating_count": rating_count,
            "updated_at": now,
        }

        await db.services.update_one(
            {"name": name},
            {
                "$set": set_doc,
                "$setOnInsert": {
                    "service_id": service_id,
                    "created_at": existing.get("created_at", now) if existing else now,
                },
            },
            upsert=True,
        )

        svc = await db.services.find_one({"name": name})
        if not svc:
            continue
        sid = svc["service_id"]

        await db.service_reviews.delete_many({"service_id": sid})

        review_docs = []
        for r in reviews_in:
            review_docs.append(
                {
                    "review_id": str(uuid.uuid4()),
                    "service_id": sid,
                    "author_name": r["author_name"],
                    "rating": int(r["rating"]),
                    "body": r["body"],
                    "created_at": now,
                }
            )
        if review_docs:
            await db.service_reviews.insert_many(review_docs)

        print(f"Upserted service + {len(review_docs)} reviews: {name} ({sid})")

    print("Done.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
