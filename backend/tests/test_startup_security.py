import pytest

from app.core.config import (
    DEFAULT_JWT_SECRET_KEY,
    InsecureConfigurationError,
    Settings,
    validate_production_secrets,
)


def test_allows_development_with_documented_local_default():
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


def test_allows_production_with_strong_non_default_secret():
    settings = Settings(ENVIRONMENT="production", JWT_SECRET_KEY="a" * 64)
    validate_production_secrets(settings)


@pytest.mark.parametrize("environment_value", ["production", "Production", "PRODUCTION", "  production  "])
def test_production_secret_validation_is_case_and_whitespace_insensitive(environment_value):
    settings = Settings(ENVIRONMENT=environment_value, JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY)
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


@pytest.mark.parametrize("environment_value", ["production", "Production", "PRODUCTION", "  production  "])
def test_strong_secret_is_accepted_regardless_of_environment_casing(environment_value):
    settings = Settings(ENVIRONMENT=environment_value, JWT_SECRET_KEY="a" * 64)
    validate_production_secrets(settings)


def test_unrecognized_environment_value_fails_clearly_instead_of_defaulting_to_development():
    settings = Settings(ENVIRONMENT="staging", JWT_SECRET_KEY="a" * 64)
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)
