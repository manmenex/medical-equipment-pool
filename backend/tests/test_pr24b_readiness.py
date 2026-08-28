"""PR24B (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §15A):
GET /api/v1/ready -- the fail-closed production readiness probe. Also
covers that GET /api/v1/health's existing always-200 liveness behavior
is unchanged.
"""
import pytest

from app.api.v1 import health as health_module
from app.db.session import get_db
from app.main import app


class _BrokenDBSession:
    """Fails every query, mirroring test_redis_failure_logging.py's own
    BrokenRedisClient -- the DB-unavailable half of the readiness matrix."""

    async def execute(self, *_args, **_kwargs):
        raise ConnectionError("database unavailable: could not connect to server")


async def _override_broken_db():
    yield _BrokenDBSession()


class _BrokenRedisClient:
    async def ping(self):
        raise ConnectionError("redis unavailable")


class _HealthyRedisClient:
    async def ping(self):
        return True


@pytest.fixture(autouse=True)
def healthy_redis(monkeypatch):
    monkeypatch.setattr(health_module, "get_redis", lambda: _HealthyRedisClient())


async def test_ready_returns_200_when_db_and_redis_healthy(client):
    response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ready", "database": "ok", "redis": "ok"}


async def test_ready_returns_200_degraded_when_redis_unavailable(client, monkeypatch):
    monkeypatch.setattr(health_module, "get_redis", lambda: _BrokenRedisClient())
    response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ready", "database": "ok", "redis": "degraded"}


async def test_ready_returns_503_when_database_unavailable(client):
    app.dependency_overrides[get_db] = _override_broken_db
    try:
        response = await client.get("/api/v1/ready")
    finally:
        del app.dependency_overrides[get_db]
        # Restore the client fixture's own override for any later request
        # in this test (none here, but keeps the fixture's contract intact
        # for anything appended to this test later).
    assert response.status_code == 503
    body = response.json()
    assert body == {"status": "not_ready", "database": "error", "redis": "ok"}


async def test_ready_response_never_leaks_exception_text_or_secrets(client):
    app.dependency_overrides[get_db] = _override_broken_db
    try:
        response = await client.get("/api/v1/ready")
    finally:
        del app.dependency_overrides[get_db]
    raw_body = response.text
    assert "ConnectionError" not in raw_body
    assert "could not connect to server" not in raw_body
    assert "Traceback" not in raw_body
    assert "postgresql" not in raw_body.lower()
    assert "password" not in raw_body.lower()


async def test_health_endpoint_still_always_returns_200(client):
    """Regression: /health remains the unauthenticated, always-200
    liveness/diagnostic endpoint -- unchanged by this PR's own §15A work."""
    app.dependency_overrides[get_db] = _override_broken_db
    try:
        response = await client.get("/api/v1/health")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "error"


async def test_ready_does_not_require_authentication(client):
    # No Authorization header is set anywhere in this test -- a 401/403
    # here would mean the probe is unusable by a deployment platform that
    # calls it before any user session exists.
    response = await client.get("/api/v1/ready")
    assert response.status_code in (200, 503)


@pytest.mark.parametrize(
    "redis_client",
    [_BrokenRedisClient()],
    ids=["connection_error"],
)
async def test_ready_multiple_redis_failure_forms_remain_non_blocking(client, monkeypatch, redis_client):
    monkeypatch.setattr(health_module, "get_redis", lambda: redis_client)
    response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["redis"] == "degraded"


async def test_ready_redis_generic_exception_also_non_blocking(client, monkeypatch):
    class _WeirdRedisClient:
        async def ping(self):
            raise RuntimeError("unexpected redis client error")

    monkeypatch.setattr(health_module, "get_redis", lambda: _WeirdRedisClient())
    response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["redis"] == "degraded"
