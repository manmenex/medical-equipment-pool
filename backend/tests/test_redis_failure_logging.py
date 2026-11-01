import logging

import pytest

from app.core import redis as redis_module

SENSITIVE_JTI = "super-secret-refresh-jti-marker-0123456789abcdef-should-never-leak"
SENSITIVE_KEY = "dashboard:summary:super-secret-user-data-marker-0123456789"
SENSITIVE_PREFIX = "user-search:super-secret-query-marker-0123456789"


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


def _all_log_text(caplog) -> str:
    return "\n".join(record.message for record in caplog.records)


async def test_cache_get_failure_is_logged_without_raising_or_leaking_key(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        result = await redis_module.cache_get(SENSITIVE_KEY)
    assert result is None
    text = _all_log_text(caplog)
    assert "cache_get" in text
    assert SENSITIVE_KEY not in text


async def test_cache_set_failure_is_logged_without_raising_or_leaking_key(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        await redis_module.cache_set(SENSITIVE_KEY, {"a": 1}, ttl_seconds=60)
    text = _all_log_text(caplog)
    assert "cache_set" in text
    assert SENSITIVE_KEY not in text


async def test_store_refresh_token_failure_is_logged_without_raising_or_leaking_jti(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        await redis_module.store_refresh_token(SENSITIVE_JTI, "user-1", ttl_seconds=60)
    text = _all_log_text(caplog)
    assert "store_refresh_token" in text
    assert SENSITIVE_JTI not in text


async def test_refresh_token_validation_fails_open_and_logs_error_without_leaking_jti(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        result = await redis_module.is_refresh_token_valid(SENSITIVE_JTI, "user-1")
    assert result is True
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "expected an ERROR-level log for the fail-open path"
    assert "fail" in error_records[0].message.lower()
    assert SENSITIVE_JTI not in _all_log_text(caplog)


async def test_revoke_refresh_token_failure_is_logged_without_raising_or_leaking_jti(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        await redis_module.revoke_refresh_token(SENSITIVE_JTI)
    text = _all_log_text(caplog)
    assert "revoke_refresh_token" in text
    assert SENSITIVE_JTI not in text


async def test_cache_delete_prefix_failure_is_logged_without_raising_or_leaking_prefix(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        await redis_module.cache_delete_prefix(SENSITIVE_PREFIX)
    text = _all_log_text(caplog)
    assert "cache_delete_prefix" in text
    assert SENSITIVE_PREFIX not in text


async def test_no_operation_ever_logs_full_secret_markers(caplog):
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        await redis_module.cache_get(SENSITIVE_KEY)
        await redis_module.cache_set(SENSITIVE_KEY, {"a": 1}, ttl_seconds=60)
        await redis_module.store_refresh_token(SENSITIVE_JTI, "user-1", ttl_seconds=60)
        await redis_module.is_refresh_token_valid(SENSITIVE_JTI, "user-1")
        await redis_module.revoke_refresh_token(SENSITIVE_JTI)
        await redis_module.cache_delete_prefix(SENSITIVE_PREFIX)

    text = _all_log_text(caplog)
    for marker in (SENSITIVE_JTI, SENSITIVE_KEY, SENSITIVE_PREFIX):
        assert marker not in text
    assert "JWT_SECRET" not in text
    assert "password" not in text.lower()


@pytest.mark.parametrize(
    # Deliberately uppercase-only / digit-free: the redacted output is a
    # fixed lowercase template ("sha256:...(len=N)") plus a lowercase hex
    # digest, so an uppercase input value can never coincidentally collide
    # with either part — a real substring match here can only mean the
    # implementation leaked the value itself.
    "value",
    ["Z", "ZQ", "ZQXWERT", "ZQXWERTY", "this-is-a-very-long-sensitive-identifier-marker-value"],
    ids=["one_char", "two_chars", "seven_chars", "exactly_eight_chars", "long_value"],
)
def test_redact_never_contains_the_complete_input_regardless_of_length(value):
    redacted = redis_module._redact(value)
    assert value not in redacted


def test_redact_of_empty_value_does_not_error_and_has_the_expected_shape():
    redacted = redis_module._redact("")
    assert redacted.startswith("sha256:")
    assert "len=0" in redacted


def test_redact_is_correlatable_across_repeated_calls_with_the_same_value():
    value = "repeat-me-please-1234567890"
    first = redis_module._redact(value)
    second = redis_module._redact(value)
    assert first == second


def test_redact_distinguishes_different_values():
    assert redis_module._redact("value-one") != redis_module._redact("value-two")


async def test_short_identifier_is_never_fully_present_in_captured_logs(caplog):
    # Uppercase-only so it cannot coincidentally collide with the lowercase
    # hex digest or the fixed "sha256:...(len=N)" template (see the
    # test_redact_never_contains_the_complete_input_regardless_of_length
    # comment above for the full reasoning).
    short_jti = "ZQX"
    with caplog.at_level(logging.WARNING, logger=redis_module.__name__):
        await redis_module.revoke_refresh_token(short_jti)
    text = _all_log_text(caplog)
    assert short_jti not in text
