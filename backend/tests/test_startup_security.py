import pytest

from app.core.config import (
    DEFAULT_JWT_SECRET_KEY,
    InsecureConfigurationError,
    Settings,
    validate_production_secrets,
)


def test_allows_non_production_with_default_secret():
    settings = Settings(ENVIRONMENT="development", JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY)
    validate_production_secrets(settings)


def test_rejects_production_with_default_secret():
    settings = Settings(ENVIRONMENT="production", JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY)
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


def test_rejects_production_with_missing_secret():
    settings = Settings(ENVIRONMENT="production", JWT_SECRET_KEY="")
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


def test_rejects_production_with_short_secret():
    settings = Settings(ENVIRONMENT="production", JWT_SECRET_KEY="too-short")
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


def test_allows_production_with_strong_unique_secret():
    settings = Settings(ENVIRONMENT="production", JWT_SECRET_KEY="a" * 64)
    validate_production_secrets(settings)
