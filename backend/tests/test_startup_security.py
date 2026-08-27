import pytest
from pydantic import ValidationError

from app.core.config import (
    DEFAULT_ALLOWED_ORIGINS,
    DEFAULT_DATABASE_URL,
    DEFAULT_JWT_SECRET_KEY,
    InsecureConfigurationError,
    Settings,
    validate_production_secrets,
)

# PR24B (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §14): every
# "production is otherwise valid" test below must now also supply a
# non-default DATABASE_URL and ALLOWED_ORIGINS, since validate_production_
# secrets fails closed on those too -- a bare ENVIRONMENT=production with
# only JWT_SECRET_KEY overridden would trip the new checks below it.
_NON_DEFAULT_DATABASE_URL = "postgresql+asyncpg://real_user:real_password@prod-db-host:5432/mep_prod"
_NON_DEFAULT_ALLOWED_ORIGINS = "https://mep.hospital.example"


def test_allows_development_with_documented_local_default():
    settings = Settings(ENVIRONMENT="development", JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY)
    validate_production_secrets(settings)


def test_rejects_production_with_default_secret():
    settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY,
        DATABASE_URL=_NON_DEFAULT_DATABASE_URL,
        ALLOWED_ORIGINS=_NON_DEFAULT_ALLOWED_ORIGINS,
    )
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


def test_rejects_production_with_missing_secret():
    settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="",
        DATABASE_URL=_NON_DEFAULT_DATABASE_URL,
        ALLOWED_ORIGINS=_NON_DEFAULT_ALLOWED_ORIGINS,
    )
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


def test_rejects_production_with_short_secret():
    settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="too-short",
        DATABASE_URL=_NON_DEFAULT_DATABASE_URL,
        ALLOWED_ORIGINS=_NON_DEFAULT_ALLOWED_ORIGINS,
    )
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


def test_allows_production_with_strong_non_default_secret():
    settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 64,
        DATABASE_URL=_NON_DEFAULT_DATABASE_URL,
        ALLOWED_ORIGINS=_NON_DEFAULT_ALLOWED_ORIGINS,
    )
    validate_production_secrets(settings)


@pytest.mark.parametrize("environment_value", ["production", "Production", "PRODUCTION", "  production  "])
def test_production_secret_validation_is_case_and_whitespace_insensitive(environment_value):
    settings = Settings(
        ENVIRONMENT=environment_value,
        JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY,
        DATABASE_URL=_NON_DEFAULT_DATABASE_URL,
        ALLOWED_ORIGINS=_NON_DEFAULT_ALLOWED_ORIGINS,
    )
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


@pytest.mark.parametrize("environment_value", ["production", "Production", "PRODUCTION", "  production  "])
def test_strong_secret_is_accepted_regardless_of_environment_casing(environment_value):
    settings = Settings(
        ENVIRONMENT=environment_value,
        JWT_SECRET_KEY="a" * 64,
        DATABASE_URL=_NON_DEFAULT_DATABASE_URL,
        ALLOWED_ORIGINS=_NON_DEFAULT_ALLOWED_ORIGINS,
    )
    validate_production_secrets(settings)


# ---------------------------------------------------------------------------
# PR24B (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §14): the
# same fail-closed-on-shipped-default pattern as JWT_SECRET_KEY above,
# applied to DATABASE_URL and ALLOWED_ORIGINS.
# ---------------------------------------------------------------------------


def test_rejects_production_with_default_database_url():
    settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 64,
        DATABASE_URL=DEFAULT_DATABASE_URL,
        ALLOWED_ORIGINS=_NON_DEFAULT_ALLOWED_ORIGINS,
    )
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


def test_rejects_production_with_default_allowed_origins():
    settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 64,
        DATABASE_URL=_NON_DEFAULT_DATABASE_URL,
        ALLOWED_ORIGINS=DEFAULT_ALLOWED_ORIGINS,
    )
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)


def test_allows_development_with_default_database_url_and_origins():
    # The new DATABASE_URL/ALLOWED_ORIGINS checks below are gated on
    # ENVIRONMENT=production the same way the JWT_SECRET_KEY check
    # already is -- explicit here (rather than relying on Settings()'s
    # own environment-derived default) so this test's intent survives
    # regardless of what DATABASE_URL/CACHE_ENABLED tests/conftest.py
    # sets in the process environment.
    settings = Settings(
        ENVIRONMENT="development",
        JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY,
        DATABASE_URL=DEFAULT_DATABASE_URL,
        ALLOWED_ORIGINS=DEFAULT_ALLOWED_ORIGINS,
    )
    validate_production_secrets(settings)


# ---------------------------------------------------------------------------
# PR19A3 review fix round 1 (H2): fail-fast validation of every
# safety-critical PR19 lease/claim/retention timing setting, at
# `Settings()` construction (application startup), never deferred to the
# first request that touches it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    [
        "IMPORT_JOB_LEASE_DURATION_SECONDS",
        "IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS",
        "IMPORT_RETENTION_DAYS",
        "IMPORT_RETENTION_CLEANUP_CLAIM_TIMEOUT_SECONDS",
    ],
)
@pytest.mark.parametrize("bad_value", [0, -1, -180])
def test_non_positive_import_timing_settings_are_rejected(field_name, bad_value):
    with pytest.raises(ValidationError):
        Settings(**{field_name: bad_value})


def test_default_import_timing_settings_are_accepted():
    settings = Settings()
    assert settings.IMPORT_JOB_LEASE_DURATION_SECONDS == 300
    assert settings.IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS == 60
    assert settings.IMPORT_RETENTION_DAYS == 180
    assert settings.IMPORT_RETENTION_CLEANUP_CLAIM_TIMEOUT_SECONDS == 300


def test_heartbeat_equal_to_lease_duration_is_rejected():
    with pytest.raises(ValidationError):
        Settings(IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS=300, IMPORT_JOB_LEASE_DURATION_SECONDS=300)


def test_heartbeat_greater_than_lease_duration_is_rejected():
    with pytest.raises(ValidationError):
        Settings(IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS=400, IMPORT_JOB_LEASE_DURATION_SECONDS=300)


def test_heartbeat_strictly_less_than_lease_duration_is_accepted():
    settings = Settings(IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS=100, IMPORT_JOB_LEASE_DURATION_SECONDS=300)
    assert settings.IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS == 100


def test_unrecognized_environment_value_fails_clearly_instead_of_defaulting_to_development():
    settings = Settings(ENVIRONMENT="staging", JWT_SECRET_KEY="a" * 64)
    with pytest.raises(InsecureConfigurationError):
        validate_production_secrets(settings)
