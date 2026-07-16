import logging

import pytest

from app.core import redis as redis_module

pytestmark = pytest.mark.asyncio


class BrokenRedisClient:
    async def get(self, *_args, **_kwargs):
        raise ConnectionError("redis unavailable")

    async def set(self, *_args, **_kwargs):
        raise ConnectionError("redis unavailable")

    async def delete(self, *_args, **_kwargs):
        raise ConnectionError("redis unavailable")

    def scan_iter(self, *_args, **_kwargs):
        raise ConnectionError("redis unavailable")


@pytest.fixture(autouse=True)
def broken_redis(monkeypatch):
    monkeypatch.setattr(redis_module, "get_redis", lambda: BrokenRedisClient())
    monkeypatch.setattr(redis_module.settings, "CACHE_ENABLED", True)


async def test_cache_get_failure_is_logged_and_does_not_raise(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        result = await redis_module.cache_get("some-key")
    assert result is None
    assert any("cache_get" in r.message for r in caplog.records)


async def test_cache_set_failure_is_logged_and_does_not_raise(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        await redis_module.cache_set("some-key", {"a": 1}, ttl_seconds=60)
    assert any("cache_set" in r.message for r in caplog.records)


async def test_refresh_token_validation_fails_open_and_logs_error(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        result = await redis_module.is_refresh_token_valid("some-jti", "user-1")
    assert result is True
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "expected an ERROR-level log for the fail-open path"
    assert "fail" in error_records[0].message.lower()


async def test_logged_messages_never_contain_secrets(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        await redis_module.is_refresh_token_valid("some-jti", "user-1")
        await redis_module.cache_get("some-key")

    for record in caplog.records:
        assert "JWT_SECRET" not in record.message
        assert "password" not in record.message.lower()
