from functools import lru_cache

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
