#!/usr/bin/env python3
"""
Staging ops: merge locked multi-resource fields onto outlook_calendar_connections.

Does not perform OAuth or touch refresh tokens. Safe to run when flag is on in staging.
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

from core.config import settings  # noqa: E402
from domain.entities.models import generate_id  # noqa: E402
from domain.multi_resource_defaults import (  # noqa: E402
    SALT_OUTLOOK_MAILBOX,
    build_locked_outlook_connection_templates,
)


def _public_conn(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "connection_id": doc.get("connection_id"),
        "microsoft_email": doc.get("microsoft_email"),
        "mailbox_email": doc.get("mailbox_email"),
        "practitioner_id": doc.get("practitioner_id"),
        "is_active": doc.get("is_active"),
        "oauth_pending": doc.get("oauth_pending"),
        "authoritative_for_resource_ids": doc.get("authoritative_for_resource_ids") or [],
        "category_map_count": len(doc.get("category_maps") or []),
        "category_names": [
            m.get("category_name") for m in (doc.get("category_maps") or [])
        ],
    }


async def apply_templates(*, report_json: Path | None) -> dict[str, Any]:
    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.db_name]
    try:
        nichole = await db.resources.find_one(
            {"type": "practitioner", "active": {"$ne": False}},
            {"_id": 0},
        )
        salt = await db.resources.find_one(
            {"type": "room", "name": {"$regex": "^Salt", "$options": "i"}},
            {"_id": 0},
        )
        if not nichole or not salt:
            raise RuntimeError("Nichole and/or Salt resource missing — run seed first")
        n_id = nichole["resource_id"]
        s_id = salt["resource_id"]
        templates = build_locked_outlook_connection_templates(n_id, s_id)
        tpl_n = templates["nichole_authoritative"]
        tpl_c = templates["clients_salt_authoritative"]

        conns = await db.outlook_calendar_connections.find(
            {}, {"_id": 0, "refresh_token_encrypted": 0}
        ).to_list(50)

        report: dict[str, Any] = {
            "nichole_resource_id": n_id,
            "salt_resource_id": s_id,
            "connections_before": [_public_conn(c) for c in conns],
            "actions": [],
        }
        now = datetime.now(timezone.utc).isoformat()

        def _is_clients_mailbox(c: dict[str, Any]) -> bool:
            for key in ("microsoft_email", "mailbox_email"):
                val = (c.get(key) or "").lower()
                if val == SALT_OUTLOOK_MAILBOX.lower():
                    return True
            return False

        clients_conn = next((c for c in conns if _is_clients_mailbox(c)), None)
        nichole_candidates = [c for c in conns if not _is_clients_mailbox(c)]
        nichole_conn = nichole_candidates[0] if nichole_candidates else None

        if nichole_conn:
            cid = nichole_conn["connection_id"]
            patch = dict(tpl_n)
            mailbox = (
                nichole_conn.get("microsoft_email")
                or nichole_conn.get("mailbox_email")
                or patch.get("mailbox_email")
            )
            if mailbox:
                patch["mailbox_email"] = mailbox
            patch["visibility_only"] = False
            patch["updated_at"] = now
            await db.outlook_calendar_connections.update_one(
                {"connection_id": cid}, {"$set": patch}
            )
            report["actions"].append(
                {
                    "op": "patch_nichole_authoritative",
                    "connection_id": cid,
                    "mailbox_email": patch.get("mailbox_email"),
                }
            )

        if clients_conn:
            cid = clients_conn["connection_id"]
            patch = dict(tpl_c)
            patch["visibility_only"] = False
            patch["updated_at"] = now
            await db.outlook_calendar_connections.update_one(
                {"connection_id": cid}, {"$set": patch}
            )
            report["actions"].append(
                {"op": "patch_clients_authoritative", "connection_id": cid}
            )
        else:
            cid = generate_id()
            placeholder = {
                "connection_id": cid,
                "mailbox_email": SALT_OUTLOOK_MAILBOX,
                "microsoft_email": SALT_OUTLOOK_MAILBOX,
                "is_active": False,
                "authoritative_for_resource_ids": tpl_c["authoritative_for_resource_ids"],
                "category_maps": tpl_c["category_maps"],
                "visibility_only": False,
                "created_at": now,
                "updated_at": now,
                "oauth_pending": True,
                "placeholder_for": "clients_salt_authoritative",
            }
            await db.outlook_calendar_connections.insert_one(placeholder)
            report["actions"].append(
                {
                    "op": "insert_clients_placeholder",
                    "connection_id": cid,
                    "note": "is_active=false; OAuth must activate with refresh token",
                }
            )

        after = await db.outlook_calendar_connections.find(
            {}, {"_id": 0, "refresh_token_encrypted": 0}
        ).to_list(50)
        report["connections_after"] = [_public_conn(c) for c in after]
        report["locked_templates"] = templates

        if report_json:
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, indent=2, default=str))

        return report
    finally:
        client.close()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply locked Outlook connection templates (staging ops)."
    )
    parser.add_argument(
        "--report-json",
        default=None,
        help="Write before/after report JSON",
    )
    args = parser.parse_args()
    out_path = Path(args.report_json) if args.report_json else None
    report = await apply_templates(report_json=out_path)
    print(json.dumps({"actions": report["actions"]}, indent=2))
    if out_path:
        print(f"Wrote report: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
