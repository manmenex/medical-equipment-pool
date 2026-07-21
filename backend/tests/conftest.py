import asyncio
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
from app.models.user import ALL_ROLES, Role, User


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
            password_hash=hash_password("Password@123"),
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


async def auth_headers(client: AsyncClient, role: str = "admin") -> dict:
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
