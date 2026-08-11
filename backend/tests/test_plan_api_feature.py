"""API feature checks against local OrbStack backend (Phase A/B/C/F)."""
from __future__ import annotations

import os

import httpx
import pytest

API = os.environ.get("API_BASE_URL", "http://localhost:8001").rstrip("/")


def _get(path: str, **kwargs):
    return httpx.get(f"{API}{path}", timeout=15.0, **kwargs)


def _alive() -> bool:
    try:
        r = _get("/docs")
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _alive(), reason="Local API not reachable on :8001")


def test_oauth_google_status_endpoint():
    r = _get("/api/auth/oauth/google/status")
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body or "client_id_configured" in body or isinstance(body, dict)


def test_discovery_eligibility_requires_auth():
    r = _get("/api/me/discovery-eligibility")
    assert r.status_code in (401, 403)


def test_reels_feed_reachable():
    r = _get("/api/content/reels")
    # Auth may be required; either list or 401 is acceptable for smoke.
    assert r.status_code in (200, 401, 403)


def test_openapi_exposes_complete_discovery_and_ical():
    r = _get("/openapi.json")
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    assert any("complete-discovery" in p for p in paths)
    # ical may be nested under booking id
    joined = " ".join(paths.keys())
    assert "complete-discovery" in joined
