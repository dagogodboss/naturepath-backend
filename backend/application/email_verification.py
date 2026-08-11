"""Durable, one-time email verification challenges."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


class EmailVerificationStore:
    """Store hashed OTPs in Mongo so emailed codes survive Redis/process issues."""

    def __init__(self, collection: Any, *, secret: str, ttl_seconds: int = 600):
        self.collection = collection
        self.secret = secret.encode("utf-8")
        self.ttl_seconds = ttl_seconds

    def _hash(self, email: str, code: str) -> str:
        message = f"{normalize_email(email)}:{code}".encode("utf-8")
        return hmac.new(self.secret, message, hashlib.sha256).hexdigest()

    async def issue(
        self,
        email: str,
        code: str,
        *,
        now: datetime | None = None,
    ) -> None:
        issued_at = now or datetime.now(timezone.utc)
        normalized = normalize_email(email)
        await self.collection.update_one(
            {"email": normalized},
            {
                "$set": {
                    "email": normalized,
                    "code_hash": self._hash(normalized, str(code)),
                    "issued_at": issued_at,
                    "expires_at": issued_at + timedelta(seconds=self.ttl_seconds),
                }
            },
            upsert=True,
        )

    async def consume(
        self,
        email: str,
        code: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(timezone.utc)
        normalized = normalize_email(email)
        challenge = await self.collection.find_one({"email": normalized})
        if not challenge:
            return False
        expires_at = challenge.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if not isinstance(expires_at, datetime) or expires_at <= current:
            await self.collection.delete_one({"email": normalized})
            return False
        expected = str(challenge.get("code_hash") or "")
        supplied = self._hash(normalized, str(code))
        if not hmac.compare_digest(expected, supplied):
            return False
        # Match-and-delete makes successful verification one-time even when two
        # requests race with the same valid code.
        consumed = await self.collection.find_one_and_delete(
            {"email": normalized, "code_hash": expected}
        )
        return consumed is not None

    async def revoke(self, email: str) -> None:
        await self.collection.delete_one({"email": normalize_email(email)})
