import pytest

from application.access_control import (
    PractitionerAccessDenied,
    PrivilegeEscalationDenied,
    assert_admin_or_same_practitioner,
    assert_can_assign_role,
    assert_can_mutate_user_status,
    rbac_override_requires_owner,
)


def test_admin_can_access_any_practitioner_resource():
    assert_admin_or_same_practitioner("admin", None, "practitioner-xyz")
    assert_admin_or_same_practitioner("admin", "ignored", "other-id")


def test_owner_can_access_any_practitioner_resource():
    assert_admin_or_same_practitioner("owner", None, "practitioner-xyz")


def test_practitioner_can_access_own_resource():
    assert_admin_or_same_practitioner("practitioner", "p1", "p1")


def test_practitioner_cannot_access_other_resource():
    with pytest.raises(PractitionerAccessDenied):
        assert_admin_or_same_practitioner("practitioner", "p1", "p2")


def test_practitioner_without_profile_id_denied_for_other():
    with pytest.raises(PractitionerAccessDenied):
        assert_admin_or_same_practitioner("practitioner", None, "p2")


def test_manager_role_denied_without_elevated_permission():
    with pytest.raises(PractitionerAccessDenied):
        assert_admin_or_same_practitioner("manager", None, "p1")


def test_customer_role_denied():
    with pytest.raises(PractitionerAccessDenied):
        assert_admin_or_same_practitioner("customer", None, "p1")


def test_admin_cannot_assign_owner_role():
    with pytest.raises(PrivilegeEscalationDenied):
        assert_can_assign_role("admin", "customer", "owner")


def test_admin_cannot_mutate_owner_role():
    with pytest.raises(PrivilegeEscalationDenied):
        assert_can_assign_role("admin", "owner", "admin")


def test_owner_can_assign_owner_role():
    assert assert_can_assign_role("owner", "admin", "owner") == "owner"


def test_admin_can_assign_admin_role():
    assert assert_can_assign_role("admin", "staff", "admin") == "admin"


def test_admin_cannot_deactivate_owner():
    with pytest.raises(PrivilegeEscalationDenied):
        assert_can_mutate_user_status("admin", "owner")


def test_owner_can_deactivate_owner():
    assert_can_mutate_user_status("owner", "owner")


def test_sensitive_rbac_override_requires_owner():
    assert rbac_override_requires_owner(ptype="g", v0="customer", v1="admin") is True
    assert rbac_override_requires_owner(
        ptype="p", v0="customer", v1="user:role:manage"
    ) is True
    assert rbac_override_requires_owner(
        ptype="p", v0="staff", v1="booking:manage"
    ) is False
