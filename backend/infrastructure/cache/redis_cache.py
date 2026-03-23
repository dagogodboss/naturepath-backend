"""
Redis Cache Service - Infrastructure Layer
"""
import json
import logging
from typing import Optional, Any
import redis.asyncio as redis
from core.config import settings

logger = logging.getLogger(__name__)


class CacheService:
    """Redis-based caching service"""
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
    
    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("Connected to Redis cache")
        except Exception as e:
            logger.warning(f"Redis not available, caching disabled: {e}")
            self.redis = None
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis:
            await self.redis.close()
            logger.info("Disconnected from Redis")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self.redis:
            return None
        try:
            value = await self.redis.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set value in cache with TTL (default 5 minutes)"""
        if not self.redis:
            return False
        try:
            await self.redis.set(key, json.dumps(value, default=str), ex=ttl)
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        if not self.redis:
            return False
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not self.redis:
            return 0
        try:
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                return await self.redis.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Cache delete pattern error: {e}")
            return 0
    
    # Cache key generators
    @staticmethod
    def services_key() -> str:
        return "cache:services:all"
    
    @staticmethod
    def featured_services_key() -> str:
        return "cache:services:featured"
    
    @staticmethod
    def practitioners_key() -> str:
        return "cache:practitioners:all"
    
    @staticmethod
    def featured_practitioners_key() -> str:
        return "cache:practitioners:featured"
    
    @staticmethod
    def practitioner_key(practitioner_id: str) -> str:
        return f"cache:practitioner:{practitioner_id}"
    
    @staticmethod
    def service_key(service_id: str) -> str:
        return f"cache:service:{service_id}"
    
    @staticmethod
    def availability_key(practitioner_id: str, date: str) -> str:
        return f"cache:availability:{practitioner_id}:{date}"


# Singleton instance
_cache_service: Optional[CacheService] = None


async def get_cache_service() -> CacheService:
    """Get cache service singleton"""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
        await _cache_service.connect()
    return _cache_service
