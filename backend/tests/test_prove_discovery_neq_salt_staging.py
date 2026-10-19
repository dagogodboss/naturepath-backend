"""Regression: staging prove must resolve Nichole without requiring resource.kind."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS.parent))

from scripts.prove_discovery_neq_salt_staging import (  # noqa: E402
    _nichole_resource_id,
)


class _FakeFind:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, query, projection=None):  # noqa: ARG002
        return self._doc


class _FakeDb:
    def __init__(self, *, services=None, resources=None):
        self.services = _FakeFind(services)
        self.resources = resources or _FakeResources([])


class _FakeResources:
    def __init__(self, docs):
        self._docs = docs

    async def find_one(self, query, projection=None):  # noqa: ARG002
        for doc in self._docs:
            if "kind" in query and doc.get("kind") != query["kind"]:
                continue
            if query.get("active") is True and not doc.get("active"):
                continue
            name_q = query.get("name")
            if isinstance(name_q, dict) and "$regex" in name_q:
                needle = str(name_q["$regex"]).lower()
                if needle not in str(doc.get("name") or "").lower():
                    continue
            return doc
        return None


def test_nichole_from_discovery_required_resource_without_kind():
    db = _FakeDb(
        services={"required_resource_id": "rid-nichole"},
        resources=_FakeResources(
            [{"resource_id": "rid-nichole", "name": "Dr. Nichole", "active": True}]
        ),
    )
    rid = asyncio.run(_nichole_resource_id(db, discovery_service_id="disc-1"))
    assert rid == "rid-nichole"


def test_nichole_name_fallback_when_no_discovery():
    db = _FakeDb(
        services=None,
        resources=_FakeResources(
            [
                {"resource_id": "salt", "name": "Salt room", "active": True},
                {"resource_id": "nid", "name": "Dr. Nichole", "active": True},
            ]
        ),
    )
    rid = asyncio.run(_nichole_resource_id(db, discovery_service_id=None))
    assert rid == "nid"


def test_nichole_kind_fallback():
    db = _FakeDb(
        services=None,
        resources=_FakeResources(
            [
                {
                    "resource_id": "prac",
                    "name": "Practitioner",
                    "kind": "practitioner",
                    "active": True,
                }
            ]
        ),
    )
    rid = asyncio.run(_nichole_resource_id(db))
    assert rid == "prac"
