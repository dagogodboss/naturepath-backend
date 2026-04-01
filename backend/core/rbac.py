"""
Central RBAC role and permission mapping.

Base policy loads from rbac_policy.csv; optional rows in MongoDB collection
`rbac_policy_overrides` append policies (p) and groupings (g) at startup and
after admin reload.
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Any, Iterable

import casbin
from motor.motor_asyncio import AsyncIOMotorDatabase


class SystemRole(str, Enum):
    CUSTOMER = "customer"
    STAFF = "staff"
    MANAGER = "manager"
    PRACTITIONER = "practitioner"
    ADMIN = "admin"
    OWNER = "owner"


class Permission(str, Enum):
    PROFILE_READ = "profile:read"
    PROFILE_WRITE = "profile:write"
    BOOKING_CREATE = "booking:create"
    BOOKING_READ_OWN = "booking:read:own"
    BOOKING_READ_ALL = "booking:read:all"
    BOOKING_MANAGE = "booking:manage"
    BOOKING_COMPLETE = "booking:complete"
    PRACTITIONER_PROFILE_MANAGE = "practitioner:profile:manage"
    PRACTITIONER_SLOT_MANAGE = "practitioner:slot:manage"
    SERVICE_READ = "service:read"
    SERVICE_CREATE = "service:create"
    SERVICE_UPDATE = "service:update"
    SERVICE_DELETE = "service:delete"
    ADMIN_DASHBOARD_READ = "admin:dashboard:read"
    USER_ROLE_MANAGE = "user:role:manage"
    USER_STATUS_MANAGE = "user:status:manage"


ROLE_ALIASES: dict[str, SystemRole] = {
    "owner": SystemRole.OWNER,
    "practitioner": SystemRole.PRACTITIONER,
    "admin": SystemRole.ADMIN,
    "manager": SystemRole.MANAGER,
    "staff": SystemRole.STAFF,
    "customer": SystemRole.CUSTOMER,
}


def normalize_role(role: str | None) -> str:
    """Return a canonical role string."""
    if not role:
        return SystemRole.CUSTOMER.value
    lowered = role.strip().lower()
    mapped = ROLE_ALIASES.get(lowered)
    if mapped:
        return mapped.value
    return lowered if lowered in {m.value for m in SystemRole} else SystemRole.CUSTOMER.value


_enforcer: casbin.Enforcer | None = None


def _build_enforcer(override_rows: list[dict[str, Any]]) -> casbin.Enforcer:
    base_dir = os.path.dirname(__file__)
    model_path = os.path.join(base_dir, "rbac_model.conf")
    policy_path = os.path.join(base_dir, "rbac_policy.csv")
    e = casbin.Enforcer(model_path, policy_path)
    for doc in override_rows:
        ptype = doc.get("ptype")
        if ptype == "p":
            v2 = doc.get("v2") or "use"
            e.add_policy(str(doc["v0"]), str(doc["v1"]), str(v2))
        elif ptype == "g":
            e.add_grouping_policy(str(doc["v0"]), str(doc["v1"]))
    return e


def ensure_enforcer_loaded() -> None:
    global _enforcer
    if _enforcer is None:
        _enforcer = _build_enforcer([])


def get_enforcer() -> casbin.Enforcer:
    ensure_enforcer_loaded()
    assert _enforcer is not None
    return _enforcer


async def load_policy_overrides_from_db(db: AsyncIOMotorDatabase) -> None:
    """Rebuild enforcer: CSV base plus all documents in rbac_policy_overrides."""
    global _enforcer
    cursor = db.rbac_policy_overrides.find({})
    docs = await cursor.to_list(length=10_000)
    rows: list[dict[str, Any]] = []
    for d in docs:
        row: dict[str, Any] = {
            "ptype": d["ptype"],
            "v0": d["v0"],
            "v1": d["v1"],
        }
        if d.get("v2") is not None:
            row["v2"] = d["v2"]
        rows.append(row)
    _enforcer = _build_enforcer(rows)


def _principal_role_and_user_id(
    principal: str | dict | None,
) -> tuple[str, str | None]:
    if isinstance(principal, dict):
        return normalize_role(principal.get("role")), principal.get("user_id")
    return normalize_role(principal), None


def has_permission(principal: str | dict | None, permission: Permission) -> bool:
    """
    Check role-based policy, then optional per-user policy rows (subject = user_id).
    """
    role, user_id = _principal_role_and_user_id(principal)
    enforcer = get_enforcer()
    if bool(enforcer.enforce(role, permission.value, "use")):
        return True
    if user_id:
        return bool(enforcer.enforce(str(user_id), permission.value, "use"))
    return False


def any_permission(
    principal: str | dict | None, permissions: Iterable[Permission]
) -> bool:
    return any(has_permission(principal, perm) for perm in permissions)
