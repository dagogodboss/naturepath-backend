#!/usr/bin/env python3
"""
Run in-process Outlook sync for one outlook_calendar_connections row.

Usage (from backend repo root):
  DB_NAME=natural_path_staging MULTI_RESOURCE_SCHEDULING=true \\
    PYTHONPATH=backend python -m scripts.sync_outlook_connection_cli \\
    --connection-id 0ae88711-4e79-42b4-831f-141705d6ca9c \\
    --report-json qa/reports/multi-resource-proof/outlook-sync-....json

Does not print tokens or secrets.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from application.outlook_sync import OutlookSyncError, sync_outlook_connection  # noqa: E402
from core.config import settings  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_sync(
    db: Any,
    connection_id: str,
) -> dict[str, Any]:
    connection = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection_id}
    )
    if not connection:
        return {
            "ok": False,
            "error": "connection_not_found",
            "connection_id": connection_id,
        }
    if not connection.get("refresh_token_encrypted"):
        return {
            "ok": False,
            "error": "missing_refresh_token",
            "connection_id": connection_id,
            "mailbox": connection.get("mailbox_email"),
        }

    report: dict[str, Any] = {
        "kind": "outlook_connection_sync",
        "generated_at": _utc_now_iso(),
        "connection_id": connection_id,
        "mailbox_email": connection.get("mailbox_email"),
        "practitioner_id": connection.get("practitioner_id"),
        "multi_resource_scheduling": bool(settings.multi_resource_scheduling),
        "db_name": settings.db_name,
        "before": {
            "last_sync_status": connection.get("last_sync_status"),
            "last_sync_error": connection.get("last_sync_error"),
            "last_synced_at": connection.get("last_synced_at"),
            "event_count": connection.get("event_count"),
        },
    }

    try:
        result = await sync_outlook_connection(db, connection)
        report["ok"] = True
        report["sync_result"] = result
    except OutlookSyncError as exc:
        report["ok"] = False
        report["error"] = "outlook_sync_error"
        report["message"] = str(exc)
        report["status_code"] = exc.status_code
    except Exception as exc:
        report["ok"] = False
        report["error"] = type(exc).__name__
        report["message"] = str(exc)[:500]

    after = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection_id},
        {
            "last_sync_status": 1,
            "last_sync_error": 1,
            "last_synced_at": 1,
            "event_count": 1,
        },
    )
    report["after"] = after or {}

    auth_ids = connection.get("authoritative_for_resource_ids") or []
    if auth_ids:
        busy_counts: dict[str, int] = {}
        for rid in auth_ids:
            busy_counts[str(rid)] = await db.resource_busy_intervals.count_documents(
                {"resource_id": str(rid)}
            )
        report["resource_busy_interval_counts"] = busy_counts
        report["resource_busy_interval_total"] = sum(busy_counts.values())

    legacy_count = await db.outlook_calendar_events.count_documents(
        {"connection_id": connection_id}
    )
    report["legacy_outlook_calendar_events_count"] = legacy_count

    return report


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sync one Outlook calendar connection.")
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--report-json", default=None)
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        report = await run_sync(db, args.connection_id)
        print(json.dumps({k: v for k, v in report.items() if k != "sync_result"}, indent=2))
        if report.get("sync_result"):
            print("sync_result:", json.dumps(report["sync_result"], indent=2))
        if args.report_json:
            out = Path(args.report_json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, default=str))
            print(f"Wrote report: {out}")
        if not report.get("ok"):
            sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
