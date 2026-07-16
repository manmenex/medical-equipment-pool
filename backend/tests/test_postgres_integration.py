"""PostgreSQL-backed integration tests for structured exception handling.

The main suite runs against SQLite, which does not enforce foreign key
constraints by default — so it cannot prove the IntegrityError SQLSTATE
classification in app.core.db_errors actually works, only that the
pre-flush existence checks in app.core.references do (those work against
any backend). These tests run against a real PostgreSQL database instead,
which does enforce FK/unique/not-null/check constraints, so the
`_classify()` SQLSTATE mapping is exercised for real.

Run only this suite:
    POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
        .venv/bin/python -m pytest -q -m postgres

Run the full suite (these tests skip automatically if PostgreSQL is not
reachable at POSTGRES_TEST_DATABASE_URL, so this is always safe to run):
    .venv/bin/python -m pytest -q

Default connection target if POSTGRES_TEST_DATABASE_URL is unset:
    postgresql+asyncpg://mep_test:mep_test_password@localhost:5432/mep_test_db
"""

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db_errors import translate_integrity_error
from app.core.exceptions import DuplicateError, InvalidInputError
from app.core.security import hash_password
from app.crud import master_data as md_crud
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.equipment import Equipment
from app.models.user import ALL_ROLES, Role, User

pytestmark = pytest.mark.postgres

POSTGRES_TEST_DATABASE_URL = os.environ.get(
    "POSTGRES_TEST_DATABASE_URL",
    "postgresql+asyncpg://mep_test:mep_test_password@localhost:5432/mep_test_db",
)


@pytest_asyncio.fixture
async def pg_engine():
    engine = create_async_engine(POSTGRES_TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL not reachable/usable at {POSTGRES_TEST_DATABASE_URL}: {exc}")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine):
    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def pg_seeded_users(pg_session):
    roles = {}
    for name in ALL_ROLES:
        role = Role(name=name, permissions={})
        pg_session.add(role)
        roles[name] = role
    await pg_session.flush()

    users = {}
    for role_name in ALL_ROLES:
        user = User(
            employee_code=f"{role_name.upper()}001",
            full_name=f"Test {role_name}",
            email=f"{role_name}@mep-hospital-test.dev",
            password_hash=hash_password("Password@123"),
            role_id=roles[role_name].id,
        )
        pg_session.add(user)
        users[role_name] = user
    await pg_session.commit()
    return users


@pytest_asyncio.fixture
async def pg_client(pg_engine, pg_session):
    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _admin_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"identifier": "ADMIN001", "password": "Password@123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# API-level: duplicate unique key -> 409 DUPLICATE
# ---------------------------------------------------------------------------


async def test_duplicate_department_code_returns_409_duplicate_on_postgres(pg_client, pg_seeded_users):
    headers = await _admin_headers(pg_client)
    payload = {"code": "PGDUP", "name": "Cardiology"}
    first = await pg_client.post("/api/v1/departments", headers=headers, json=payload)
    assert first.status_code == 201, first.text

    second = await pg_client.post(
        "/api/v1/departments", headers=headers, json={"code": "PGDUP", "name": "Cardiology 2"}
    )
    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "DUPLICATE"
    assert "sqlstate" not in body["detail"].lower()
    assert "23505" not in body["detail"]


# ---------------------------------------------------------------------------
# API-level: missing references -> safe non-DUPLICATE response
# ---------------------------------------------------------------------------


async def test_ward_with_missing_department_is_not_classified_as_duplicate_on_postgres(pg_client, pg_seeded_users):
    headers = await _admin_headers(pg_client)
    resp = await pg_client.post(
        "/api/v1/wards",
        headers=headers,
        json={"code": "PGW1", "name": "Ghost Ward", "department_id": str(uuid.uuid4())},
    )
    assert resp.status_code != 409
    body = resp.json()
    assert body["code"] != "DUPLICATE"
    assert resp.status_code == 400
    assert body["code"] == "INVALID_INPUT"


async def test_equipment_with_missing_references_is_not_classified_as_duplicate_on_postgres(
    pg_client, pg_seeded_users
):
    headers = await _admin_headers(pg_client)
    resp = await pg_client.post(
        "/api/v1/equipment",
        headers=headers,
        json={
            "asset_number": "PG-EQ-0001",
            "equipment_name": "Infusion Pump",
            "category_id": str(uuid.uuid4()),
            "department_owner_id": str(uuid.uuid4()),
            "current_location_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code != 409
    body = resp.json()
    assert body["code"] != "DUPLICATE"
    assert resp.status_code == 400
    assert body["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Low-level: prove the SQLSTATE classification itself against real Postgres,
# independent of the pre-flush existence checks (which would otherwise catch
# every case above before the database is ever asked to enforce anything).
# ---------------------------------------------------------------------------


async def test_foreign_key_violation_is_classified_as_invalid_input_not_duplicate(pg_session):
    with pytest.raises(InvalidInputError):
        async with translate_integrity_error(pg_session, resource="ward"):
            # Bypasses app.core.references entirely — this goes straight to
            # the database, which must reject it via a real FK constraint.
            await md_crud.create_ward(pg_session, code="RAWFK", name="Raw FK Ward", department_id=uuid.uuid4())


async def test_unique_violation_is_classified_as_duplicate(pg_session):
    await md_crud.create_department(pg_session, code="RAWUQ", name="First")
    await pg_session.commit()

    with pytest.raises(DuplicateError):
        async with translate_integrity_error(pg_session, resource="department"):
            await md_crud.create_department(pg_session, code="RAWUQ", name="Second")


async def test_not_null_violation_is_classified_as_invalid_input(pg_session):
    with pytest.raises(InvalidInputError):
        async with translate_integrity_error(pg_session, resource="department"):
            # Raw SQL, bypassing the ORM/Pydantic layers entirely, which
            # would otherwise reject a NULL name before it ever reached the
            # database — this proves the SQLSTATE 23502 mapping itself.
            await pg_session.execute(
                text("INSERT INTO departments (id, code, name) VALUES (gen_random_uuid(), 'RAWNN', NULL)")
            )
            await pg_session.flush()


# ---------------------------------------------------------------------------
# Rollback / atomicity, verified from a fresh session
# ---------------------------------------------------------------------------


async def test_rollback_after_duplicate_leaves_no_extra_business_row(pg_client, pg_seeded_users, pg_engine):
    headers = await _admin_headers(pg_client)
    payload = {"asset_number": "PG-ROLLBACK-0001", "equipment_name": "Ventilator"}
    first = await pg_client.post("/api/v1/equipment", headers=headers, json=payload)
    assert first.status_code == 201, first.text

    second = await pg_client.post("/api/v1/equipment", headers=headers, json=payload)
    assert second.status_code == 409

    # Fresh session/connection, independent of whatever the request used.
    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as fresh_session:
        result = await fresh_session.execute(
            select(Equipment).where(Equipment.asset_number == "PG-ROLLBACK-0001")
        )
        rows = result.scalars().all()
    assert len(rows) == 1


async def test_rollback_after_duplicate_leaves_no_audit_row(pg_client, pg_seeded_users, pg_engine):
    headers = await _admin_headers(pg_client)
    payload = {"asset_number": "PG-ROLLBACK-0002", "equipment_name": "X-Ray"}
    first = await pg_client.post("/api/v1/equipment", headers=headers, json=payload)
    assert first.status_code == 201, first.text

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as fresh_session:
        before = (
            await fresh_session.execute(select(AuditLog).where(AuditLog.entity_type == "equipment"))
        ).scalars().all()

    second = await pg_client.post("/api/v1/equipment", headers=headers, json=payload)
    assert second.status_code == 409

    async with session_maker() as fresh_session:
        after = (
            await fresh_session.execute(select(AuditLog).where(AuditLog.entity_type == "equipment"))
        ).scalars().all()

    assert len(after) == len(before), "a failed duplicate create must not leave an audit row behind"


# ---------------------------------------------------------------------------
# PR3: authentication-event audit is best-effort, verified against a real
# SAVEPOINT/ROLLBACK TO SAVEPOINT on PostgreSQL (SQLite emulates savepoints
# differently at the driver level, so this must be checked here too, not
# just in the SQLite-backed suite).
# ---------------------------------------------------------------------------


async def test_login_succeeds_on_postgres_even_if_audit_write_fails(pg_client, pg_seeded_users, monkeypatch):
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr("app.core.audit.audit_crud.create", _boom)

    resp = await pg_client.post(
        "/api/v1/auth/login", json={"identifier": "ADMIN001", "password": "Password@123"}
    )
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()
