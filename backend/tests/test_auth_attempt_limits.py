"""Server-side login and OTP attempt budgets."""

import pytest

from application.auth_attempt_limits import (
    LOGIN_EMAIL_LIMIT,
    OTP_SEND_EMAIL_LIMIT,
    OTP_VERIFY_EMAIL_LIMIT,
    AttemptLimited,
    AttemptLimiter,
)


class DictCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def incr(self, key, ttl=60):
        self.store[key] = int(self.store.get(key) or 0) + 1
        return self.store[key]

    async def delete(self, key):
        self.store.pop(key, None)
        return True


@pytest.mark.asyncio
async def test_login_email_budget_survives_client_address_changes():
    limiter = AttemptLimiter(DictCache())
    email = "person@example.com"
    for _ in range(LOGIN_EMAIL_LIMIT):
        await limiter.record_login_failure(email, "10.0.0.1")

    with pytest.raises(AttemptLimited):
        await limiter.assert_login_allowed(email, "10.9.9.9")

    await limiter.clear_login_failures(email)
    await limiter.assert_login_allowed(email, "10.9.9.9")


@pytest.mark.asyncio
async def test_otp_verify_budget_is_per_account_not_per_address():
    limiter = AttemptLimiter(DictCache())
    email = "person@example.com"
    for index in range(OTP_VERIFY_EMAIL_LIMIT):
        await limiter.record_otp_verify_failure(email, f"10.0.0.{index}")

    with pytest.raises(AttemptLimited):
        await limiter.assert_otp_verify_allowed(email, "192.0.2.40")


@pytest.mark.asyncio
async def test_otp_resend_budget_is_not_reset_for_a_new_address():
    limiter = AttemptLimiter(DictCache())
    email = "person@example.com"
    for _ in range(OTP_SEND_EMAIL_LIMIT):
        assert await limiter.reserve_otp_send(email) is True
    assert await limiter.reserve_otp_send(email) is False
