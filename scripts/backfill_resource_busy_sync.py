#!/usr/bin/env python3
"""Sync resource_busy_intervals from confirmed/pending bookings (pymongo only, for VPC VM)."""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

import pymongo

STATUSES = frozenset({"pending", "confirmed", "in_progress"})


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def occupied_for_service(service: dict, start_time: str) -> tuple[str, str]:
    prep = int(service.get("prep_minutes") or 0)
    recovery = int(service.get("recovery_minutes") or 0)
    dur = service.get("customer_duration_minutes")
    session = int(dur if dur is not None else service.get("duration_minutes") or 0)
    if session <= 0:
        raise ValueError("invalid session minutes")
    start_m = _minutes(start_time)
    occ_start = start_m - prep
    occ_end = start_m + session + recovery
    if occ_start < 0:
        occ_start = 0
    return _hhmm(occ_start), _hhmm(occ_end)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--date", default=None, help="Only bookings on this YYYY-MM-DD")
    args = parser.parse_args()
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ.get("DB_NAME", "natural_path_staging")
    client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=15000)
    db = client[db_name]
    q: dict = {"status": {"$in": list(STATUSES)}}
    if args.date:
        q["slot.date"] = args.date
    written = would = skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    svc_cache: dict = {}
    for booking in db.bookings.find(q, {"_id": 0}):
        slot = booking.get("slot") or {}
        date_str = slot.get("date")
        if not date_str or not slot.get("start_time"):
            skipped += 1
            continue
        sid = booking.get("service_id")
        if not sid:
            skipped += 1
            continue
        if sid not in svc_cache:
            svc_cache[sid] = db.services.find_one({"service_id": sid}, {"_id": 0}) or {}
        service = svc_cache[sid]
        rid = booking.get("resource_id") or service.get("required_resource_id")
        if not rid or not service:
            skipped += 1
            continue
        try:
            occ_start, occ_end = occupied_for_service(service, slot["start_time"])
        except ValueError:
            skipped += 1
            continue
        bid = booking["booking_id"]
        filt = {
            "booking_id": bid,
            "resource_id": str(rid),
            "date": slot["date"],
            "source": "booking",
        }
        doc = {
            **filt,
            "interval_id": str(uuid.uuid4()),
            "start_time": occ_start,
            "end_time": occ_end,
            "authoritative": True,
            "show_as": "busy",
            "is_cancelled": False,
            "synced_at": now,
            "created_at": now,
        }
        if args.apply:
            db.resource_busy_intervals.update_one(filt, {"$set": doc}, upsert=True)
            written += 1
        else:
            would += 1
    print(
        {
            "dry_run": not args.apply,
            "date_filter": args.date,
            "written": written,
            "would_write": would,
            "skipped": skipped,
        }
    )
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
