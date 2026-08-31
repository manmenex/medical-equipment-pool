import pytest
from fastapi import Response

from app.api.v1 import auth as auth_module
from app.core.config import Settings


@pytest.mark.parametrize(
    "environment_value", ["production", "Production", "PRODUCTION", "  production  ", "\tproduction\n"]
)
def test_settings_canonicalizes_every_spelling_of_production(environment_value):
    settings = Settings(ENVIRONMENT=environment_value)
    assert settings.ENVIRONMENT == "production"


@pytest.mark.parametrize(
    "environment_value", ["development", "Development", "DEVELOPMENT", "  development  "]
)
def test_settings_canonicalizes_every_spelling_of_development(environment_value):
    settings = Settings(ENVIRONMENT=environment_value)
    assert settings.ENVIRONMENT == "development"


@pytest.mark.parametrize("environment_value", ["production", "Production", "PRODUCTION", "  production  "])
def test_refresh_cookie_is_secure_for_every_accepted_spelling_of_production(monkeypatch, environment_value):
    # Regression test: settings.ENVIRONMENT used to be compared verbatim
    # ("== production") in app.api.v1.auth._set_refresh_cookie, so
    # ENVIRONMENT="Production" passed startup validation but produced a
    # non-secure refresh cookie. Canonicalization in Settings must make
    # every consumer, including this cookie flag, agree.
    settings = Settings(ENVIRONMENT=environment_value)
    monkeypatch.setattr(auth_module, "settings", settings)

    response = Response()
    auth_module._set_refresh_cookie(response, "dummy-refresh-token")

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "Secure" in set_cookie_header, f"expected a Secure cookie for ENVIRONMENT={environment_value!r}"


@pytest.mark.parametrize("environment_value", ["development", "Development", "  development  "])
def test_refresh_cookie_is_not_secure_for_development(monkeypatch, environment_value):
    settings = Settings(ENVIRONMENT=environment_value)
    monkeypatch.setattr(auth_module, "settings", settings)

    response = Response()
    auth_module._set_refresh_cookie(response, "dummy-refresh-token")

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "Secure" not in set_cookie_header


# PR24D-L1 (docs/runbooks/PR24_LOCAL_STAGING_INSTALLATION_RUNBOOK.md):
# COOKIE_SECURE decouples the refresh cookie's Secure attribute from
# ENVIRONMENT so local Staging/UAT (ENVIRONMENT=production, plain HTTP on
# a LAN, no TLS) can explicitly opt out without weakening real Production,
# which never sets this override.


def test_cookie_secure_defaults_to_environment_is_production_when_unset():
    assert Settings(ENVIRONMENT="production").cookie_secure is True
    assert Settings(ENVIRONMENT="development").cookie_secure is False


def test_cookie_secure_explicit_false_overrides_production():
    # The local-installer case: ENVIRONMENT=production (for
    # validate_production_secrets()'s hardened checks) but plain HTTP on
    # the LAN, so the cookie must not carry Secure or browsers drop it.
    settings = Settings(ENVIRONMENT="production", COOKIE_SECURE=False)
    assert settings.cookie_secure is False


def test_cookie_secure_explicit_true_overrides_development():
    settings = Settings(ENVIRONMENT="development", COOKIE_SECURE=True)
    assert settings.cookie_secure is True


def test_refresh_cookie_not_secure_when_cookie_secure_false_overrides_production(monkeypatch):
    settings = Settings(ENVIRONMENT="production", COOKIE_SECURE=False)
    monkeypatch.setattr(auth_module, "settings", settings)

    response = Response()
    auth_module._set_refresh_cookie(response, "dummy-refresh-token")

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "Secure" not in set_cookie_header


def test_refresh_cookie_still_secure_for_production_when_cookie_secure_unset(monkeypatch):
    # Real Production never sets COOKIE_SECURE -- confirms the override
    # introduced above changes nothing for the unconfigured (default) case.
    settings = Settings(ENVIRONMENT="production")
    monkeypatch.setattr(auth_module, "settings", settings)

    response = Response()
    auth_module._set_refresh_cookie(response, "dummy-refresh-token")

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "Secure" in set_cookie_header
