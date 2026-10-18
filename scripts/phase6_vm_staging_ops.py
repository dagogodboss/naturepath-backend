#!/usr/bin/env python3
"""VPC VM runner: staging Outlook sync + Discovery≠Salt prove + admin smoke."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pymongo

STAGING_API = os.environ.get(
    "STAGING_API",
    "https://natural-path-api-staging-30255322344.us-central1.run.app",
)
DB_NAME = os.environ.get("DB_NAME", "natural_path_staging")
PROJECT_NUMBER = os.environ.get("PROJECT_NUMBER", "30255322344")
CONNECTION_ID = os.environ.get(
    "CONNECTION_ID", "0ae88711-4e79-42b4-831f-141705d6ca9c"
)
PROVE_DATE = os.environ.get("PROVE_DATE", "2026-10-21")
NICHOLE_RESOURCE_ID = os.environ.get(
    "NICHOLE_RESOURCE_ID", "5786a4d5-93bd-5ae9-83ba-43db7872cf89"
)
INJECT_SYNTHETIC_BUSY = os.environ.get("INJECT_SYNTHETIC_BUSY", "1") == "1"


def metadata_token() -> str:
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())["access_token"]


def secret_value(name: str) -> str:
    token = metadata_token()
    url = (
        f"https://secretmanager.googleapis.com/v1/projects/{PROJECT_NUMBER}/"
        f"secrets/{name}/versions/latest:access"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())["payload"]["data"]
    return base64.b64decode(payload).decode()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_access(sub: str, jwt_key: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=60)
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:500]}


def main() -> int:
    mongo_url = secret_value("mongo-url")
    jwt_key = secret_value("jwt-secret")
    client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=15000)
    db = client[DB_NAME]

    conn = db.outlook_calendar_connections.find_one({"connection_id": CONNECTION_ID})
    sync_report: dict = {
        "kind": "outlook_connection_sync",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "connection_id": CONNECTION_ID,
        "db_name": DB_NAME,
        "staging_api": STAGING_API,
        "before": {
            "last_sync_status": (conn or {}).get("last_sync_status"),
            "last_sync_error": (conn or {}).get("last_sync_error"),
            "event_count": (conn or {}).get("event_count"),
        },
    }

    practitioner_id = (conn or {}).get("practitioner_id")
    practitioner = (
        db.practitioners.find_one({"practitioner_id": practitioner_id})
        if practitioner_id
        else None
    )
    user_id = (practitioner or {}).get("user_id")
    user = (
        db.users.find_one(
            {"user_id": user_id}, {"email": 1, "role": 1, "is_active": 1}
        )
        if user_id
        else None
    )
    sync_report["practitioner_id"] = practitioner_id
    sync_report["staff_email"] = (user or {}).get("email")

    if user_id and user and user.get("is_active", True):
        token = mint_access(user_id, jwt_key)
        status, body = http_json(
            "POST",
            f"{STAGING_API}/api/practitioners/outlook/sync",
            token=token,
        )
        sync_report["sync_http_status"] = status
        sync_report["sync_response"] = body
        sync_report["ok"] = status == 200 and isinstance(body, dict) and body.get("status") == "ok"
    else:
        sync_report["ok"] = False
        sync_report["error"] = "no_active_practitioner_user_for_connection"

    conn_after = db.outlook_calendar_connections.find_one({"connection_id": CONNECTION_ID})
    sync_report["after"] = {
        "last_sync_status": (conn_after or {}).get("last_sync_status"),
        "last_sync_error": (conn_after or {}).get("last_sync_error"),
        "event_count": (conn_after or {}).get("event_count"),
        "last_synced_at": (conn_after or {}).get("last_synced_at"),
    }
    busy_total = db.resource_busy_intervals.count_documents(
        {"resource_id": NICHOLE_RESOURCE_ID}
    )
    busy_on_date = list(
        db.resource_busy_intervals.find(
            {"resource_id": NICHOLE_RESOURCE_ID, "date": PROVE_DATE},
            {
                "_id": 0,
                "start_time": 1,
                "end_time": 1,
                "category_name": 1,
                "source": 1,
                "booking_id": 1,
            },
        ).limit(30)
    )
    sync_report["resource_busy_interval_counts"] = {NICHOLE_RESOURCE_ID: busy_total}
    sync_report["nichole_busy_on_prove_date"] = busy_on_date

    print("===SYNC_JSON_START===")
    print(json.dumps(sync_report, indent=2, default=str))
    print("===SYNC_JSON_END===")

    discovery = db.services.find_one(
        {
            "$or": [
                {"is_discovery_entry": True},
                {"name": {"$regex": "discovery", "$options": "i"}},
            ],
            "is_active": True,
        },
        {"service_id": 1, "name": 1},
    )
    salt = db.services.find_one(
        {"name": {"$regex": "^salt", "$options": "i"}, "is_active": True},
        {"service_id": 1, "name": 1},
    )
    synthetic_id = None
    if INJECT_SYNTHETIC_BUSY:
        synthetic_id = f"prove-synthetic-{PROVE_DATE}-1500"
        db.resource_busy_intervals.update_one(
            {"interval_id": synthetic_id},
            {
                "$set": {
                    "interval_id": synthetic_id,
                    "resource_id": NICHOLE_RESOURCE_ID,
                    "date": PROVE_DATE,
                    "start_time": "15:00",
                    "end_time": "15:45",
                    "show_as": "busy",
                    "authoritative": True,
                    "category_name": "Discovery",
                    "source": "staging_prove_synthetic",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )

    busy_on_prove_date = list(
        db.resource_busy_intervals.find(
            {"resource_id": NICHOLE_RESOURCE_ID, "date": PROVE_DATE},
            {
                "_id": 0,
                "interval_id": 1,
                "start_time": 1,
                "end_time": 1,
                "category_name": 1,
                "source": 1,
            },
        ).limit(30)
    )

    prove: dict = {
        "kind": "discovery_neq_salt_staging_prove",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": PROVE_DATE,
        "discovery_service": discovery,
        "salt_service": salt,
        "via": "staging_api_service_slots",
        "nichole_busy_on_date": busy_on_prove_date,
        "synthetic_busy_injected": INJECT_SYNTHETIC_BUSY,
        "synthetic_interval_id": synthetic_id,
    }
    if user_id and discovery and salt:
        token = mint_access(user_id, jwt_key)
        for label, sid in [
            ("discovery", discovery["service_id"]),
            ("salt", salt["service_id"]),
        ]:
            st, slots = http_json(
                "GET",
                f"{STAGING_API}/api/booking/service-slots?"
                f"service_id={sid}&date={PROVE_DATE}",
                token=token,
            )
            prove[f"{label}_http_status"] = st
            prove[f"{label}_slots"] = slots
        d_starts = []
        s_starts = []
        if isinstance(prove.get("discovery_slots"), list):
            d_starts = [s.get("start_time") for s in prove["discovery_slots"]]
        if isinstance(prove.get("salt_slots"), list):
            s_starts = [s.get("start_time") for s in prove["salt_slots"]]
        prove["discovery_slot_starts"] = d_starts
        prove["salt_slot_starts"] = s_starts
        prove["checks"] = {
            "discovery_15_00_blocked": "15:00" not in d_starts,
            "salt_15_00_offered": "15:00" in s_starts,
        }
        prove["ok"] = (
            prove["checks"]["discovery_15_00_blocked"]
            and prove["checks"]["salt_15_00_offered"]
        )
        prove["note"] = (
            "Synthetic Nichole Discovery busy 15:00–15:45 when INJECT_SYNTHETIC_BUSY=1; "
            "else relies on bookings/Outlook resource_busy_intervals."
        )
    else:
        prove["ok"] = False
        prove["error"] = "missing_user_or_services"

    if synthetic_id:
        db.resource_busy_intervals.delete_one({"interval_id": synthetic_id})
        prove["synthetic_cleaned_up"] = True

    print("===PROVE_JSON_START===")
    print(json.dumps(prove, indent=2, default=str))
    print("===PROVE_JSON_END===")

    admin = db.users.find_one(
        {"role": {"$in": ["owner", "admin"]}, "is_active": True},
        {"user_id": 1, "email": 1, "role": 1},
    )
    admin_smoke: dict = {
        "kind": "phase_6_staging_admin_smoke",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "staging_api": STAGING_API,
        "admin_user": (
            {"email": admin.get("email"), "role": admin.get("role")} if admin else None
        ),
    }
    if admin:
        token = mint_access(admin["user_id"], jwt_key)
        st, resources = http_json(
            "GET", f"{STAGING_API}/api/admin/resources", token=token
        )
        if st == 200 and isinstance(resources, dict):
            preview = {
                "total": resources.get("total"),
                "resource_names": [
                    r.get("name") for r in (resources.get("items") or [])[:10]
                ],
            }
        else:
            preview = resources
        admin_smoke["GET /api/admin/resources"] = {"status": st, "body_preview": preview}
        admin_smoke["ran"] = True
        admin_smoke["ok"] = st == 200
    else:
        admin_smoke["ran"] = False
        admin_smoke["ok"] = False
        admin_smoke["reason"] = "no_active_admin_or_owner_in_staging_db"

    print("===ADMIN_JSON_START===")
    print(json.dumps(admin_smoke, indent=2, default=str))
    print("===ADMIN_JSON_END===")

    client.close()
    exit_code = 0
    if not prove.get("ok"):
        exit_code = 1
    if not sync_report.get("ok"):
        exit_code = max(exit_code, 2)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
