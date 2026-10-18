#!/usr/bin/env python3
"""Probe Entra application calendar access (no refresh token / device code)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from application.outlook_sync import OutlookSyncError, graph_client, sync_outlook_connection  # noqa: E402
from core.config import settings  # noqa: E402


async def _probe_mailbox(upn: str) -> dict:
    client = graph_client()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=1)
    end = now + timedelta(days=7)
    token = await client.client_credentials_token()
    access = token.get("access_token")
    report: dict = {"mailbox": upn, "token_acquired": bool(access)}
    if not access:
        return report
    try:
        events = await client.list_user_calendar_view(access, upn, start=start, end=end)
        report["status"] = "ok"
        report["event_count"] = len(events)
    except Exception as exc:
        report["status"] = "error"
        report["error"] = str(exc)[:500]
    return report


async def _sync_connection(db, connection_id: str) -> dict:
    conn = await db.outlook_calendar_connections.find_one({"connection_id": connection_id})
    if not conn:
        return {"connection_id": connection_id, "status": "not_found"}
    try:
        result = await sync_outlook_connection(db, conn)
        busy = await db.resource_busy_intervals.count_documents(
            {"connection_id": connection_id}
        )
        return {
            "connection_id": connection_id,
            "mailbox_email": conn.get("mailbox_email"),
            "auth_mode": conn.get("auth_mode"),
            "sync": result,
            "resource_busy_intervals": busy,
        }
    except OutlookSyncError as exc:
        return {
            "connection_id": connection_id,
            "status": "sync_error",
            "detail": str(exc),
            "status_code": exc.status_code,
        }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Outlook app-only Graph access")
    parser.add_argument("--mailbox", action="append", default=[])
    parser.add_argument("--connection-id", default="")
    parser.add_argument("--report-json", default="")
    args = parser.parse_args()

    mailboxes = args.mailbox or [
        "Clients@thenaturalpathla.com",
        "nmoore@thenaturalpathla.com",
    ]
    report = {
        "kind": "outlook_app_only_probe",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "client_id_prefix": (graph_client().client_id or "")[:8],
        "mailboxes": [],
    }
    for upn in mailboxes:
        report["mailboxes"].append(await _probe_mailbox(upn))
    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.db_name]
    try:
        if args.connection_id:
            report["connection_sync"] = await _sync_connection(db, args.connection_id)
    finally:
        client.close()

    text = json.dumps(report, indent=2)
    print(text)
    if args.report_json:
        Path(args.report_json).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
