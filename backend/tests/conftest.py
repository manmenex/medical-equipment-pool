import asyncio
import functools
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CACHE_ENABLED", "false")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import ALL_ROLES, ROLE_ADMINISTRATOR, Role, User


@functools.lru_cache(maxsize=None)
def cached_password_hash(password: str) -> str:
    """Hash a fixed fixture password once per test session.

    bcrypt cost 12 costs ~0.3 s per call, and the user-seeding fixtures hash the
    same constant password for every role on every test. Each user still gets a
    real production-cost hash that verifies through the real verify path; only
    the repeated computation is removed. Do not use for tests that assert on
    hashing behavior (salt uniqueness, cost, rehash).
    """
    return hash_password(password)


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_users(db_session):
    roles = {}
    for name in ALL_ROLES:
        role = Role(name=name, permissions={})
        db_session.add(role)
        roles[name] = role
    await db_session.flush()

    users = {}
    for role_name in ALL_ROLES:
        user = User(
            employee_code=f"{role_name.upper()}001",
            full_name=f"Test {role_name}",
            email=f"{role_name}@mep-hospital-test.dev",
            password_hash=cached_password_hash("Password@123"),
            role_id=roles[role_name].id,
        )
        db_session.add(user)
        users[role_name] = user
    await db_session.commit()
    return users


@pytest_asyncio.fixture
async def client(db_engine, db_session):
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def login(client: AsyncClient, identifier: str, password: str = "Password@123") -> str:
    resp = await client.post("/api/v1/auth/login", json={"identifier": identifier, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Shared test helpers. Previously duplicated (with subtly inconsistent
# signatures/return shapes) across test_borrow.py, test_equipment.py,
# test_exception_handling.py, test_audit.py, and
# test_validation_and_auth_regression.py; consolidated here so every module
# uses the same behavior. No test behavior changes as part of this
# consolidation -- every call site's observable HTTP requests/assertions are
# unchanged.
# ---------------------------------------------------------------------------


async def auth_headers(client: AsyncClient, role: str = ROLE_ADMINISTRATOR) -> dict:
    identifier = f"{role.upper()}001"
    token = await login(client, identifier)
    return {"Authorization": f"Bearer {token}"}


async def create_ward(client: AsyncClient, headers: dict, code: str, name: str | None = None) -> str:
    """Creates a ward and returns its id. `code` must be unique per call site
    (wards.code is unique) -- every existing call site already satisfies
    this."""
    resp = await client.post("/api/v1/wards", headers=headers, json={"code": code, "name": name or code})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def on_demand_borrow_payload(client: AsyncClient, admin_headers: dict, equipment_id: str, *, ward_code: str) -> dict:
    """Roadmap PR7b: every dispatch requires ward_id and dispatch_type --
    borrower_name is no longer accepted. Creates a fresh ward and returns a
    ready-to-use on-demand borrow JSON payload."""
    ward_id = await create_ward(client, admin_headers, ward_code)
    return {"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand"}


# CI sharding. `.github/workflows/ci.yml` runs each backend suite as several
# parallel jobs; PYTEST_SHARD="<index>/<total>" (0-based) keeps every
# total-th collected test, so the shards are disjoint and together cover the
# whole selection. Item-level, not file-level: test_postgres_integration.py
# alone holds most of the PostgreSQL suite, so whole-file shards could not
# balance. PYTEST_SHARD_REPORT names a JSON file recording how many tests
# this shard ran out of how many were collected; the CI gate job sums those
# to prove no test fell between shards. Unset locally, nothing changes.
# trylast: shard what `-m` left, not the whole collection.
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    shard = os.environ.get("PYTEST_SHARD")
    if not shard:
        return
    index, total = (int(part) for part in shard.split("/"))
    if not 0 <= index < total:
        raise pytest.UsageError(f"PYTEST_SHARD={shard!r}: index must be in [0, {total})")
    collected = len(items)
    kept = [item for position, item in enumerate(items) if position % total == index]
    dropped = [item for position, item in enumerate(items) if position % total != index]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept
    report = os.environ.get("PYTEST_SHARD_REPORT")
    if report:
        import json

        with open(report, "w", encoding="utf-8") as handle:
            json.dump({"shard": shard, "collected": collected, "selected": len(kept)}, handle)
