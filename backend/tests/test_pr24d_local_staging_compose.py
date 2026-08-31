"""PR24D-L1 (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §32;
the full operator runbook is planned for PR24D-L3 and does not exist yet):
static structural assertions on deployment/local-staging/compose.yml.

These are pure YAML-structure checks (no Docker daemon required, no live
`docker compose` invocation) proving the security/architecture invariants
the local Staging/UAT execution mode must never regress: no PostgreSQL/
Redis LAN exposure, exactly one backend replica/worker (structurally, not
just documented), Redis is never a startup-blocking dependency, no
committed secrets or defaults, the readiness endpoint (not the
liveness-only one) gates traffic, and the generated .env file is excluded
from Git.
"""

from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "deployment" / "local-staging" / "compose.yml"
ENV_EXAMPLE_PATH = COMPOSE_PATH.parent / ".env.example"
GITIGNORE_PATH = Path(__file__).resolve().parents[2] / ".gitignore"
DOCKERFILE_PATH = Path(__file__).resolve().parents[2] / "backend" / "Dockerfile"


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
    # protective. The real one-replica/one-worker invariant comes from the
    # fixed `container_name` guard (see
    # test_backend_has_fixed_container_name_to_structurally_block_scaling)
    # plus backend/Dockerfile's own `--workers 1`.
    services = _load_compose()["services"]
    assert "deploy" not in services.get("backend", {}), (
        "deploy.replicas is Swarm-only and ignored by `docker compose up` -- do not rely on it here"
    )


def test_backend_has_fixed_container_name_to_structurally_block_scaling():
    # A fixed container_name makes `docker compose up --scale backend=2`
    # fail (Compose refuses to create two containers sharing one name) --
    # this is the structural enforcement of the single-backend invariant,
    # not just a comment. The embedded APScheduler (app/worker/scheduler.py)
    # has no leader-election guard, so a second backend container would
    # duplicate the daily PM/CAL notification job.
    services = _load_compose()["services"]
    container_name = services["backend"].get("container_name")
    assert container_name, "backend must set a fixed container_name to structurally block --scale backend=N"


def test_backend_dockerfile_worker_count_is_one():
    # The container-count guard above only prevents *multiple containers*;
    # it says nothing about a single container running multiple Uvicorn
    # worker processes. Assert the actual launch command directly.
    dockerfile_text = DOCKERFILE_PATH.read_text()
    import re

    match = re.search(r'"--workers",\s*"(\d+)"', dockerfile_text)
    assert match, "backend/Dockerfile's CMD must specify --workers explicitly"
    assert match.group(1) == "1", (
        f"backend/Dockerfile must run exactly 1 Uvicorn worker, found {match.group(1)!r} "
        "-- the embedded APScheduler has no leader-election guard"
    )


def test_redis_is_not_a_health_gated_startup_dependency_for_backend():
    # backend/app/core/redis.py wraps every Redis call in try/except and
    # fails open (cache misses become no-ops; refresh-token validation
    # treats an unreachable Redis as valid) -- GET /api/v1/ready reports
    # Redis but never blocks on it. Gating backend startup on Redis health
    # here would make an already-non-critical dependency accidentally
    # block the whole stack (and therefore `frontend`, which waits on
    # backend), contradicting that contract.
    services = _load_compose()["services"]
    redis_dep = services["backend"].get("depends_on", {}).get("redis")
    assert redis_dep is None or redis_dep.get("condition") != "service_healthy", (
        "backend must not have a service_healthy-gated dependency on redis"
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
