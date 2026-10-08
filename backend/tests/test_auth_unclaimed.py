"""Unit tests for guest/OAuth claim helpers and phone-setup gating."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.claim_proof import MemoryClaimProofStore
from application.refresh_sessions import MemoryRefreshSessionStore
from application.use_cases.auth_use_case import (
    AuthUseCase,
    _is_unclaimed_account,
)


def test_oauth_claimed_is_not_unclaimed():
    assert _is_unclaimed_account({
        "auth_method": "oauth",
        "account_claimed": True,
        "password_hash": None,
    }) is False


def test_password_claimed_is_not_unclaimed():
    assert _is_unclaimed_account({
        "auth_method": "password",
        "account_claimed": True,
        "password_hash": "x",
    }) is False


def test_guest_purchase_is_unclaimed():
    assert _is_unclaimed_account({
        "auth_method": "guest_purchase",
        "account_claimed": False,
        "password_hash": None,
    }) is True


def test_account_claimed_false_is_unclaimed():
    assert _is_unclaimed_account({
        "auth_method": "guest_purchase",
        "account_claimed": False,
    }) is True


def test_missing_password_alone_is_not_unclaimed():
    """Regression: OAuth users have no password_hash but must not be claimable."""
    assert _is_unclaimed_account({
        "auth_method": "oauth",
        "account_claimed": True,
        "password_hash": None,
    }) is False
    assert _is_unclaimed_account({
        "account_claimed": True,
        "password_hash": None,
    }) is False


def test_legacy_guest_method_without_flag():
    assert _is_unclaimed_account({
        "auth_method": "guest_purchase",
    }) is True


def _guest():
    return {
        "user_id": "guest-1",
        "email": "guest@example.com",
        "role": "customer",
        "auth_method": "guest_purchase",
        "account_claimed": False,
        "password_hash": None,
        "phone": "5551234567",
        "first_name": "G",
        "last_name": "Uest",
        "session_epoch": 0,
    }


def _use_case(repo, claims=None):
    return AuthUseCase(
        repo,
        claim_store=claims or MemoryClaimProofStore(),
        session_store=MemoryRefreshSessionStore(),
    )


@pytest.mark.asyncio
async def test_register_claim_rejected_without_credential():
    """A shared email flag is not enough. The claim credential is required."""
    repo = MagicMock()
    repo.get_by_email = AsyncMock(return_value=_guest())
    repo.claim_if_unclaimed = AsyncMock()
    uc = _use_case(repo)

    with pytest.raises(ValueError, match="Verify your email before claiming"):
        await uc.register(
            email="guest@example.com",
            password="password123",
            first_name="G",
            last_name="Uest",
            phone="5551234567",
        )

    repo.claim_if_unclaimed.assert_not_called()


@pytest.mark.asyncio
async def test_register_claim_rejects_credential_for_a_different_account():
    guest = _guest()
    claims = MemoryClaimProofStore()
    other_token = await claims.issue(email="other@example.com", user_id="other-user")
    repo = MagicMock()
    repo.get_by_email = AsyncMock(return_value=guest)
    repo.claim_if_unclaimed = AsyncMock()
    uc = _use_case(repo, claims)

    with pytest.raises(ValueError, match="Verify your email before claiming"):
        await uc.register(
            email=guest["email"],
            password="password123",
            first_name="G",
            last_name="Uest",
            phone="5551234567",
            claim_token=other_token,
        )

    repo.claim_if_unclaimed.assert_not_called()
    mismatched = await claims.issue(email=guest["email"], user_id="someone-else")
    with pytest.raises(ValueError, match="Verify your email before claiming"):
        await uc.register(
            email=guest["email"],
            password="password123",
            first_name="G",
            last_name="Uest",
            phone="5551234567",
            claim_token=mismatched,
        )
    repo.claim_if_unclaimed.assert_not_called()


@pytest.mark.asyncio
async def test_register_claim_succeeds_once_with_bound_credential():
    guest = _guest()
    claimed = {
        **guest,
        "account_claimed": True,
        "auth_method": "password",
        "is_verified": True,
        "session_epoch": 1,
    }
    claims = MemoryClaimProofStore()
    token = await claims.issue(email=guest["email"], user_id=guest["user_id"])
    repo = MagicMock()
    repo.get_by_email = AsyncMock(return_value=guest)
    repo.claim_if_unclaimed = AsyncMock(return_value=claimed)
    uc = _use_case(repo, claims)

    with patch("application.use_cases.auth_use_case.send_welcome_email") as welcome:
        welcome.delay = MagicMock()
        result = await uc.register(
            email=guest["email"],
            password="password123",
            first_name="G",
            last_name="Uest",
            phone="5551234567",
            claim_token=token,
        )

    assert "access_token" in result
    assert "refresh_token" in result
    repo.claim_if_unclaimed.assert_awaited_once()
    update_payload = repo.claim_if_unclaimed.await_args.args[1]
    assert update_payload["account_claimed"] is True
    assert update_payload["is_verified"] is True
    assert update_payload["auth_method"] == "password"
    assert update_payload["session_epoch"] == 1

    with pytest.raises(ValueError, match="Verify your email before claiming"):
        await uc.register(
            email=guest["email"],
            password="password123",
            first_name="G",
            last_name="Uest",
            phone="5551234567",
            claim_token=token,
        )
    repo.claim_if_unclaimed.assert_awaited_once()


@pytest.mark.asyncio
async def test_claim_credential_is_single_use_and_email_bound():
    store = MemoryClaimProofStore()
    token = await store.issue(email="guest@example.com", user_id="guest-1")
    assert await store.consume(email="other@example.com", token=token) is None
    assert await store.consume(email="guest@example.com", token=token) == "guest-1"
    assert await store.consume(email="guest@example.com", token=token) is None
