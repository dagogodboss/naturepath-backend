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


def test_practitioner_cannot_access_other_resource():
    with pytest.raises(PractitionerAccessDenied):
        assert_admin_or_same_practitioner("practitioner", "p1", "p2")


def test_practitioner_missing_id_denied():
    with pytest.raises(PractitionerAccessDenied):
        assert_admin_or_same_practitioner("practitioner", None, "p2")


def test_customer_role_denied():
    with pytest.raises(PractitionerAccessDenied):
        assert_admin_or_same_practitioner("customer", None, "p1")
