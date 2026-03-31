import pytest

from application.access_control import (
    PractitionerAccessDenied,
    assert_admin_or_same_practitioner,
)


def test_admin_can_access_any_practitioner_resource():
    assert_admin_or_same_practitioner("admin", None, "practitioner-xyz")
    assert_admin_or_same_practitioner("admin", "ignored", "other-id")


def test_practitioner_can_access_own_resource():
    assert_admin_or_same_practitioner("practitioner", "p1", "p1")


def test_practitioner_can_access_any_practitioner_resource():
    assert_admin_or_same_practitioner("practitioner", "p1", "p2")


def test_practitioner_without_profile_id_still_allowed():
    assert_admin_or_same_practitioner("practitioner", None, "p2")


def test_manager_role_denied_without_elevated_permission():
    with pytest.raises(PractitionerAccessDenied):
        assert_admin_or_same_practitioner("manager", None, "p1")


def test_customer_role_denied():
    with pytest.raises(PractitionerAccessDenied):
        assert_admin_or_same_practitioner("customer", None, "p1")
