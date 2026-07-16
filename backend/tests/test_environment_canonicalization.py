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
