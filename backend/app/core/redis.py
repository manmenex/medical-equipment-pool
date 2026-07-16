import json
import logging
from typing import Any

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def cache_get(key: str) -> Any | None:
    if not settings.CACHE_ENABLED:
        return None
    try:
        client = get_redis()
        raw = await client.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("Redis cache_get failed for key=%s: %s: %s", key, type(exc).__name__, exc)
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    if not settings.CACHE_ENABLED:
        return
    try:
        client = get_redis()
        await client.set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except Exception as exc:
        logger.warning("Redis cache_set failed for key=%s: %s: %s", key, type(exc).__name__, exc)


async def store_refresh_token(jti: str, user_id: str, ttl_seconds: int) -> None:
    try:
        client = get_redis()
        await client.set(f"refresh:{jti}", user_id, ex=ttl_seconds)
    except Exception as exc:
        logger.warning("Redis store_refresh_token failed for jti=%s: %s: %s", jti, type(exc).__name__, exc)


async def is_refresh_token_valid(jti: str, user_id: str) -> bool:
    try:
        client = get_redis()
        stored = await client.get(f"refresh:{jti}")
        return stored == user_id
    except Exception as exc:
        # Redis unavailable: fail open on JWT validity alone rather than locking
        # every user out because the cache is down.
        logger.error(
            "Redis unavailable during refresh-token validation for jti=%s; failing open "
            "(treating token as valid): %s: %s",
            jti,
            type(exc).__name__,
            exc,
        )
        return True


async def revoke_refresh_token(jti: str) -> None:
    try:
        client = get_redis()
        await client.delete(f"refresh:{jti}")
    except Exception as exc:
        logger.warning("Redis revoke_refresh_token failed for jti=%s: %s: %s", jti, type(exc).__name__, exc)


async def cache_delete_prefix(prefix: str) -> None:
    if not settings.CACHE_ENABLED:
        return
    try:
        client = get_redis()
        async for key in client.scan_iter(match=f"{prefix}*"):
            await client.delete(key)
    except Exception as exc:
        logger.warning("Redis cache_delete_prefix failed for prefix=%s: %s: %s", prefix, type(exc).__name__, exc)
