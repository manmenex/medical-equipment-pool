"""PR24D-L1 (docs/runbooks/PR24_LOCAL_STAGING_INSTALLATION_RUNBOOK.md):
static structural assertions on deployment/local-staging/compose.yml.

These are pure YAML-structure checks (no Docker daemon required, no live
`docker compose` invocation) proving the security/architecture invariants
the local Staging/UAT execution mode must never regress: no PostgreSQL/
Redis LAN exposure, exactly one backend replica/worker, no committed
secrets or defaults, the readiness endpoint (not the liveness-only one)
gates traffic, and the generated .env file is excluded from Git.
"""

from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "deployment" / "local-staging" / "compose.yml"
ENV_EXAMPLE_PATH = COMPOSE_PATH.parent / ".env.example"
GITIGNORE_PATH = Path(__file__).resolve().parents[2] / ".gitignore"


def _load_compose() -> dict:
    with COMPOSE_PATH.open() as fh:
        return yaml.safe_load(fh)


def test_compose_file_exists_and_parses():
    assert COMPOSE_PATH.is_file()
    compose = _load_compose()
    assert "services" in compose
    for name in ("postgres", "redis", "backend", "frontend"):
        assert name in compose["services"], f"missing required service: {name}"


def test_postgres_not_exposed_to_lan():
    services = _load_compose()["services"]
    assert "ports" not in services["postgres"], (
        "postgres must not publish a host port -- LAN clients must never reach it directly"
    )


def test_redis_not_exposed_to_lan():
    services = _load_compose()["services"]
    assert "ports" not in services["redis"], (
        "redis must not publish a host port -- LAN clients must never reach it directly"
    )


def test_backend_not_exposed_to_lan():
    services = _load_compose()["services"]
    assert "ports" not in services["backend"], (
        "backend must not publish a host port -- LAN clients reach it only through frontend's reverse proxy"
    )


def test_only_frontend_publishes_a_host_port():
    services = _load_compose()["services"]
    published = [name for name, svc in services.items() if "ports" in svc]
    assert published == ["frontend"], f"expected only frontend to publish a port, got: {published}"


def test_postgres_has_persistent_named_volume():
    compose = _load_compose()
    volumes = compose["services"]["postgres"].get("volumes", [])
    assert any("postgres_data" in v for v in volumes), "postgres must mount a persistent named volume"
    assert any(v.split(":")[0] in compose.get("volumes", {}) for v in volumes), (
        "postgres's volume must be a named (not anonymous/bind) volume declared in the top-level volumes: block"
    )


def test_no_deploy_replicas_key_present():
    # deploy.replicas is a Swarm-only directive silently ignored by plain
    # `docker compose up` -- its presence here would be misleading, not
    # protective. The real one-replica/one-worker invariant comes from
    # never running `--scale backend=N` (documented in compose.yml's own
    # header) plus backend/Dockerfile's own `--workers 1`.
    services = _load_compose()["services"]
    assert "deploy" not in services.get("backend", {}), (
        "deploy.replicas is Swarm-only and ignored by `docker compose up` -- do not rely on it here"
    )


def test_backend_readiness_healthcheck_not_liveness():
    services = _load_compose()["services"]
    healthcheck = services["backend"].get("healthcheck", {})
    test_cmd = " ".join(healthcheck.get("test", []))
    assert "/api/v1/ready" in test_cmd, "backend healthcheck must gate on /api/v1/ready (readiness), not /health"
    assert "/api/v1/health" not in test_cmd


def test_frontend_waits_for_backend_healthy():
    services = _load_compose()["services"]
    depends_on = services["frontend"].get("depends_on", {})
    assert depends_on.get("backend", {}).get("condition") == "service_healthy"


def test_environment_fixed_to_production():
    services = _load_compose()["services"]
    assert services["backend"]["environment"]["ENVIRONMENT"] == "production"


def test_cookie_secure_fixed_to_false():
    services = _load_compose()["services"]
    assert services["backend"]["environment"]["COOKIE_SECURE"] == "false"


def test_no_hardcoded_secrets_or_ip_in_compose_file():
    text = COMPOSE_PATH.read_text()
    for literal in ("mep_password", "change-me", "changeme", "password123"):
        assert literal not in text.lower(), f"compose.yml must not contain the literal {literal!r}"
    # No dotted-quad IPv4 literal anywhere (a hardcoded hospital IP)
    import re

    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text), (
        "compose.yml must not contain a hardcoded IP address"
    )


def test_no_insecure_default_fallback_for_required_secrets():
    # `${VAR:-default}` silently falls back to `default`; `${VAR:?msg}`
    # fails closed if VAR is unset. Every secret-shaped variable below
    # must use the fail-closed form, never the silent-default form.
    text = COMPOSE_PATH.read_text()
    for var in ("POSTGRES_PASSWORD", "JWT_SECRET_KEY", "ALLOWED_ORIGINS"):
        assert f"${{{var}:?" in text, f"{var} must use the required (:?) form, never a silent default"
        assert f"${{{var}:-" not in text, f"{var} must not have a silent (:-) default fallback"


def test_env_example_has_no_filled_in_secrets():
    text = ENV_EXAMPLE_PATH.read_text()
    for line in text.splitlines():
        if line.strip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in ("POSTGRES_PASSWORD", "JWT_SECRET_KEY", "ALLOWED_ORIGINS"):
            assert value.strip() == "", f"{key} must be left blank in .env.example, not pre-filled"


def test_local_staging_env_is_gitignored():
    patterns = GITIGNORE_PATH.read_text().splitlines()
    assert ".env" in [p.strip() for p in patterns], (
        "the root .gitignore's `.env` pattern must still cover deployment/local-staging/.env"
    )
