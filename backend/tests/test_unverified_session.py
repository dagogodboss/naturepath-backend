"""Unverified password accounts must not receive a normal session."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.refresh_sessions import MemoryRefreshSessionStore
from application.use_cases.auth_use_case import AuthUseCase, allows_normal_session
from tests.test_auth_attempt_limits import DictCache
from tests.test_refresh_sessions import _use_case


def _repo_for_new_user():
    repo = MagicMock()
    repo.get_by_email = AsyncMock(return_value=None)
    repo.create = AsyncMock(side_effect=lambda doc: doc)
    return repo


@pytest.mark.asyncio
async def test_new_registration_does_not_return_a_session():
    repo = _repo_for_new_user()
    uc = AuthUseCase(repo, session_store=MemoryRefreshSessionStore())
    with patch("application.use_cases.auth_use_case.send_welcome_email") as welcome:
        welcome.delay = MagicMock()
        result = await uc.register(
            email="new@example.com",
            password="password123",
            first_name="New",
            last_name="User",
            phone="5551234567",
        )
    assert result["verification_required"] is True
    assert "access_token" not in result
    assert "refresh_token" not in result
    created = repo.create.await_args.args[0]
    assert created["is_verified"] is False


@pytest.mark.asyncio
async def test_unverified_login_and_refresh_do_not_issue_a_normal_session():
    user = {
        "user_id": "user-1",
        "email": "person@example.com",
        "role": "customer",
        "is_active": True,
        "is_verified": False,
        "phone": "5551234567",
        "session_epoch": 0,
    }
    uc, _doc = _use_case(user)
    with pytest.raises(ValueError, match="Verify your email"):
        await uc.login("person@example.com", "password123")

    user["is_verified"] = True
    issued = await uc.login("person@example.com", "password123")
    user["is_verified"] = False
    with pytest.raises(ValueError, match="Verify your email"):
        await uc.refresh_token(issued["refresh_token"])
    with pytest.raises(ValueError, match="Email verification required"):
        await uc.get_current_user(issued["access_token"])


@pytest.mark.asyncio
async def test_legacy_account_without_verification_flag_can_still_sign_in():
    user = {
        "user_id": "owner-1",
        "email": "owner@example.com",
        "role": "owner",
        "is_active": True,
        "phone": "5551234567",
        "session_epoch": 0,
    }
    assert allows_normal_session(user) is True
    uc, _doc = _use_case(user)
    result = await uc.login("owner@example.com", "password123")
    assert result["user"]["role"] == "owner"
    assert result["access_token"]


@pytest.mark.asyncio
async def test_verified_login_still_returns_a_session():
    uc, _doc = _use_case()
    result = await uc.login("person@example.com", "password123")
    assert result["access_token"]
    assert result["refresh_token"]
    profile = await uc.get_current_user(result["access_token"])
    assert profile["email"] == "person@example.com"
    assert "password_hash" not in profile
