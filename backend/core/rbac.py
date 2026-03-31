"""
Central RBAC role and permission mapping.
"""
from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from typing import Iterable
import casbin


class SystemRole(str, Enum):
    CUSTOMER = "customer"
    STAFF = "staff"
    MANAGER = "manager"
    PRACTITIONER = "practitioner"
    ADMIN = "admin"


class Permission(str, Enum):
    PROFILE_READ = "profile:read"
    PROFILE_WRITE = "profile:write"
    BOOKING_CREATE = "booking:create"
    BOOKING_READ_OWN = "booking:read:own"
    BOOKING_READ_ALL = "booking:read:all"
    BOOKING_MANAGE = "booking:manage"
    PRACTITIONER_PROFILE_MANAGE = "practitioner:profile:manage"
    PRACTITIONER_SLOT_MANAGE = "practitioner:slot:manage"
    SERVICE_READ = "service:read"
    SERVICE_CREATE = "service:create"
    SERVICE_UPDATE = "service:update"
    SERVICE_DELETE = "service:delete"
    ADMIN_DASHBOARD_READ = "admin:dashboard:read"
    USER_ROLE_MANAGE = "user:role:manage"
    USER_STATUS_MANAGE = "user:status:manage"


# Practitioner and admin intentionally share full elevated capability.
ROLE_ALIASES: dict[str, SystemRole] = {
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
    return ROLE_ALIASES.get(lowered, SystemRole.CUSTOMER).value


@lru_cache()
def get_enforcer() -> casbin.Enforcer:
    base_dir = os.path.dirname(__file__)
    model_path = os.path.join(base_dir, "rbac_model.conf")
    policy_path = os.path.join(base_dir, "rbac_policy.csv")
    return casbin.Enforcer(model_path, policy_path)


def has_permission(role: str | None, permission: Permission) -> bool:
    canonical = normalize_role(role)
    enforcer = get_enforcer()
    return bool(enforcer.enforce(canonical, permission.value, "use"))


def any_permission(role: str | None, permissions: Iterable[Permission]) -> bool:
    return any(has_permission(role, perm) for perm in permissions)
