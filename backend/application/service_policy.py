"""Shared booking eligibility policy for the service catalog."""

from __future__ import annotations

from typing import Any, Mapping


def _service_name(service: Mapping[str, Any] | None) -> str:
    return str((service or {}).get("name") or "").strip().lower()


def is_discovery_exempt(service: Mapping[str, Any] | None) -> bool:
    if not service:
        return False
    if service.get("is_discovery_entry") is True:
        return True
    name = _service_name(service)
    return "discovery call" in name or "salt session" in name or "halotherapy" in name


def service_requires_discovery(service: Mapping[str, Any] | None) -> bool:
    if not service:
        return True
    explicit = service.get("requires_discovery")
    if isinstance(explicit, bool):
        return explicit
    return not is_discovery_exempt(service)

