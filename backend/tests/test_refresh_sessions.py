"""Refresh rotation, reuse handling, logout, and absolute session lifetime."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from jose import jwt

from application.auth_attempt_limits import AttemptLimiter
from application.refresh_sessions import MemoryRefreshSessionStore
from application.use_cases.auth_use_case import AuthUseCase
from core.config import settings
from tests.test_auth_attempt_limits import DictCache


def _user():
    return {
        "user_id": "user-1",
        "email": "person@example.com",
        "role": "customer",
        "is_active": True,
        "is_verified": True,
        "phone": "5551234567",
        "session_epoch": 0,
    }


def _use_case(user=None, store=None):
    current = user or _user()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=current)
    repo.get_by_email = AsyncMock(return_value=current)
    repo.update = AsyncMock(return_value=current)
    uc = AuthUseCase(
        repo,
        session_store=store or MemoryRefreshSessionStore(),
        attempt_limiter=AttemptLimiter(DictCache()),
    )
    current["password_hash"] = uc._hash_password("password123")
    return uc, current


def _decode(token):
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


@pytest.mark.asyncio
async def test_refresh_credential_cannot_be_exchanged_twice():
    uc, _user_doc = _use_case()
    first = await uc.login("person@example.com", "password123")
    rotated = await uc.refresh_token(first["refresh_token"])
    assert rotated["refresh_token"] != first["refresh_token"]

    with pytest.raises(ValueError, match="Invalid refresh token"):
        await uc.refresh_token(first["refresh_token"])

    # Within the grace window the family stays usable.
    again = await uc.refresh_token(rotated["refresh_token"])
    assert again["access_token"]


@pytest.mark.asyncio
async def test_reuse_after_grace_revokes_the_session_family():
    store = MemoryRefreshSessionStore()
    uc, _user_doc = _use_case(store=store)
    first = await uc.login("person@example.com", "password123")
    rotated = await uc.refresh_token(first["refresh_token"])
    old_jti = _decode(first["refresh_token"])["jti"]
    sid, _deadline = store.grace[old_jti]
    store.grace[old_jti] = (sid, time.monotonic() - 1)

    with pytest.raises(ValueError, match="Invalid refresh token"):
        await uc.refresh_token(first["refresh_token"])
    with pytest.raises(ValueError, match="Invalid refresh token"):
        await uc.refresh_token(rotated["refresh_token"])


@pytest.mark.asyncio
async def test_logout_revokes_refresh_and_access():
    uc, _user_doc = _use_case()
    issued = await uc.login("person@example.com", "password123")
    await uc.logout(issued["refresh_token"])

    with pytest.raises(ValueError, match="Invalid refresh token|Session is no longer valid"):
        await uc.refresh_token(issued["refresh_token"])
    with pytest.raises(ValueError, match="Session is no longer valid"):
        await uc.get_current_user(issued["access_token"])


@pytest.mark.asyncio
async def test_client_hint_cannot_extend_session_lifetime():
    uc, _user_doc = _use_case()
    issued = await uc.login("person@example.com", "password123", standalone=False)
    original = _decode(issued["refresh_token"])
    rotated = await uc.refresh_token(issued["refresh_token"], standalone=True)
    renewed = _decode(rotated["refresh_token"])

    assert renewed.get("standalone") is not True
    assert int(renewed["session_exp"]) == int(original["session_exp"])
    assert int(renewed["exp"]) <= int(original["session_exp"])


@pytest.mark.asyncio
async def test_standalone_session_keeps_its_original_deadline():
    uc, _user_doc = _use_case()
    issued = await uc.login("person@example.com", "password123", standalone=True)
    original = _decode(issued["refresh_token"])
    assert original.get("standalone") is True
    assert int(original["session_exp"]) - int(datetime.now(timezone.utc).timestamp()) > int(
        timedelta(days=60).total_seconds()
    )
    rotated = await uc.refresh_token(issued["refresh_token"], standalone=False)
    renewed = _decode(rotated["refresh_token"])
    assert renewed.get("standalone") is True
    assert int(renewed["session_exp"]) == int(original["session_exp"])


@pytest.mark.asyncio
async def test_epoch_change_invalidates_existing_sessions():
    uc, user = _use_case()
    issued = await uc.login("person@example.com", "password123")
    user["session_epoch"] = 1
    with pytest.raises(ValueError, match="Session is no longer valid"):
        await uc.get_current_user(issued["access_token"])
    with pytest.raises(ValueError, match="Session is no longer valid"):
        await uc.refresh_token(issued["refresh_token"])


@pytest.mark.asyncio
async def test_legacy_refresh_credential_works_once():
    uc, _user_doc = _use_case()
    legacy = uc._create_refresh_token(
        {"sub": "user-1", "email": "person@example.com", "role": "customer"},
        standalone=False,
    )
    rotated = await uc.refresh_token(legacy)
    assert rotated["access_token"]
    with pytest.raises(ValueError, match="Invalid refresh token"):
        await uc.refresh_token(legacy)
