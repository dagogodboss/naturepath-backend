"""Refresh rotation, reuse handling, logout, and absolute session lifetime."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from jose import jwt

from application.auth_attempt_limits import AttemptLimiter
from application.refresh_sessions import MemoryRefreshSessionStore, RedisRefreshSessionStore
from application.use_cases.auth_use_case import AuthUnavailable, AuthUseCase
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


@pytest.mark.asyncio
async def test_unavailable_revocation_state_does_not_accept_refresh():
    store = MemoryRefreshSessionStore()
    uc, _user_doc = _use_case(store=store)
    issued = await uc.login("person@example.com", "password123")

    async def unavailable(_sid, _user_id):
        return "unavailable"

    store.session_state = unavailable
    with pytest.raises(AuthUnavailable):
        await uc.get_current_user(issued["access_token"])
    with pytest.raises(AuthUnavailable):
        await uc.refresh_token(issued["refresh_token"])
    assert store.sessions


@pytest.mark.asyncio
async def test_storage_outage_does_not_accept_refresh():
    store = MemoryRefreshSessionStore()
    uc, _user_doc = _use_case(store=store)
    issued = await uc.login("person@example.com", "password123")
    store.available = False

    with pytest.raises(AuthUnavailable):
        await uc.refresh_token(issued["refresh_token"])
    with pytest.raises(AuthUnavailable):
        await uc.get_current_user(issued["access_token"])
    assert await uc.logout(issued["refresh_token"]) is False

    store.available = True
    still_valid = await uc.refresh_token(issued["refresh_token"])
    assert still_valid["access_token"]


@pytest.mark.asyncio
async def test_revocation_survives_a_later_storage_outage():
    store = MemoryRefreshSessionStore()
    uc, _user_doc = _use_case(store=store)
    issued = await uc.login("person@example.com", "password123")
    sid = _decode(issued["refresh_token"])["sid"]
    assert await uc.logout(issued["refresh_token"]) is True
    store.available = False

    with pytest.raises(AuthUnavailable):
        await uc.get_current_user(issued["access_token"])
    with pytest.raises(AuthUnavailable):
        await uc.refresh_token(issued["refresh_token"])

    store.available = True
    with pytest.raises(ValueError, match="Session is no longer valid"):
        await uc.get_current_user(issued["access_token"])
    with pytest.raises(ValueError, match="Invalid refresh token"):
        await uc.refresh_token(issued["refresh_token"])
    assert sid not in store.sessions


@pytest.mark.asyncio
async def test_epoch_bump_stays_rejected_when_session_store_is_down():
    store = MemoryRefreshSessionStore()
    uc, user = _use_case(store=store)
    issued = await uc.login("person@example.com", "password123")
    user["session_epoch"] = 1
    store.available = False

    with pytest.raises(ValueError, match="Session is no longer valid"):
        await uc.get_current_user(issued["access_token"])
    with pytest.raises(ValueError, match="Session is no longer valid"):
        await uc.refresh_token(issued["refresh_token"])


@pytest.mark.asyncio
async def test_logout_then_refresh_does_not_create_a_session():
    store = MemoryRefreshSessionStore()
    uc, _user_doc = _use_case(store=store)
    issued = await uc.login("person@example.com", "password123")
    sid = _decode(issued["refresh_token"])["sid"]
    await uc.logout(issued["refresh_token"])

    with pytest.raises(ValueError, match="Invalid refresh token"):
        await uc.refresh_token(issued["refresh_token"])
    assert sid not in store.sessions
    assert store.refresh == {}


@pytest.mark.asyncio
async def test_inflight_refresh_cannot_recreate_logged_out_session():
    store = MemoryRefreshSessionStore()
    uc, _user_doc = _use_case(store=store)
    issued = await uc.login("person@example.com", "password123")
    sid = _decode(issued["access_token"])["sid"]
    original_rotate = store.rotate

    async def rotate_after_logout(**kwargs):
        await uc.logout(issued["refresh_token"])
        return await original_rotate(**kwargs)

    store.rotate = rotate_after_logout
    with pytest.raises(ValueError, match="Invalid refresh token"):
        renewed = await uc.refresh_token(issued["refresh_token"])
        await uc.get_current_user(renewed["access_token"])

    assert sid not in store.sessions
    with pytest.raises(ValueError, match="Session is no longer valid"):
        await uc.get_current_user(issued["access_token"])


@pytest.mark.asyncio
async def test_logout_after_completed_refresh_invalidates_the_new_session():
    uc, _user_doc = _use_case()
    issued = await uc.login("person@example.com", "password123")
    rotated = await uc.refresh_token(issued["refresh_token"])
    assert await uc.logout(rotated["refresh_token"]) is True

    with pytest.raises(ValueError, match="Session is no longer valid"):
        await uc.get_current_user(rotated["access_token"])
    with pytest.raises(ValueError, match="Invalid refresh token"):
        await uc.refresh_token(rotated["refresh_token"])


@pytest.mark.asyncio
async def test_reuse_is_not_accepted_when_revocation_cannot_be_stored():
    store = MemoryRefreshSessionStore()
    uc, _user_doc = _use_case(store=store)
    first = await uc.login("person@example.com", "password123")
    rotated = await uc.refresh_token(first["refresh_token"])
    old_jti = _decode(first["refresh_token"])["jti"]
    sid, _deadline = store.grace[old_jti]
    store.grace[old_jti] = (sid, time.monotonic() - 1)
    current_jti = store.sessions[sid]["current_jti"]

    async def revoke_fails(_sid):
        return False

    store.revoke = revoke_fails
    with pytest.raises(AuthUnavailable):
        await uc.refresh_token(first["refresh_token"])
    assert store.sessions[sid]["current_jti"] == current_jti
    assert _decode(rotated["refresh_token"])["jti"] == current_jti


@pytest.mark.asyncio
async def test_redis_store_fails_closed_when_connection_is_missing():
    store = RedisRefreshSessionStore()
    store._redis = AsyncMock(return_value=None)
    assert await store.session_state("sid", "user-1") == "unavailable"
    assert await store.revoke("sid") is False
    assert await store.save(
        jti="jti",
        sid="sid",
        user_id="user-1",
        refresh_ttl=60,
        session_ttl=60,
        meta={"epoch": 0},
    ) is False
    assert await store.rotate(
        jti="jti",
        sid="sid",
        user_id="user-1",
        refresh_ttl=60,
        session_ttl=60,
        meta={"epoch": 0},
    ) == "unavailable"


@pytest.mark.asyncio
async def test_redis_rotate_and_revoke_surface_store_results():
    store = RedisRefreshSessionStore()
    redis = MagicMock()
    redis.eval = AsyncMock(return_value="rejected")
    store._redis = AsyncMock(return_value=redis)

    assert await store.rotate(
        jti="jti",
        sid="sid",
        user_id="user-1",
        refresh_ttl=60,
        session_ttl=60,
        meta={"epoch": 0},
    ) == "rejected"
    script = redis.eval.await_args.args[0]
    assert redis.eval.await_args.args[4] == "auth:revoked:sid"
    assert "EXISTS" in script

    redis.eval = AsyncMock(side_effect=ConnectionError("down"))
    assert await store.revoke("sid") is False
