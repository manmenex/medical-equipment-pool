import hashlib
import json
import logging
from typing import Any

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def _redact(value: str) -> str:
    """Log-safe representation of a potentially sensitive identifier.

    Cache keys and JTIs are not guaranteed to be free of sensitive content
    (a cache key may be built from user-supplied data), so this never
    includes any substring of the original value, regardless of its
    length — only a short SHA-256-derived correlation hash and the input's
    length, so repeated failures against the same key/jti can still be
    correlated across log lines without ever writing the identifier itself,
    even partially.
    """
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}(len={len(value)})"


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
        logger.warning("Redis cache_get failed key=%s: %s: %s", _redact(key), type(exc).__name__, exc)
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    if not settings.CACHE_ENABLED:
        return
    try:
        client = get_redis()
        await client.set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except Exception as exc:
        logger.warning("Redis cache_set failed key=%s: %s: %s", _redact(key), type(exc).__name__, exc)


async def store_refresh_token(jti: str, user_id: str, ttl_seconds: int) -> None:
    try:
        client = get_redis()
        await client.set(f"refresh:{jti}", user_id, ex=ttl_seconds)
    except Exception as exc:
        logger.warning("Redis store_refresh_token failed jti=%s: %s: %s", _redact(jti), type(exc).__name__, exc)


async def is_refresh_token_valid(jti: str, user_id: str) -> bool:
    try:
        client = get_redis()
        stored = await client.get(f"refresh:{jti}")
        return stored == user_id
    except Exception as exc:
        # Redis unavailable: fail open on JWT validity alone rather than locking
        # every user out because the cache is down.
        logger.error(
            "Redis unavailable during refresh-token validation jti=%s; failing open "
            "(treating token as valid): %s: %s",
            _redact(jti),
            type(exc).__name__,
            exc,
        )
        return True


async def revoke_refresh_token(jti: str) -> None:
    try:
        client = get_redis()
        await client.delete(f"refresh:{jti}")
    except Exception as exc:
        logger.warning("Redis revoke_refresh_token failed jti=%s: %s: %s", _redact(jti), type(exc).__name__, exc)


async def cache_delete_prefix(prefix: str) -> None:
    if not settings.CACHE_ENABLED:
        return
    try:
        client = get_redis()
        async for key in client.scan_iter(match=f"{prefix}*"):
            await client.delete(key)
    except Exception as exc:
        logger.warning(
            "Redis cache_delete_prefix failed prefix=%s: %s: %s", _redact(prefix), type(exc).__name__, exc
        )
