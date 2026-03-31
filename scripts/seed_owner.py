#!/usr/bin/env python3
"""
One-time owner bootstrap script.

Creates or updates the primary owner account:
  - Full name: Nichole Moore
  - Email: admin@thenaturalpath.com
  - Role: practitioner (inherits admin permissions via Casbin policy)

Usage:
  export MONGO_URL="mongodb+srv://..."
  export OWNER_PASSWORD="strong-password"
  PYTHONPATH=. python3 scripts/seed_owner.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main() -> None:
    mongo_url = (os.environ.get("MONGO_URL") or os.environ.get("MONGODB_URL") or "").strip()
    owner_password = (os.environ.get("OWNER_PASSWORD") or "").strip()
    if not mongo_url:
        print("Set MONGO_URL or MONGODB_URL before running this script.", file=sys.stderr)
        sys.exit(1)
    if not owner_password:
        print("Set OWNER_PASSWORD before running this script.", file=sys.stderr)
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db = client.get_default_database()
    now = _utc_now_iso()

    owner_email = "Nmoore@thenaturalpathla.com"
    first_name = "Nichole"
    last_name = "Moore"

    existing_user = await db.users.find_one({"email": owner_email})
    user_id = existing_user["user_id"] if existing_user else str(uuid.uuid4())
    user_doc = {
        "user_id": user_id,
        "email": owner_email,
        "password_hash": pwd_context.hash(owner_password),
        "first_name": first_name,
        "last_name": last_name,
        "role": "practitioner",
        "is_active": True,
        "is_verified": True,
        "updated_at": now,
    }
    await db.users.update_one(
        {"email": owner_email},
        {"$set": user_doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    existing_practitioner = await db.practitioners.find_one({"user_id": user_id})
    practitioner_id = (
        existing_practitioner["practitioner_id"] if existing_practitioner else str(uuid.uuid4())
    )
    practitioner_doc = {
        "practitioner_id": practitioner_id,
        "user_id": user_id,
        "bio": existing_practitioner.get("bio", "Owner practitioner profile")
        if existing_practitioner
        else "Owner practitioner profile",
        "philosophy": existing_practitioner.get("philosophy") if existing_practitioner else None,
        "specialties": existing_practitioner.get("specialties", []) if existing_practitioner else [],
        "certifications": existing_practitioner.get("certifications", []) if existing_practitioner else [],
        "services": existing_practitioner.get("services", []) if existing_practitioner else [],
        "availability": existing_practitioner.get("availability", []) if existing_practitioner else [],
        "hourly_rate": existing_practitioner.get("hourly_rate", 0.0) if existing_practitioner else 0.0,
        "is_featured": existing_practitioner.get("is_featured", True) if existing_practitioner else True,
        "rating": existing_practitioner.get("rating", 5.0) if existing_practitioner else 5.0,
        "total_reviews": existing_practitioner.get("total_reviews", 0) if existing_practitioner else 0,
        "updated_at": now,
    }
    await db.practitioners.update_one(
        {"user_id": user_id},
        {"$set": practitioner_doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    print(
        "Seeded owner account and practitioner profile:"
        f" {first_name} {last_name} <{owner_email}> role=practitioner(admin-equivalent)"
    )
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
