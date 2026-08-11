"""Unit tests for guest/OAuth claim helpers and phone-setup gating."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.use_cases.auth_use_case import (
    AuthUseCase,
    _is_unclaimed_account,
    email_claim_ok_key,
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


def test_email_claim_ok_key_normalizes():
    assert email_claim_ok_key("  Guest@Example.COM ") == "auth:claim_ok:guest@example.com"


@pytest.mark.asyncio
async def test_register_claim_rejected_without_otp_proof():
    """Guest takeover must not succeed on password alone — OTP claim proof required."""
    guest = {
        "user_id": "guest-1",
        "email": "guest@example.com",
        "role": "customer",
        "auth_method": "guest_purchase",
        "account_claimed": False,
        "password_hash": None,
        "phone": "5551234567",
    }
    repo = MagicMock()
    repo.get_by_email = AsyncMock(return_value=guest)
    repo.update = AsyncMock()
    uc = AuthUseCase(repo)

    with patch.object(uc, "_consume_email_claim_proof", AsyncMock(return_value=False)):
        with pytest.raises(ValueError, match="Verify your email before claiming"):
            await uc.register(
                email="guest@example.com",
                password="password123",
                first_name="G",
                last_name="Uest",
                phone="5551234567",
            )

    repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_register_claim_succeeds_with_otp_proof():
    guest = {
        "user_id": "guest-1",
        "email": "guest@example.com",
        "role": "customer",
        "auth_method": "guest_purchase",
        "account_claimed": False,
        "password_hash": None,
        "phone": "5551234567",
        "first_name": "G",
        "last_name": "Uest",
    }
    claimed = {**guest, "account_claimed": True, "auth_method": "password", "is_verified": True}
    repo = MagicMock()
    repo.get_by_email = AsyncMock(return_value=guest)
    repo.update = AsyncMock(return_value=claimed)
    uc = AuthUseCase(repo)

    with patch.object(uc, "_consume_email_claim_proof", AsyncMock(return_value=True)):
        with patch("application.use_cases.auth_use_case.send_welcome_email") as welcome:
            welcome.delay = MagicMock()
            result = await uc.register(
                email="guest@example.com",
                password="password123",
                first_name="G",
                last_name="Uest",
                phone="5551234567",
            )

    assert "access_token" in result
    repo.update.assert_awaited_once()
    update_payload = repo.update.await_args.args[1]
    assert update_payload["account_claimed"] is True
    assert update_payload["is_verified"] is True
    assert update_payload["auth_method"] == "password"


@pytest.mark.asyncio
async def test_consume_email_claim_proof_reads_and_deletes_cache():
    repo = MagicMock()
    uc = AuthUseCase(repo)
    cache = MagicMock()
    cache.get = AsyncMock(return_value={"verified": True})
    cache.delete = AsyncMock()

    with patch(
        "infrastructure.cache.get_cache_service",
        AsyncMock(return_value=cache),
    ):
        ok = await uc._consume_email_claim_proof("Guest@Example.com")

    assert ok is True
    cache.get.assert_awaited_once_with("auth:claim_ok:guest@example.com")
    cache.delete.assert_awaited_once_with("auth:claim_ok:guest@example.com")


@pytest.mark.asyncio
async def test_consume_email_claim_proof_missing():
    repo = MagicMock()
    uc = AuthUseCase(repo)
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.delete = AsyncMock()

    with patch(
        "infrastructure.cache.get_cache_service",
        AsyncMock(return_value=cache),
    ):
        ok = await uc._consume_email_claim_proof("nobody@example.com")

    assert ok is False
    cache.delete.assert_not_called()
