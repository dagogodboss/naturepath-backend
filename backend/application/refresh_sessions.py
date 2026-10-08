"""Server-side refresh sessions.

Refresh credentials are one-time. Presenting a credential again after the
short grace window revokes that session. Logout deletes the session record
so later access tokens for it are rejected. Absolute session expiry is fixed
when the session is created and is not extended on refresh.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

GRACE_SECONDS = 15


def legacy_refresh_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


class MemoryRefreshSessionStore:
    def __init__(self):
        self.available = True
        self.refresh: dict[str, dict[str, str]] = {}
        self.grace: dict[str, tuple[str, float]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.legacy: set[str] = set()

    async def save(
        self,
        *,
        jti: str,
        sid: str,
        user_id: str,
        refresh_ttl: int,
        session_ttl: int,
        meta: dict[str, Any],
    ) -> bool:
        del refresh_ttl, session_ttl
        self.refresh[jti] = {"sid": sid, "user_id": user_id}
        self.sessions[sid] = {**meta, "user_id": user_id, "current_jti": jti}
        return True

    async def consume(self, jti: str) -> str:
        row = self.refresh.pop(jti, None)
        now = time.monotonic()
        if row:
            self.grace[jti] = (row["sid"], now + GRACE_SECONDS)
            return "consumed"
        grace = self.grace.get(jti)
        if grace and grace[1] > now:
            return "grace"
        return "reuse"

    async def session_state(self, sid: str, user_id: str) -> str:
        if not self.available:
            return "unavailable"
        row = self.sessions.get(sid)
        if not row or row.get("user_id") != user_id:
            return "revoked"
        return "active"

    async def revoke(self, sid: str) -> None:
        row = self.sessions.pop(sid, None)
        if row and row.get("current_jti"):
            self.refresh.pop(row["current_jti"], None)

    async def consume_legacy(self, token_hash: str) -> Optional[bool]:
        """True on first presentation, False on reuse, None if unavailable."""
        if token_hash in self.legacy:
            return False
        self.legacy.add(token_hash)
        return True


class RedisRefreshSessionStore:
    async def _redis(self):
        from infrastructure.cache import get_cache_service

        cache = await get_cache_service()
        return cache.redis

    async def save(
        self,
        *,
        jti: str,
        sid: str,
        user_id: str,
        refresh_ttl: int,
        session_ttl: int,
        meta: dict[str, Any],
    ) -> bool:
        redis = await self._redis()
        if redis is None:
            return False
        try:
            body = json.dumps({**meta, "user_id": user_id, "current_jti": jti})
            pipe = redis.pipeline()
            pipe.set(
                f"auth:rt:{jti}",
                json.dumps({"sid": sid, "user_id": user_id}),
                ex=max(1, int(refresh_ttl)),
            )
            pipe.set(f"auth:sess:{sid}", body, ex=max(1, int(session_ttl)))
            await pipe.execute()
            return True
        except Exception:
            logger.exception("Unable to store refresh session")
            return False

    async def consume(self, jti: str) -> str:
        redis = await self._redis()
        if redis is None:
            return "unavailable"
        script = """
        local current = redis.call('GET', KEYS[1])
        if current then
          redis.call('DEL', KEYS[1])
          redis.call('SET', KEYS[2], current, 'EX', tonumber(ARGV[1]))
          return 'consumed'
        end
        if redis.call('GET', KEYS[2]) then
          return 'grace'
        end
        return 'reuse'
        """
        try:
            result = await redis.eval(
                script,
                2,
                f"auth:rt:{jti}",
                f"auth:rtgrace:{jti}",
                str(GRACE_SECONDS),
            )
            return str(result)
        except Exception:
            logger.exception("Unable to consume refresh credential")
            return "unavailable"

    async def session_state(self, sid: str, user_id: str) -> str:
        redis = await self._redis()
        if redis is None:
            return "unavailable"
        try:
            raw = await redis.get(f"auth:sess:{sid}")
        except Exception:
            logger.exception("Unable to read refresh session")
            return "unavailable"
        if not raw:
            return "revoked"
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            return "revoked"
        if row.get("user_id") != user_id:
            return "revoked"
        return "active"

    async def revoke(self, sid: str) -> None:
        redis = await self._redis()
        if redis is None:
            return
        try:
            raw = await redis.get(f"auth:sess:{sid}")
            if raw:
                row = json.loads(raw)
                current = row.get("current_jti")
                if current:
                    await redis.delete(f"auth:rt:{current}")
            await redis.delete(f"auth:sess:{sid}")
        except Exception:
            logger.exception("Unable to revoke refresh session")

    async def consume_legacy(self, token_hash: str) -> Optional[bool]:
        redis = await self._redis()
        if redis is None:
            return None
        try:
            created = await redis.set(
                f"auth:rtlegacy:{token_hash}",
                "1",
                ex=60 * 60 * 24 * 120,
                nx=True,
            )
            return bool(created)
        except Exception:
            logger.exception("Unable to record legacy refresh use")
            return None
