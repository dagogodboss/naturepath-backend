"""Single-use guest-claim credentials bound to the verified account."""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Optional

logger = logging.getLogger(__name__)

CLAIM_PROOF_TTL_SEC = 1800


def hash_claim_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def claim_cache_key(email: str, token_hash: str) -> str:
    normalized = (email or "").strip().lower()
    return f"auth:claim:{normalized}:{token_hash}"


class MemoryClaimProofStore:
    """In-process store used by tests. pop() is the single-use transition."""

    def __init__(self):
        self.rows: dict[str, str] = {}

    async def issue(self, *, email: str, user_id: str, ttl: int = CLAIM_PROOF_TTL_SEC) -> Optional[str]:
        del ttl
        token = secrets.token_urlsafe(32)
        self.rows[claim_cache_key(email, hash_claim_token(token))] = user_id
        return token

    async def consume(self, *, email: str, token: str) -> Optional[str]:
        if not token:
            return None
        return self.rows.pop(claim_cache_key(email, hash_claim_token(token)), None)


class RedisClaimProofStore:
    """Redis-backed claim proofs. The credential is stored only as a hash."""

    async def issue(self, *, email: str, user_id: str, ttl: int = CLAIM_PROOF_TTL_SEC) -> Optional[str]:
        from infrastructure.cache import get_cache_service

        token = secrets.token_urlsafe(32)
        cache = await get_cache_service()
        stored = await cache.set(
            claim_cache_key(email, hash_claim_token(token)),
            {"user_id": user_id},
            ttl=ttl,
        )
        if not stored:
            return None
        return token

    async def consume(self, *, email: str, token: str) -> Optional[str]:
        if not token:
            return None
        from infrastructure.cache import get_cache_service

        cache = await get_cache_service()
        status, value = await cache.getdel_json(
            claim_cache_key(email, hash_claim_token(token))
        )
        if status != "ok" or not isinstance(value, dict):
            return None
        user_id = value.get("user_id")
        return str(user_id) if user_id else None
