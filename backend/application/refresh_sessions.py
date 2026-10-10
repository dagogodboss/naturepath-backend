"""Server-side refresh sessions.

Refresh credentials are one-time. Presenting a credential again after the
short grace window revokes that session. Logout records a revocation marker
and deletes the session so a later refresh cannot recreate it. Reading or
writing revocation state fails closed when the store is unavailable.
Absolute session expiry is fixed when the session is created and is not
extended on refresh.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

GRACE_SECONDS = 15
# Longer than the longest issued session so a stale refresh cannot outlive revocation.
REVOCATION_TTL_SECONDS = 91 * 24 * 60 * 60


def legacy_refresh_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


class MemoryRefreshSessionStore:
    def __init__(self):
        self.available = True
        self.refresh: dict[str, dict[str, str]] = {}
        self.grace: dict[str, tuple[str, float]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.revoked: set[str] = set()
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
        if not self.available or sid in self.revoked:
            return False
        self.refresh[jti] = {"sid": sid, "user_id": user_id}
        self.sessions[sid] = {**meta, "user_id": user_id, "current_jti": jti}
        return True

    async def rotate(
        self,
        *,
        jti: str,
        sid: str,
        user_id: str,
        refresh_ttl: int,
        session_ttl: int,
        meta: dict[str, Any],
    ) -> str:
        """Commit a replacement credential only while this session is still active."""
        del refresh_ttl, session_ttl
        if not self.available:
            return "unavailable"
        row = self.sessions.get(sid)
        if sid in self.revoked or not row or row.get("user_id") != user_id:
            return "rejected"
        if int(row.get("epoch") or 0) != int(meta.get("epoch") or 0):
            return "rejected"
        previous = row.get("current_jti")
        if previous and previous != jti:
            self.refresh.pop(previous, None)
        self.refresh[jti] = {"sid": sid, "user_id": user_id}
        self.sessions[sid] = {**meta, "user_id": user_id, "current_jti": jti}
        return "stored"

    async def consume(self, jti: str) -> str:
        if not self.available:
            return "unavailable"
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
        if sid in self.revoked:
            return "revoked"
        row = self.sessions.get(sid)
        if not row or row.get("user_id") != user_id:
            return "revoked"
        return "active"

    async def revoke(self, sid: str) -> bool:
        if not self.available:
            return False
        self.revoked.add(sid)
        row = self.sessions.pop(sid, None)
        if row and row.get("current_jti"):
            self.refresh.pop(row["current_jti"], None)
        return True

    async def consume_legacy(self, token_hash: str) -> Optional[bool]:
        """True on first presentation, False on reuse, None if unavailable."""
        if not self.available:
            return None
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
            if await self._revoked(redis, sid):
                return False
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

    async def rotate(
        self,
        *,
        jti: str,
        sid: str,
        user_id: str,
        refresh_ttl: int,
        session_ttl: int,
        meta: dict[str, Any],
    ) -> str:
        """Atomically replace a session only when it is still active and unrevoked."""
        redis = await self._redis()
        if redis is None:
            return "unavailable"
        script = """
        if redis.call('EXISTS', KEYS[3]) == 1 then
          return 'rejected'
        end
        local raw = redis.call('GET', KEYS[1])
        if not raw then
          return 'rejected'
        end
        local ok, row = pcall(cjson.decode, raw)
        if not ok or type(row) ~= 'table' then
          return 'rejected'
        end
        if tostring(row['user_id'] or '') ~= ARGV[1] then
          return 'rejected'
        end
        if tonumber(row['epoch'] or 0) ~= tonumber(ARGV[2]) then
          return 'rejected'
        end
        if row['current_jti'] then
          redis.call('DEL', 'auth:rt:' .. row['current_jti'])
        end
        redis.call('SET', KEYS[2], ARGV[3], 'EX', tonumber(ARGV[4]))
        redis.call('SET', KEYS[1], ARGV[5], 'EX', tonumber(ARGV[6]))
        return 'stored'
        """
        try:
            result = await redis.eval(
                script,
                3,
                f"auth:sess:{sid}",
                f"auth:rt:{jti}",
                f"auth:revoked:{sid}",
                user_id,
                str(int(meta.get("epoch") or 0)),
                json.dumps({"sid": sid, "user_id": user_id}),
                str(max(1, int(refresh_ttl))),
                json.dumps({**meta, "user_id": user_id, "current_jti": jti}),
                str(max(1, int(session_ttl))),
            )
        except Exception:
            logger.exception("Unable to rotate refresh session")
            return "unavailable"
        text = result.decode() if isinstance(result, bytes) else str(result)
        if text in {"stored", "rejected"}:
            return text
        return "unavailable"

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

    async def _revoked(self, redis, sid: str) -> bool:
        try:
            return bool(await redis.exists(f"auth:revoked:{sid}"))
        except Exception:
            logger.exception("Unable to read refresh revocation")
            raise

    async def session_state(self, sid: str, user_id: str) -> str:
        redis = await self._redis()
        if redis is None:
            return "unavailable"
        try:
            if await self._revoked(redis, sid):
                return "revoked"
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

    async def revoke(self, sid: str) -> bool:
        redis = await self._redis()
        if redis is None:
            return False
        script = """
        local raw = redis.call('GET', KEYS[1])
        if raw then
          local ok, row = pcall(cjson.decode, raw)
          if ok and type(row) == 'table' and row['current_jti'] then
            redis.call('DEL', 'auth:rt:' .. row['current_jti'])
          end
        end
        redis.call('SET', KEYS[2], '1', 'EX', tonumber(ARGV[1]))
        redis.call('DEL', KEYS[1])
        return 1
        """
        try:
            await redis.eval(
                script,
                2,
                f"auth:sess:{sid}",
                f"auth:revoked:{sid}",
                str(REVOCATION_TTL_SECONDS),
            )
            return True
        except Exception:
            logger.exception("Unable to revoke refresh session")
            return False

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
