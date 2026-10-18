#!/usr/bin/env python3
"""
Ops CLI: Microsoft device-code OAuth for a specific outlook_calendar_connections row.

Usage (VPC VM with MONGO_URL / DB_NAME):
  OUTLOOK_DEVICE_CODE_OAUTH_ENABLED=1 python -m scripts.outlook_device_code_cli \\
    --connection-id 9fba4c5f-38e7-4a69-888c-3f84627ed3ea \\
    --poll-minutes 8 \\
    --report-json qa/reports/multi-resource-proof/outlook-device-code-staging-clients.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from application.outlook_device_oauth import (  # noqa: E402
    poll_device_code_for_connection,
    start_device_code_for_connection,
)
from application.outlook_sync import OutlookSyncError, sync_outlook_connection  # noqa: E402
from core.config import settings  # noqa: E402


async def _run(connection_id: str, poll_minutes: float, report_json: Path | None) -> dict:
    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.db_name]
    report: dict = {"connection_id": connection_id, "db_name": settings.db_name}
    try:
        conn = await db.outlook_calendar_connections.find_one(
            {"connection_id": connection_id}, {"_id": 0}
        )
        if not conn:
            raise SystemExit(f"Connection not found: {connection_id}")

        started = await start_device_code_for_connection(db, conn)
        report["start"] = started
        dc = started.get("device_code") or {}
        print("\n=== OUTLOOK DEVICE CODE — SIGN IN REQUIRED ===")
        print(f"Mailbox connection: {connection_id}")
        print(f"USER CODE: {dc.get('user_code')}")
        print(f"Open: {dc.get('verification_uri') or 'https://microsoft.com/devicelogin'}")
        if dc.get("verification_uri_complete"):
            print(f"Or: {dc['verification_uri_complete']}")
        print("==============================================\n")

        deadline = time.monotonic() + poll_minutes * 60
        conn = await db.outlook_calendar_connections.find_one(
            {"connection_id": connection_id}, {"_id": 0}
        )
        interval = float(
            (conn.get("oauth_device_code_session") or {}).get("interval_seconds") or 5
        )
        poll_log: list = []
        final = started
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            conn = await db.outlook_calendar_connections.find_one(
                {"connection_id": connection_id}, {"_id": 0}
            )
            final = await poll_device_code_for_connection(db, conn or {})
            poll_log.append({"status": final.get("status"), "error": final.get("error")})
            if final.get("status") == "connected":
                break
            if final.get("status") in {"expired"}:
                break
            interval = max(interval, float(
                (conn.get("oauth_device_code_session") or {}).get("interval_seconds") or 5
            ))

        report["poll"] = poll_log
        report["final"] = final

        if final.get("status") == "connected":
            conn = await db.outlook_calendar_connections.find_one(
                {"connection_id": connection_id}, {"_id": 0}
            )
            try:
                sync_result = await sync_outlook_connection(db, conn)
                report["sync"] = sync_result
            except OutlookSyncError as exc:
                report["sync_error"] = str(exc)
            busy = await db.resource_busy_intervals.count_documents(
                {"connection_id": connection_id}
            )
            report["resource_busy_intervals_for_connection"] = busy

        if report_json:
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, indent=2, default=str))
        return report
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Outlook device-code OAuth CLI")
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--poll-minutes", type=float, default=8.0)
    parser.add_argument("--report-json", type=Path, default=None)
    args = parser.parse_args()
    report = asyncio.run(_run(args.connection_id, args.poll_minutes, args.report_json))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
