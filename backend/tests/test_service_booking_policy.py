from application.service_catalog import SERVICE_CATALOG
from application.service_policy import is_discovery_exempt, service_requires_prerequisite


def _by_name(name):
    return next(entry for entry in SERVICE_CATALOG if entry["name"] == name)


def test_catalog_starting_prerequisite_flags():
    assert _by_name("Discovery Call")["is_prerequisite"] is True
    assert _by_name("Discovery Call")["requires_prerequisite"] is False
    assert _by_name("Salt Session (Halotherapy)")["requires_prerequisite"] is False
    assert _by_name("Natural Health Education Hour")["requires_prerequisite"] is False
    for name in (
        "Wellness Consultation",
        "2-Hours Extended Consultation",
        "Follow-up Consultation",
        "Direct-to-Consumer Lab Testing",
    ):
        assert _by_name(name)["requires_prerequisite"] is True
        assert _by_name(name)["is_prerequisite"] is False


def test_discovery_and_education_are_bookable_without_discovery_completion():
    assert is_discovery_exempt({"name": "Discovery Call"}) is True
    assert is_discovery_exempt({"name": "Natural Health Education Hour"}) is True
    assert is_discovery_exempt({"name": "Salt Session (Halotherapy)"}) is False
    assert service_requires_prerequisite({"name": "Salt Session"}) is True
    assert (
        service_requires_prerequisite(
            {"name": "Salt Session (Halotherapy)", "requires_prerequisite": False}
        )
        is False
    )


def test_stored_flag_is_honored_without_a_salt_override():
    assert (
        service_requires_prerequisite(
            {"name": "Salt Session", "requires_discovery": False}
        )
        is False
    )
    assert (
        service_requires_prerequisite(
            {"name": "Salt Session", "requires_prerequisite": True}
        )
        is True
    )
    assert (
        service_requires_prerequisite(
            {"name": "Initial Consultation", "requires_discovery": False}
        )
        is False
    )


def test_prerequisite_service_cannot_require_itself():
    service = {
        "service_id": "disc",
        "name": "Discovery Call",
        "requires_prerequisite": True,
    }
    assert service_requires_prerequisite(service, "disc") is False
    assert service_requires_prerequisite(service, "other") is True


def test_other_services_remain_gated_by_default():
    assert service_requires_prerequisite({"name": "1-Hour Consultation"}) is True
