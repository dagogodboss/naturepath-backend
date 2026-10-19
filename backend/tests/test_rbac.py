"""Casbin role vs permission checks for owner / practitioner split."""

from core.rbac import Permission, has_permission


def test_owner_inherits_admin_user_role_manage():
    assert has_permission("owner", Permission.USER_ROLE_MANAGE)


def test_practitioner_cannot_manage_users():
    assert not has_permission("practitioner", Permission.USER_ROLE_MANAGE)


def test_practitioner_can_complete_bookings():
    assert has_permission("practitioner", Permission.BOOKING_COMPLETE)


def test_practitioner_can_update_services():
    assert has_permission("practitioner", Permission.SERVICE_UPDATE)


def test_practitioner_cannot_read_all_bookings_globally():
    assert not has_permission("practitioner", Permission.BOOKING_READ_ALL)


def test_user_level_grant_in_mongo_requires_runtime_load():
    # Documented behavior: per-user p rules are merged when load_policy_overrides_from_db runs.
    assert not has_permission(
        {"role": "customer", "user_id": "nonexistent-user-id"},
        Permission.USER_ROLE_MANAGE,
    )


def test_manager_lacks_scheduling_admin_gate_permissions():
    """#9 C5 — ordinary manager is not admin_or_practitioner for scheduling APIs."""
    assert not has_permission("manager", Permission.USER_ROLE_MANAGE)
    assert not has_permission("manager", Permission.PRACTITIONER_PROFILE_MANAGE)
    assert has_permission("admin", Permission.USER_ROLE_MANAGE)
    assert has_permission("practitioner", Permission.PRACTITIONER_PROFILE_MANAGE)
