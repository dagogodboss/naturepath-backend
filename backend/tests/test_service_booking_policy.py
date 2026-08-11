from application.service_policy import is_discovery_exempt, service_requires_discovery


def test_discovery_and_salt_are_bookable_without_discovery_completion():
    assert is_discovery_exempt({"name": "Discovery Call"}) is True
    assert is_discovery_exempt({"name": "Salt Session (Halotherapy)"}) is True
    assert service_requires_discovery({"name": "Salt Session"}) is False


def test_explicit_policy_overrides_legacy_name_fallback():
    assert service_requires_discovery(
        {"name": "Salt Session", "requires_discovery": True}
    ) is True
    assert service_requires_discovery(
        {"name": "Initial Consultation", "requires_discovery": False}
    ) is False


def test_other_services_remain_discovery_gated_by_default():
    assert service_requires_discovery({"name": "1-Hour Consultation"}) is True

