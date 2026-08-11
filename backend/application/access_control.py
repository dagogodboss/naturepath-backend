"""Pure access checks for practitioner-scoped resources (testable without HTTP)."""
from __future__ import annotations

from core.rbac import Permission, has_permission, normalize_role

ASSIGNABLE_ROLES = frozenset(
    {"customer", "staff", "manager", "practitioner", "admin", "owner"}
)
# Roles that only an owner principal may assign or target for mutation.
OWNER_PROTECTED_ROLES = frozenset({"owner"})
SENSITIVE_RBAC_PERMISSIONS = frozenset(
    {
        Permission.USER_ROLE_MANAGE.value,
        Permission.USER_STATUS_MANAGE.value,
    }
)
SENSITIVE_RBAC_ROLES = frozenset({"admin", "owner"})


class PractitionerAccessDenied(Exception):
    """Raised when a practitioner attempts to act on another practitioner's resource."""

    pass


class PrivilegeEscalationDenied(Exception):
    """Raised when an admin attempts an owner-only privilege change."""

    pass


def assert_admin_or_same_practitioner(
    user_role: str,
    acting_practitioner_id: str | None,
    resource_practitioner_id: str,
) -> None:
    """
    Admin may access any practitioner resource.
    Practitioner may access only resources for their own practitioner_id.
    """
    role = normalize_role(user_role)
    if has_permission(role, Permission.USER_ROLE_MANAGE):
        return
    if has_permission(role, Permission.PRACTITIONER_PROFILE_MANAGE):
        if acting_practitioner_id and acting_practitioner_id == resource_practitioner_id:
            return
    raise PractitionerAccessDenied(
        "Not allowed to access this practitioner resource"
    )


def assert_can_assign_role(
    actor_role: str | None,
    target_current_role: str | None,
    new_role: str,
) -> str:
    """
    Normalize and authorize a role change.

    Only owners may assign the owner role or mutate users who are already owners.
    """
    actor = normalize_role(actor_role)
    target = normalize_role(target_current_role)
    normalized = normalize_role(new_role)
    if normalized not in ASSIGNABLE_ROLES:
        raise PrivilegeEscalationDenied("Invalid role")
    if actor != "owner":
        if normalized in OWNER_PROTECTED_ROLES:
            raise PrivilegeEscalationDenied("Only owner can assign owner role")
        if target in OWNER_PROTECTED_ROLES:
            raise PrivilegeEscalationDenied("Only owner can modify owner accounts")
    return normalized


def assert_can_mutate_user_status(
    actor_role: str | None,
    target_current_role: str | None,
) -> None:
    """Only owners may activate/deactivate owner accounts."""
    actor = normalize_role(actor_role)
    target = normalize_role(target_current_role)
    if target in OWNER_PROTECTED_ROLES and actor != "owner":
        raise PrivilegeEscalationDenied("Only owner can modify owner accounts")


def rbac_override_requires_owner(
    *,
    ptype: str,
    v0: str,
    v1: str,
) -> bool:
    """
    True when creating/deleting this override must be performed by an owner.

    Blocks non-owner admins from granting role-manage or inheriting admin/owner.
    """
    subject = (v0 or "").strip().lower()
    object_ = (v1 or "").strip()
    if ptype == "g":
        parent = object_.lower()
        return subject in SENSITIVE_RBAC_ROLES or parent in SENSITIVE_RBAC_ROLES
    if ptype == "p":
        return object_ in SENSITIVE_RBAC_PERMISSIONS
    return True
