from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import AnyUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Minimum accepted length for JWT_SECRET_KEY in production. HS256 signing
# security depends entirely on this secret's unpredictability; this is not
# a cryptographic entropy guarantee, just a floor that rejects trivially
# short or placeholder values.
JWT_SECRET_MIN_LENGTH = 32

DEFAULT_JWT_SECRET_KEY = "change-me-in-production-use-a-random-64-byte-value"

# PR24B (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §14): the
# same class of risk as DEFAULT_JWT_SECRET_KEY above -- a deployment that
# silently boots ENVIRONMENT=production against the shipped local-dev
# default DATABASE_URL, or with ALLOWED_ORIGINS still unset to the shipped
# localhost dev origins, is a real, easy-to-make misconfiguration
# (forgetting to override an env var), not a hypothetical.
DEFAULT_DATABASE_URL = "postgresql+asyncpg://mep_user:mep_password@localhost:5432/mep_db"
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173,http://localhost"

# PR24B Fix Round 1 (independent review, P1): the repository ships more
# than one literal placeholder for JWT_SECRET_KEY -- config.py's own field
# default / docker-compose.yml's inline default use different wording
# from .env.example's separate copy-paste placeholder. A single exact-
# match check against only one of these misses the other -- the same
# defect class as the ALLOWED_ORIGINS order mismatch this fix round
# addresses. Both known literals are rejected below.
KNOWN_INSECURE_JWT_SECRET_KEYS = frozenset(
    {
        DEFAULT_JWT_SECRET_KEY,  # config.py Settings field default / docker-compose.yml inline default
        "change-me-to-a-random-64-byte-value",  # .env.example's own placeholder text
    }
)

# PR24B Fix Round 2 (independent re-review, P1): DATABASE_URL has more
# shipped-default resolutions than Fix Round 1's two-literal set covered.
# docker-compose.yml computes DATABASE_URL from POSTGRES_USER/
# POSTGRES_PASSWORD/POSTGRES_DB, each with its own `${VAR:-default}`
# fallback -- so *no* `.env` at all (docker-compose.yml's own native
# defaults, host "postgres", password "mep_password") is a THIRD distinct
# literal, on top of Fix Round 1's local-dev default (host "localhost",
# password "mep_password") and .env.example-copied default (host
# "postgres", password "change-me"). A closed set of full-URL literals
# would need a new entry for every host x password combination the
# repository ever ships; instead this checks the four identity
# components independently -- username, database name, host, and
# password each drawn from their own small known-shipped set. A managed-
# provider URL would need to accidentally reuse all four simultaneously
# to be misclassified, which is not a realistic production
# configuration, and no new literal is needed if a future host/password
# combination is added to docker-compose.yml or .env.example as long as
# the username/database stay "mep_user"/"mep_db".
INSECURE_DATABASE_USERNAME = "mep_user"
INSECURE_DATABASE_NAME = "mep_db"
INSECURE_DATABASE_HOSTS = frozenset({"localhost", "postgres"})
INSECURE_DATABASE_PASSWORDS = frozenset({"mep_password", "change-me"})

# The only ENVIRONMENT values this deployment recognizes (see .env.example,
# docker-compose.yml, docker-compose.prod.yml). Anything else is treated as
# a misconfiguration rather than silently falling back to development.
KNOWN_ENVIRONMENTS = {"development", "production"}


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

    ALLOWED_ORIGINS: str = DEFAULT_ALLOWED_ORIGINS

    # PR24D-L1 (docs/runbooks/PR24_LOCAL_STAGING_INSTALLATION_RUNBOOK.md):
    # the refresh-token cookie's `Secure` attribute was previously tied
    # directly to `ENVIRONMENT == "production"` in app.api.v1.auth. Local
    # Staging/UAT execution (Docker on a LAN host, no TLS) also runs under
    # ENVIRONMENT=production -- deliberately, to keep
    # validate_production_secrets()'s hardened checks (no default secrets/
    # database/origins) in effect -- but a browser silently drops a Secure
    # cookie set over plain HTTP, breaking token refresh. None (the
    # default) preserves the exact previous behavior for every existing
    # deployment (derived from ENVIRONMENT below); only a deployment that
    # explicitly sets COOKIE_SECURE=false (the local installer) opts out.
    # Real Production is unaffected unless it, too, explicitly overrides
    # this -- which it must never do.
    COOKIE_SECURE: bool | None = None

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

    # Roadmap PR19A2 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §9.1/
    # §9.2): a validation-job lease's duration and the interval at which a
    # live worker renews it. Defaults match the design's own recommended 5x
    # safety margin (300s lease / 60s renewal) so a single missed renewal
    # never triggers a false-positive recovery.
    IMPORT_JOB_LEASE_DURATION_SECONDS: int = 300
    IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS: int = 60

    # Roadmap PR19A3 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §18,
    # Owner Decision recorded in docs/DECISION_LOG.md): 180-day post-terminal
    # retention, deployment-configurable, no Version 1 Administrator UI to
    # change it. IMPORT_RETENTION_CLEANUP_CLAIM_TIMEOUT_SECONDS bounds how
    # long a retention-cleanup claim survives a crashed cleanup worker
    # before another invocation may re-claim it (design §18's "e.g. 5
    # minutes -- a single session's redaction is fast" example).
    IMPORT_RETENTION_DAYS: int = 180
    IMPORT_RETENTION_CLEANUP_CLAIM_TIMEOUT_SECONDS: int = 300

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def cookie_secure(self) -> bool:
        """Whether the refresh-token cookie's `Secure` attribute should be
        set. Defaults to `ENVIRONMENT == "production"` (the historical,
        unconditional behavior) unless COOKIE_SECURE is explicitly set,
        which always wins regardless of ENVIRONMENT."""
        if self.COOKIE_SECURE is not None:
            return self.COOKIE_SECURE
        return self.ENVIRONMENT == "production"

    @field_validator(
        "IMPORT_JOB_LEASE_DURATION_SECONDS",
        "IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS",
        "IMPORT_RETENTION_DAYS",
        "IMPORT_RETENTION_CLEANUP_CLAIM_TIMEOUT_SECONDS",
    )
    @classmethod
    def _positive_import_timing(cls, value: int, info) -> int:
        """Roadmap PR19 (§9.1/§9.2/§18): every one of these values gates a
        safety-critical durability or retention window -- a non-positive
        value is never a valid degenerate case, it is a misconfiguration
        that must fail application startup, not silently produce
        immediately-expiring leases/claims or immediately-eligible
        retention data. Checked here (Settings construction, i.e. process
        startup, see `get_settings` below) rather than deferred to the
        first request that touches it."""
        if value <= 0:
            raise ValueError(
                f"{info.field_name} must be a positive number of seconds/days, got {value}. "
                "A non-positive value would make leases/claims expire immediately or make data "
                "immediately eligible for retention action -- refusing to start with this configuration."
            )
        return value

    @model_validator(mode="after")
    def _heartbeat_bounded_under_lease_duration(self) -> "Settings":
        """§9.2: "a lease's effective lifetime for renewal purposes is
        bounded by `IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS`, itself bounded
        well under `IMPORT_JOB_LEASE_DURATION_SECONDS`" -- the renewal
        loop can never keep a lease alive if it fires no more often than
        the lease's own expiry. Enforced as a strict `<` relationship
        (the minimum the mechanism requires to function at all); the
        shipped defaults (60s / 300s) already satisfy this with the
        design's own 5x safety margin, so this never constrains a
        deployment that follows the documented defaults."""
        if self.IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS >= self.IMPORT_JOB_LEASE_DURATION_SECONDS:
            raise ValueError(
                "IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS "
                f"({self.IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS}) must be strictly less than "
                f"IMPORT_JOB_LEASE_DURATION_SECONDS ({self.IMPORT_JOB_LEASE_DURATION_SECONDS}) -- otherwise "
                "the renewal loop can never renew a lease before it expires. Refusing to start with this "
                "configuration."
            )
        return self

    @field_validator("ENVIRONMENT")
    @classmethod
    def _canonicalize_environment(cls, value: str) -> str:
        """Normalize ENVIRONMENT once, at construction time.

        Every consumer — this module's own production checks, the
        refresh-token cookie's `secure` flag in app.api.v1.auth, anything
        added later — reads settings.ENVIRONMENT after this validator runs,
        so trimming and lowercasing here is the single source of truth.
        Membership in KNOWN_ENVIRONMENTS is checked later in
        validate_production_secrets, not here, so that a clear
        InsecureConfigurationError (routed through app.main's startup
        logging) is raised at the same point as the other startup checks
        instead of a raw pydantic ValidationError at import time.
        """
        return value.strip().lower()


def _is_shipped_localhost_dev_origin(origin: str) -> bool:
    """True for the plain-HTTP `localhost` origin pattern that repository
    authority explicitly names as the forbidden production default
    (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §9: "never the
    development defaults (`http://localhost*`)") -- any port, scheme fixed
    to `http` since that is what `.env.example` / `docker-compose.yml`
    actually ship. Deliberately scoped to what the design doc names rather
    than a general loopback/private-network guess: e.g. 127.0.0.1 is not
    named anywhere in repository authority, so it is not treated as an
    equivalent here.
    """
    parsed = urlsplit(origin)
    return parsed.scheme.lower() == "http" and parsed.hostname == "localhost"


def _is_shipped_insecure_database_url(database_url: str) -> bool:
    """True when database_url's connection identity matches every
    component of a repository-shipped default (PR24B Fix Round 2): a
    username of `mep_user`, a database name of `mep_db`, a host of
    `localhost` (config.py's own local-dev default) or `postgres`
    (docker-compose.yml's service name), and a password of
    `mep_password` (docker-compose.yml's own native default, or
    config.py's local-dev default) or `change-me` (.env.example's
    placeholder). Checking components independently rather than a
    closed set of full-URL literals means a legitimate managed-provider
    URL is misclassified only if it happens to reuse all four shipped
    values simultaneously -- not a realistic production configuration --
    and no new literal needs adding if a future host/password
    combination is introduced as long as the username/database stay
    their shipped values.
    """
    parsed = urlsplit(database_url)
    database_name = parsed.path.lstrip("/")
    return (
        parsed.username == INSECURE_DATABASE_USERNAME
        and parsed.password in INSECURE_DATABASE_PASSWORDS
        and parsed.hostname in INSECURE_DATABASE_HOSTS
        and database_name == INSECURE_DATABASE_NAME
    )


def validate_production_secrets(settings: Settings) -> None:
    """Refuse to run in production with a missing, default, or too-short JWT secret.

    Called once at application startup (see app.main.create_app). Raises
    InsecureConfigurationError instead of returning a status so the caller
    cannot accidentally ignore the result and continue booting.
    """
    # settings.ENVIRONMENT is already trimmed and lowercased by
    # Settings._canonicalize_environment, so this is an exact match against
    # the canonical value — not a re-normalization.
    if settings.ENVIRONMENT not in KNOWN_ENVIRONMENTS:
        raise InsecureConfigurationError(
            f"ENVIRONMENT={settings.ENVIRONMENT!r} is not a recognized value. Refusing to start "
            "with an unrecognized environment rather than silently treating it as development. "
            f"Set ENVIRONMENT to one of: {', '.join(sorted(KNOWN_ENVIRONMENTS))}."
        )

    if settings.ENVIRONMENT != "production":
        return

    if not settings.JWT_SECRET_KEY:
        raise InsecureConfigurationError(
            "JWT_SECRET_KEY is not set. Refusing to start with ENVIRONMENT=production and no "
            "JWT signing key configured. Set JWT_SECRET_KEY to a unique, randomly-generated value."
        )

    if settings.JWT_SECRET_KEY in KNOWN_INSECURE_JWT_SECRET_KEYS:
        raise InsecureConfigurationError(
            "JWT_SECRET_KEY is set to a publicly-documented placeholder value shipped in source "
            "control (config.py's own default, docker-compose.yml's inline default, or "
            ".env.example's copy-paste placeholder). Refusing to start with ENVIRONMENT=production. "
            'Generate a real secret with: python -c "import secrets; print(secrets.token_urlsafe(64))" '
            "and set it as JWT_SECRET_KEY."
        )

    if len(settings.JWT_SECRET_KEY) < JWT_SECRET_MIN_LENGTH:
        raise InsecureConfigurationError(
            f"JWT_SECRET_KEY is only {len(settings.JWT_SECRET_KEY)} characters, below the minimum "
            f"accepted length of {JWT_SECRET_MIN_LENGTH} for ENVIRONMENT=production. Generate a "
            'longer secret with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
        )

    if _is_shipped_insecure_database_url(settings.DATABASE_URL):
        raise InsecureConfigurationError(
            "DATABASE_URL resolves to a repository-shipped development/default database "
            "configuration (matching the shipped username, database name, host, and password "
            "identity). Refusing to start with ENVIRONMENT=production and no real production "
            "database configured. Set DATABASE_URL to the actual production PostgreSQL connection "
            "string. (The connection string itself is intentionally not included in this message, "
            "since DATABASE_URL commonly carries a username and password.)"
        )

    origins = frozenset(settings.allowed_origins_list)
    if not origins:
        raise InsecureConfigurationError(
            "ALLOWED_ORIGINS is empty. Refusing to start with ENVIRONMENT=production and no real "
            "production origin configured. Set ALLOWED_ORIGINS to the actual production frontend "
            "origin(s)."
        )

    if all(_is_shipped_localhost_dev_origin(origin) for origin in origins):
        raise InsecureConfigurationError(
            "ALLOWED_ORIGINS resolves entirely to the shipped development-only localhost origin "
            f"pattern ({sorted(origins)!r}), regardless of ordering, spacing, or duplicates. "
            "Refusing to start with ENVIRONMENT=production and no real production origin configured "
            "(docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §9: ALLOWED_ORIGINS must be set "
            "to the exact production hostname(s) only -- never a wildcard, never the development "
            "defaults `http://localhost*`). Set ALLOWED_ORIGINS to the actual production frontend "
            "origin(s)."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
