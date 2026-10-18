#!/usr/bin/env python3
"""
Post–Entra admin consent cutover: probe app-only Graph, flip auth_mode, sync, prove.

Default: staging only. Prod requires staging prove success + --prod --i-understand-prod.
Does not start device-code flows or change DNS.

Usage (from repo backend/):
  set -a; source backend/.env; set +a
  DB_NAME=natural_path_staging MULTI_RESOURCE_SCHEDULING=true \\
    PYTHONPATH=backend python3 -m scripts.phase6_post_consent_cutover \\
    --dry-run --report-dir ../qa/reports/multi-resource-proof
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
if str(_THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from application.outlook_sync import OutlookSyncError, graph_client, sync_outlook_connection  # noqa: E402
from core.config import settings  # noqa: E402
from scripts.phase6_post_consent_helpers import (  # noqa: E402
    DEFAULT_MAILBOXES,
    EXIT_CONSENT_BLOCKER,
    EXIT_PROD_GATE,
    EXIT_STAGING_FAILED,
    PROD_CONNECTION_IDS,
    REQUIRED_STAGING_RUN_ENV,
    STAGING_CONNECTION_IDS,
    ProbeVerdict,
    busy_intervals_assertion,
    decode_jwt_roles,
    evaluate_mailbox_probes,
    qa_artifact_name,
    staging_env_gaps,
    validate_prod_gate,
)
DEFAULT_STAGING_API = "https://natural-path-api-staging-qxje535rja-uc.a.run.app"
DEFAULT_PROD_API = "https://natural-path-api-qxje535rja-uc.a.run.app"
DEFAULT_GCP_PROJECT = "project-990664b0-1bae-4746-88d"
DEFAULT_GCP_REGION = "us-central1"
STAGING_SERVICE = "natural-path-api-staging"
PROD_SERVICE = "natural-path-api"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_access_jwt(sub: str, jwt_key: str, *, minutes: int = 60) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps(
            {"sub": sub, "exp": int(exp.timestamp()), "type": "access"},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    sig = _b64url(hmac.new(jwt_key.encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    body: dict | None = None,
    timeout: int = 120,
) -> tuple[int, object]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:500]}


async def probe_mailboxes(mailboxes: tuple[str, ...]) -> tuple[ProbeVerdict, dict[str, Any]]:
    client = graph_client()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=1)
    end = now + timedelta(days=7)
    access = ""
    roles: list[str] = []
    token_error: str | None = None
    try:
        token_payload = await client.client_credentials_token()
        access = token_payload.get("access_token") or ""
        roles = decode_jwt_roles(access) if access else []
    except Exception as exc:
        token_error = str(exc)[:500]
    rows: list[dict[str, Any]] = []
    for upn in mailboxes:
        row: dict[str, Any] = {"mailbox": upn, "token_acquired": bool(access)}
        if token_error and not access:
            row["status"] = "error"
            row["error"] = token_error
            rows.append(row)
            continue
        if not access:
            row["status"] = "error"
            row["error"] = "no access_token from client_credentials"
            rows.append(row)
            continue
        try:
            events = await client.list_user_calendar_view(access, upn, start=start, end=end)
            row["status"] = "ok"
            row["event_count"] = len(events)
        except Exception as exc:
            row["status"] = "error"
            row["error"] = str(exc)[:500]
        rows.append(row)
    verdict = evaluate_mailbox_probes(rows)
    meta = {
        "jwt_roles": roles,
        "client_id_prefix": (client.client_id or "")[:8],
    }
    return verdict, meta


def gcloud_run_env_map(
    service: str,
    *,
    project: str,
    region: str,
) -> dict[str, str]:
    cmd = [
        "gcloud",
        "run",
        "services",
        "describe",
        service,
        f"--project={project}",
        f"--region={region}",
        "--format=json",
    ]
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=90)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"__error__": str(exc)[:400]}
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return {"__error__": "invalid gcloud json"}
    out: dict[str, str] = {}
    for item in doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [{}])[0].get(
        "env", []
    ):
        name = item.get("name")
        if not name:
            continue
        if "value" in item:
            out[name] = str(item["value"])
        elif item.get("valueFrom", {}).get("secretKeyRef"):
            out[name] = "(secret)"
    return out


def ensure_cloud_run_env(
    service: str,
    *,
    project: str,
    region: str,
    updates: dict[str, str],
    dry_run: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "service": service,
        "updates": updates,
        "dry_run": dry_run,
    }
    if dry_run:
        report["action"] = "skipped_dry_run"
        report["gcloud_command"] = (
            f"gcloud run services update {service} "
            f"--project {project} --region {region} "
            f"--update-env-vars {','.join(f'{k}={v}' for k, v in updates.items())}"
        )
        return report
    pairs = ",".join(f"{k}={v}" for k, v in updates.items())
    cmd = [
        "gcloud",
        "run",
        "services",
        "update",
        service,
        f"--project={project}",
        f"--region={region}",
        f"--update-env-vars={pairs}",
    ]
    try:
        subprocess.check_call(cmd, timeout=600)
        report["action"] = "updated"
        report["ok"] = True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        report["action"] = "failed"
        report["ok"] = False
        report["error"] = str(exc)[:400]
    return report


async def patch_auth_mode_mongo(db: Any, connection_id: str, *, dry_run: bool) -> dict[str, Any]:
    before = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection_id},
        {"auth_mode": 1, "mailbox_email": 1},
    )
    row = {
        "connection_id": connection_id,
        "before_auth_mode": (before or {}).get("auth_mode"),
        "mailbox_email": (before or {}).get("mailbox_email"),
    }
    if dry_run:
        row["action"] = "would_set_auth_mode_application"
        row["ok"] = True
        return row
    if not before:
        row["ok"] = False
        row["error"] = "connection_not_found"
        return row
    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection_id},
        {
            "$set": {
                "auth_mode": "application",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    row["action"] = "set_auth_mode_application"
    row["ok"] = True
    return row


async def patch_auth_mode_admin_api(
    api_base: str,
    connection_id: str,
    admin_token: str,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/api/admin/scheduling/outlook/connections/{connection_id}"
    if dry_run:
        return {
            "connection_id": connection_id,
            "action": "would_patch_auth_mode_application",
            "ok": True,
            "url": url,
        }
    status, body = http_json(
        "PATCH",
        url,
        token=admin_token,
        body={"auth_mode": "application"},
    )
    return {
        "connection_id": connection_id,
        "http_status": status,
        "body": body,
        "ok": status == 200,
    }


async def sync_connection(db: Any, connection_id: str, *, dry_run: bool) -> dict[str, Any]:
    conn = await db.outlook_calendar_connections.find_one({"connection_id": connection_id})
    if not conn:
        return {"connection_id": connection_id, "ok": False, "error": "not_found"}
    if dry_run:
        return {
            "connection_id": connection_id,
            "mailbox_email": conn.get("mailbox_email"),
            "action": "would_sync_in_process",
            "ok": True,
        }
    try:
        result = await sync_outlook_connection(db, conn)
        busy = await db.resource_busy_intervals.count_documents(
            {"connection_id": connection_id}
        )
        auth_ids = conn.get("authoritative_for_resource_ids") or []
        by_resource: dict[str, int] = {}
        for rid in auth_ids:
            by_resource[str(rid)] = await db.resource_busy_intervals.count_documents(
                {"resource_id": str(rid)}
            )
        return {
            "connection_id": connection_id,
            "mailbox_email": conn.get("mailbox_email"),
            "sync": result,
            "resource_busy_intervals_by_connection": busy,
            "resource_busy_intervals_by_resource": by_resource,
            "ok": True,
        }
    except OutlookSyncError as exc:
        return {
            "connection_id": connection_id,
            "ok": False,
            "error": str(exc),
            "status_code": exc.status_code,
        }


async def find_admin_user_id(db: Any) -> str | None:
    doc = await db.users.find_one(
        {"role": {"$in": ["owner", "admin"]}, "is_active": True},
        {"user_id": 1},
    )
    return doc.get("user_id") if doc else None


def write_artifact(report_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / name
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


async def run_staging_phase(args: argparse.Namespace, report: dict[str, Any]) -> bool:
    mailboxes = tuple(args.mailbox) if args.mailbox else DEFAULT_MAILBOXES
    verdict, probe_meta = await probe_mailboxes(mailboxes)
    report["probe"] = {
        "verdict": verdict.code,
        "message": verdict.message,
        "mailboxes": list(verdict.mailboxes),
        **probe_meta,
    }
    if not verdict.ok:
        report["ok"] = False
        if verdict.code == "entra_admin_consent_required":
            report["exit_hint"] = EXIT_CONSENT_BLOCKER
        else:
            report["exit_hint"] = EXIT_STAGING_FAILED
        return False

    if args.dry_run:
        report["staging_plan"] = {
            "ensure_env": REQUIRED_STAGING_RUN_ENV,
            "patch_connections": list(STAGING_CONNECTION_IDS.values()),
            "sync_connections": list(STAGING_CONNECTION_IDS.values()),
            "prove": {
                "INJECT_SYNTHETIC_BUSY": "0",
                "real_busy_only": True,
                "date": args.prove_date,
            },
        }
        report["ok"] = True
        report["note"] = "Dry-run: probe passed; no mutations performed."
        return True

    staging_env: dict[str, str] = {}
    if not args.skip_gcloud:
        staging_env = gcloud_run_env_map(
            STAGING_SERVICE,
            project=args.gcp_project,
            region=args.gcp_region,
        )
        gaps = staging_env_gaps(staging_env)
        report["staging_run_env_before"] = {k: staging_env.get(k) for k in REQUIRED_STAGING_RUN_ENV}
        report["staging_env_gaps"] = gaps
        if gaps and not args.skip_env_update:
            upd = ensure_cloud_run_env(
                STAGING_SERVICE,
                project=args.gcp_project,
                region=args.gcp_region,
                updates=dict(REQUIRED_STAGING_RUN_ENV),
                dry_run=False,
            )
            report["staging_env_update"] = upd
            if not upd.get("ok"):
                report["ok"] = False
                return False
        elif gaps:
            report["staging_env_manual"] = (
                "Set on natural-path-api-staging: "
                + ", ".join(f"{k}={v}" for k, v in REQUIRED_STAGING_RUN_ENV.items())
            )
    else:
        report["staging_env_skipped"] = True

    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[args.staging_db_name]
    try:
        patches: list[dict[str, Any]] = []
        syncs: list[dict[str, Any]] = []
        admin_token: str | None = None
        if args.use_admin_api:
            admin_id = await find_admin_user_id(db)
            if not admin_id:
                report["ok"] = False
                report["error"] = "no_admin_user_for_api_patch"
                return False
            admin_token = mint_access_jwt(admin_id, settings.jwt_secret_key)

        for label, cid in STAGING_CONNECTION_IDS.items():
            if args.use_admin_api and admin_token:
                patches.append(
                    await patch_auth_mode_admin_api(
                        args.staging_api,
                        cid,
                        admin_token,
                        dry_run=False,
                    )
                )
            else:
                patches.append(await patch_auth_mode_mongo(db, cid, dry_run=False))
        report["auth_mode_patches"] = patches
        if any(not p.get("ok") for p in patches):
            report["ok"] = False
            return False

        for cid in STAGING_CONNECTION_IDS.values():
            syncs.append(await sync_connection(db, cid, dry_run=False))
        report["syncs"] = syncs
        if any(not s.get("ok") for s in syncs):
            report["ok"] = False
            return False

        busy_counts: dict[str, int] = {}
        for s in syncs:
            for rid, cnt in (s.get("resource_busy_intervals_by_resource") or {}).items():
                busy_counts[rid] = int(cnt)
            conn_busy = int(s.get("resource_busy_intervals_by_connection") or 0)
            busy_counts[s["connection_id"]] = conn_busy

        busy_ok, busy_msg = busy_intervals_assertion(
            busy_counts,
            allow_empty=args.allow_empty_busy,
        )
        report["busy_assertion"] = {"ok": busy_ok, "detail": busy_msg, "counts": busy_counts}
        if not busy_ok:
            report["ok"] = False
            return False

        from scripts.prove_discovery_neq_salt_staging import prove  # noqa: WPS433

        settings.multi_resource_scheduling = True
        prove_report = await prove(
            db,
            args.prove_date,
            inject_synthetic=False,
            use_real_busy_only=True,
        )
        report["discovery_neq_salt_prove"] = prove_report
        if not prove_report.get("ok"):
            report["ok"] = False
            return False
        report["ok"] = True
        return True
    finally:
        client.close()


async def run_prod_phase(args: argparse.Namespace, report: dict[str, Any]) -> bool:
    report["prod"] = {"enabled": True}
    updates = {"MULTI_RESOURCE_SCHEDULING": "true"}
    if not args.skip_env_update:
        upd = ensure_cloud_run_env(
            PROD_SERVICE,
            project=args.gcp_project,
            region=args.gcp_region,
            updates=updates,
            dry_run=False,
        )
        report["prod_env_update"] = upd
        if not upd.get("ok"):
            report["ok"] = False
            return False
    else:
        report["prod_env_manual"] = (
            "After sign-off only: gcloud run services update natural-path-api "
            f"--project {args.gcp_project} --region {args.gcp_region} "
            "--update-env-vars MULTI_RESOURCE_SCHEDULING=true"
        )

    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[args.prod_db_name]
    try:
        patches = []
        syncs = []
        for cid in PROD_CONNECTION_IDS.values():
            patches.append(await patch_auth_mode_mongo(db, cid, dry_run=False))
        report["prod_auth_mode_patches"] = patches
        if any(not p.get("ok") for p in patches):
            report["ok"] = False
            return False
        for cid in PROD_CONNECTION_IDS.values():
            syncs.append(await sync_connection(db, cid, dry_run=False))
        report["prod_syncs"] = syncs
        if any(not s.get("ok") for s in syncs):
            report["ok"] = False
            return False

        from scripts.prove_discovery_neq_salt_staging import prove  # noqa: WPS433

        settings.multi_resource_scheduling = True
        prove_report = await prove(
            db,
            args.prove_date,
            inject_synthetic=False,
            use_real_busy_only=True,
        )
        report["prod_discovery_neq_salt_prove"] = prove_report
        report["ok"] = bool(prove_report.get("ok"))
        return report["ok"]
    finally:
        client.close()


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Post–Entra consent staging/prod cutover")
    parser.add_argument("--dry-run", action="store_true", help="Probe only; no mutations")
    parser.add_argument("--prod", action="store_true", help="Run prod phase after staging succeeds")
    parser.add_argument(
        "--i-understand-prod",
        action="store_true",
        help="Required with --prod (explicit prod acknowledgment)",
    )
    parser.add_argument("--skip-gcloud", action="store_true", help="Do not read/update Cloud Run env")
    parser.add_argument(
        "--skip-env-update",
        action="store_true",
        help="Document required env vars instead of gcloud update",
    )
    parser.add_argument(
        "--use-admin-api",
        action="store_true",
        help="PATCH auth_mode via staging admin API (default: Mongo)",
    )
    parser.add_argument(
        "--allow-empty-busy",
        action="store_true",
        help="Do not fail when resource_busy_intervals stay empty after sync",
    )
    parser.add_argument("--mailbox", action="append", default=[])
    parser.add_argument("--prove-date", default=os.environ.get("PROVE_DATE", "2026-10-21"))
    parser.add_argument(
        "--staging-api",
        default=os.environ.get("STAGING_API", DEFAULT_STAGING_API),
    )
    parser.add_argument(
        "--staging-db-name",
        default=os.environ.get("STAGING_DB_NAME", "natural_path_staging"),
    )
    parser.add_argument(
        "--prod-db-name",
        default=os.environ.get("PROD_DB_NAME", "natural_path"),
    )
    parser.add_argument("--gcp-project", default=os.environ.get("GCP_PROJECT", DEFAULT_GCP_PROJECT))
    parser.add_argument("--gcp-region", default=os.environ.get("GCP_REGION", DEFAULT_GCP_REGION))
    parser.add_argument(
        "--report-dir",
        default=str(_THIS_DIR.parent.parent / "qa/reports/multi-resource-proof"),
    )
    args = parser.parse_args()

    gate_err = validate_prod_gate(
        prod=args.prod,
        dry_run=args.dry_run,
        i_understand_prod=args.i_understand_prod,
    )
    if gate_err:
        print(gate_err, file=sys.stderr)
        return EXIT_PROD_GATE

    stamp = _utc_stamp()
    report: dict[str, Any] = {
        "kind": "phase6_post_consent_cutover",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "prod_requested": args.prod,
        "db_name": settings.db_name,
        "staging_db_name": args.staging_db_name,
        "staging_api": args.staging_api,
    }

    # Staging phase uses staging DB when env DB_NAME differs — prefer explicit staging db for mutations.
    if not args.dry_run:
        os.environ["DB_NAME"] = args.staging_db_name
        settings.db_name = args.staging_db_name

    staging_ok = await run_staging_phase(args, report)
    artifact_name = qa_artifact_name(phase="staging" if not args.prod else "staging-then-prod", stamp=stamp)
    artifact_path = write_artifact(Path(args.report_dir), artifact_name, report)
    print(f"Wrote QA artifact: {artifact_path}")

    if not staging_ok:
        print(report.get("probe", {}).get("message") or report.get("error") or "Staging cutover failed.")
        exit_hint = report.get("exit_hint")
        if exit_hint == EXIT_CONSENT_BLOCKER:
            return EXIT_CONSENT_BLOCKER
        return int(exit_hint or EXIT_STAGING_FAILED)

    if args.dry_run:
        print(report.get("note", "Dry-run complete."))
        return 0

    if not args.prod:
        print("Staging cutover complete. Prod not requested.")
        return 0

    # Prod phase uses prod DB
    os.environ["DB_NAME"] = args.prod_db_name
    settings.db_name = args.prod_db_name
    prod_report: dict[str, Any] = {
        "kind": "phase6_post_consent_cutover_prod",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parent_artifact": str(artifact_path),
    }
    prod_ok = await run_prod_phase(args, prod_report)
    prod_artifact = write_artifact(
        Path(args.report_dir),
        qa_artifact_name(phase="prod", stamp=stamp),
        prod_report,
    )
    print(f"Wrote prod QA artifact: {prod_artifact}")
    if not prod_ok:
        return EXIT_STAGING_FAILED
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
