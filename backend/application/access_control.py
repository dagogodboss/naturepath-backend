"""Pure access checks for practitioner-scoped resources (testable without HTTP)."""
from __future__ import annotations


class PractitionerAccessDenied(Exception):
    """Raised when a practitioner attempts to act on another practitioner's resource."""

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
    if user_role == "admin":
        return
    if user_role == "practitioner":
        if acting_practitioner_id and acting_practitioner_id == resource_practitioner_id:
            return
    raise PractitionerAccessDenied(
        "Not allowed to access this practitioner resource"
    )
