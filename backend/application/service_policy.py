"""Shared booking eligibility policy for the service catalog."""

from __future__ import annotations

from typing import Any, Mapping, Optional


def _service_name(service: Mapping[str, Any] | None) -> str:
    return str((service or {}).get("name") or "").strip().lower()


def is_discovery_exempt(service: Mapping[str, Any] | None) -> bool:
    """Name fallback used only when a service has no stored prerequisite flag.

    Education and the discovery entry follow this exemption. Other services,
    including salt, are not special-cased by name.
    """
    if not service:
        return False
    if service.get("is_discovery_entry") is True:
        return True
    if service.get("is_prerequisite") is True:
        return True
    name = _service_name(service)
    return (
        "discovery call" in name
        or "natural health education" in name
        or "educational hour" in name
    )


def service_requires_prerequisite(
    service: Mapping[str, Any] | None,
    prerequisite_service_id: Optional[str] = None,
) -> bool:
    """True when this service stays locked until the current prerequisite is completed.

    The prerequisite service cannot require itself. A stored ``requires_prerequisite``
    flag wins. Older rows fall back to ``requires_discovery``, then to the education
    exemption. There is no salt-only override.
    """
    if not service:
        return True
    service_id = service.get("service_id")
    if prerequisite_service_id and service_id and service_id == prerequisite_service_id:
        return False
    if service.get("is_prerequisite") is True and not prerequisite_service_id:
        return False
    explicit = service.get("requires_prerequisite")
    if isinstance(explicit, bool):
        return explicit
    legacy = service.get("requires_discovery")
    if isinstance(legacy, bool):
        return legacy
    return not is_discovery_exempt(service)


def service_requires_discovery(
    service: Mapping[str, Any] | None,
    prerequisite_service_id: Optional[str] = None,
) -> bool:
    """Compatibility name for the prerequisite gate."""
    return service_requires_prerequisite(service, prerequisite_service_id)
