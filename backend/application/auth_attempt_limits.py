"""Server-side budgets for credential attempts.

Account and challenge budgets stay in effect when the client address changes.
Address budgets are a secondary dampener and use the same direct client host as
the existing OTP send limiter. They do not replace the account budget.
"""

from __future__ import annotations

LOGIN_EMAIL_LIMIT = 10
LOGIN_EMAIL_WINDOW_SEC = 15 * 60
LOGIN_IP_LIMIT = 50
LOGIN_IP_WINDOW_SEC = 15 * 60
OTP_VERIFY_EMAIL_LIMIT = 10
OTP_VERIFY_EMAIL_WINDOW_SEC = 30 * 60
OTP_VERIFY_IP_LIMIT = 40
OTP_VERIFY_IP_WINDOW_SEC = 15 * 60
OTP_SEND_EMAIL_LIMIT = 5
OTP_SEND_EMAIL_WINDOW_SEC = 15 * 60


class AttemptLimited(Exception):
    """The account or client has exhausted an attempt budget."""


class AttemptLimiter:
    def __init__(self, cache):
        self.cache = cache

    async def _count(self, key: str) -> int:
        raw = await self.cache.get(key)
        if raw is None or isinstance(raw, bool):
            return int(raw or 0)
        if isinstance(raw, (int, float)):
            return int(raw)
        if isinstance(raw, str):
            try:
                return int(raw)
            except ValueError:
                return 0
        return 0

    async def _assert_under(self, key: str, limit: int) -> None:
        if await self._count(key) >= limit:
            raise AttemptLimited("Too many attempts. Please try again later.")

    async def assert_login_allowed(self, email: str, client_ip: str) -> None:
        await self._assert_under(f"auth:login_fail:email:{email}", LOGIN_EMAIL_LIMIT)
        await self._assert_under(f"auth:login_fail:ip:{client_ip}", LOGIN_IP_LIMIT)

    async def record_login_failure(self, email: str, client_ip: str) -> None:
        await self.cache.incr(
            f"auth:login_fail:email:{email}", ttl=LOGIN_EMAIL_WINDOW_SEC
        )
        await self.cache.incr(
            f"auth:login_fail:ip:{client_ip}", ttl=LOGIN_IP_WINDOW_SEC
        )

    async def clear_login_failures(self, email: str) -> None:
        await self.cache.delete(f"auth:login_fail:email:{email}")

    async def assert_otp_verify_allowed(self, email: str, client_ip: str) -> None:
        await self._assert_under(
            f"auth:otp_fail:email:{email}", OTP_VERIFY_EMAIL_LIMIT
        )
        await self._assert_under(f"auth:otp_fail:ip:{client_ip}", OTP_VERIFY_IP_LIMIT)

    async def record_otp_verify_failure(self, email: str, client_ip: str) -> None:
        await self.cache.incr(
            f"auth:otp_fail:email:{email}", ttl=OTP_VERIFY_EMAIL_WINDOW_SEC
        )
        await self.cache.incr(
            f"auth:otp_fail:ip:{client_ip}", ttl=OTP_VERIFY_IP_WINDOW_SEC
        )

    async def clear_otp_verify_failures(self, email: str) -> None:
        await self.cache.delete(f"auth:otp_fail:email:{email}")

    async def reserve_otp_send(self, email: str) -> bool:
        """Return False when this email has used its resend budget.

        A replacement challenge gets a fresh per-code guess budget. This
        counter is not cleared by resending or by a different client address.
        """
        count = await self.cache.incr(
            f"auth:otp_send:email:{email}", ttl=OTP_SEND_EMAIL_WINDOW_SEC
        )
        return int(count) <= OTP_SEND_EMAIL_LIMIT
