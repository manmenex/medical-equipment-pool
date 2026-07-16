from functools import lru_cache

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

# Minimum accepted length for JWT_SECRET_KEY in production. HS256 signing
# security depends entirely on this secret's unpredictability; this is not
# a cryptographic entropy guarantee, just a floor that rejects trivially
# short or placeholder values.
JWT_SECRET_MIN_LENGTH = 32

DEFAULT_JWT_SECRET_KEY = "change-me-in-production-use-a-random-64-byte-value"


class InsecureConfigurationError(RuntimeError):
    """Raised at startup when the running environment's configuration is unsafe.

    Intentionally a plain RuntimeError subclass (not a DomainError) since this
    fires before the ASGI app exists to route it through any HTTP exception
    handler — it must abort process startup, not produce an HTTP response.
    """


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    PROJECT_NAME: str = "Medical Equipment Pool"
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://mep_user:mep_password@localhost:5432/mep_db"

    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_ENABLED: bool = True

    JWT_SECRET_KEY: str = "change-me-in-production-use-a-random-64-byte-value"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_EXPIRE_DAYS: int = 7

    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost"

    S3_ENDPOINT: str | None = None
    S3_BUCKET: str = "mep-attachments"
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None

    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    NOTIFICATION_FROM_EMAIL: str = "noreply@hospital.local"

    PM_DUE_SOON_DAYS: int = 7
    CAL_DUE_SOON_DAYS: int = 7

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]


def validate_production_secrets(settings: Settings) -> None:
    """Refuse to run in production with a missing, default, or too-short JWT secret.

    Called once at application startup (see app.main.create_app). Raises
    InsecureConfigurationError instead of returning a status so the caller
    cannot accidentally ignore the result and continue booting.
    """
    if settings.ENVIRONMENT != "production":
        return

    if not settings.JWT_SECRET_KEY:
        raise InsecureConfigurationError(
            "JWT_SECRET_KEY is not set. Refusing to start with ENVIRONMENT=production and no "
            "JWT signing key configured. Set JWT_SECRET_KEY to a unique, randomly-generated value."
        )

    if settings.JWT_SECRET_KEY == DEFAULT_JWT_SECRET_KEY:
        raise InsecureConfigurationError(
            "JWT_SECRET_KEY is set to the publicly-documented default value shipped in source "
            "control. Refusing to start with ENVIRONMENT=production. Generate a real secret with: "
            'python -c "import secrets; print(secrets.token_urlsafe(64))" and set it as JWT_SECRET_KEY.'
        )

    if len(settings.JWT_SECRET_KEY) < JWT_SECRET_MIN_LENGTH:
        raise InsecureConfigurationError(
            f"JWT_SECRET_KEY is only {len(settings.JWT_SECRET_KEY)} characters, below the minimum "
            f"accepted length of {JWT_SECRET_MIN_LENGTH} for ENVIRONMENT=production. Generate a "
            'longer secret with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
