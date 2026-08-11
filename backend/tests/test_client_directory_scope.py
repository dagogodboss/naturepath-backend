import pytest

from application.client_directory import client_booking_filter


def test_owner_and_admin_see_clinic_wide_booked_clients():
    assert client_booking_filter({"user": {"role": "owner"}, "practitioner": None}) == {
        "customer_id": {"$ne": None}
    }
    assert client_booking_filter({"user": {"role": "admin"}, "practitioner": None}) == {
        "customer_id": {"$ne": None}
    }


def test_practitioner_scope_is_limited_to_assigned_bookings():
    assert client_booking_filter(
        {
            "user": {"role": "practitioner"},
            "practitioner": {"practitioner_id": "p-1"},
        }
    ) == {"customer_id": {"$ne": None}, "practitioner_id": "p-1"}


def test_non_practitioner_without_clinic_admin_scope_is_rejected():
    with pytest.raises(ValueError, match="Practitioner profile required"):
        client_booking_filter({"user": {"role": "customer"}, "practitioner": None})
