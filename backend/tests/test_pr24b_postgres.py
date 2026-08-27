"""PostgreSQL-backed test for PR24B's admin-bootstrap concurrency guard
(docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §17): SQLite
cannot prove `SELECT ... FOR UPDATE` actually serializes two concurrent
bootstrap attempts (its lock is a no-op on that dialect, by design --
see app.scripts.bootstrap_admin's own `_lock_administrator_role`), so
this test runs against a real PostgreSQL database, mirroring
test_postgres_integration.py's own pg_engine/skip-if-unreachable pattern.

Run only this suite:
    POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
        .venv/bin/python -m pytest -q -m postgres tests/test_pr24b_postgres.py
"""
import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.user import ALL_ROLES, ROLE_ADMINISTRATOR, Role, User
from app.scripts import bootstrap_admin

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
async def pg_roles_only(pg_engine):
    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        for name in ALL_ROLES:
            session.add(Role(name=name, permissions={}))
        await session.commit()
    return session_maker


async def test_concurrent_bootstrap_attempts_create_exactly_one_administrator(pg_roles_only, monkeypatch):
    # Two concurrent invocations racing to create "the" first
    # administrator -- app.scripts.bootstrap_admin.bootstrap_admin opens
    # its own AsyncSessionLocal() per call, exactly as two separate CLI
    # process invocations would each open their own connection.
    monkeypatch.setattr(bootstrap_admin, "AsyncSessionLocal", pg_roles_only)

    async def attempt(employee_code: str, email: str):
        try:
            return await bootstrap_admin.bootstrap_admin(
                employee_code=employee_code, email=email, full_name="Concurrent Admin"
            )
        except bootstrap_admin.BootstrapRefused as exc:
            return exc

    results = await asyncio.gather(
        attempt("ADMIN001", "admin1@hospital.local"),
        attempt("ADMIN002", "admin2@hospital.local"),
    )

    successes = [r for r in results if isinstance(r, tuple)]
    refusals = [r for r in results if isinstance(r, bootstrap_admin.BootstrapRefused)]
    assert len(successes) == 1, "exactly one concurrent attempt must succeed"
    assert len(refusals) == 1, "the other concurrent attempt must be refused, not silently create a second admin"

    async with pg_roles_only() as verify_db:
        admin_role = (
            await verify_db.execute(select(Role).where(Role.name == ROLE_ADMINISTRATOR))
        ).scalar_one()
        result = await verify_db.execute(select(User).where(User.role_id == admin_role.id))
        admins = result.scalars().all()
        assert len(admins) == 1, f"expected exactly 1 administrator after the race, found {len(admins)}"
