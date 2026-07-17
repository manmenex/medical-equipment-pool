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

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select, text
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
from app.models.transaction import BorrowTransaction
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


@pytest_asyncio.fixture
async def pg_transaction_seq(pg_engine):
    """PR4: ensures transaction_no_seq exists for tests exercising the
    already-cutover, steady-state PostgreSQL generator via the ORM/API.

    pg_engine's schema is built via Base.metadata.create_all(), which
    only creates ORM-mapped tables/columns — not the raw SQL SEQUENCE
    object migration 0003_transaction_no_seq.py creates. This mirrors
    what that migration does for a genuinely fresh database (no
    pre-existing transaction_no rows to seed above). The dedicated
    migration tests below (test_migration_0003_*) exercise the real
    0003 migration file, including its populated-database seeding
    logic — this fixture is not a substitute for those and proves
    nothing about cutover safety by itself.
    """
    # lock_timeout: fail fast (instead of hanging the whole suite) in the
    # unlikely event some other connection is still holding a lock on this
    # sequence when a test starts -- IF NOT EXISTS makes the statement
    # itself safe to repeat; this only guards against ever blocking on it.
    async with pg_engine.begin() as conn:
        await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        await conn.execute(text("CREATE SEQUENCE IF NOT EXISTS transaction_no_seq START WITH 1"))
    yield
    # Deliberately no teardown DROP here: this fixture's job is only to
    # make the sequence exist for tests exercising the steady-state
    # generator. Not part of Base.metadata, so pg_engine's own
    # drop_all()/create_all() cycle never touches it either way, and
    # IF NOT EXISTS at setup makes repeated runs safe regardless of
    # whether a prior run's value is still present. An earlier version of
    # this fixture dropped the sequence on teardown to avoid an
    # ever-growing value across runs, but that DROP could block
    # indefinitely behind an unrelated, still-closing connection from a
    # prior test holding a lock on it -- a hang is a far worse outcome
    # than a monotonically growing bigint in a throwaway test database.


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


async def test_equipment_create_with_due_dates_is_json_safe_on_postgres(pg_client, pg_seeded_users, pg_engine):
    # CR7-M3 / PR7-H1: the SQLite suite already covers the JSON-mode date
    # fix (equipment.py's create_equipment builds audit_after via
    # payload.model_dump(mode="json") instead of reusing the ORM-write
    # dict), but the audit column is JSONB on PostgreSQL specifically, not
    # SQLite's generic JSON variant — this proves the fix against the real
    # production column type/dialect, not just SQLite's emulation of it.
    headers = await _admin_headers(pg_client)
    resp = await pg_client.post(
        "/api/v1/equipment",
        headers=headers,
        json={
            "asset_number": "PG-DATES-0001",
            "equipment_name": "Ventilator",
            "pm_due_date": "2026-08-01",
            "cal_due_date": "2026-09-15",
        },
    )
    assert resp.status_code == 201, resp.text
    equipment_id = resp.json()["id"]
    assert resp.json()["pm_due_date"] == "2026-08-01"
    assert resp.json()["cal_due_date"] == "2026-09-15"

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as fresh_session:
        equipment_rows = (
            await fresh_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
        ).scalars().all()
        assert len(equipment_rows) == 1

        audit_rows = (
            await fresh_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "create",
                    AuditLog.entity_type == "equipment",
                    AuditLog.entity_id == uuid.UUID(equipment_id),
                )
            )
        ).scalars().all()
        assert len(audit_rows) == 1
        row = audit_rows[0]
        # JSONB round-trips as a native dict via asyncpg — a bare string
        # here would mean the date never got JSON-encoded in the first
        # place and the column just stored serialized text.
        assert isinstance(row.after_data, dict)
        assert row.after_data["pm_due_date"] == "2026-08-01"
        assert row.after_data["cal_due_date"] == "2026-09-15"

        # Confirm via the raw driver too, independent of the ORM's own
        # JSON handling, that PostgreSQL itself accepted and stored valid
        # JSONB (a real jsonb column, containing exactly these keys).
        raw = await fresh_session.execute(
            text(
                "SELECT after_data->>'pm_due_date', after_data->>'cal_due_date', "
                "pg_typeof(after_data)::text FROM audit_logs WHERE entity_id = :eid AND action = 'create'"
            ),
            {"eid": str(equipment_id)},
        )
        pm_due, cal_due, pg_type = raw.one()
        assert pm_due == "2026-08-01"
        assert cal_due == "2026-09-15"
        assert pg_type == "jsonb"


async def test_login_succeeds_on_postgres_even_if_commit_fails(pg_client, pg_seeded_users, monkeypatch):
    # PR7-M1: best-effort protection must cover the whole persistence
    # boundary, including the commit that follows the audit SAVEPOINT — not
    # just the audit write itself. Verified against a real PostgreSQL
    # transaction/commit boundary, not just SQLite's.
    from sqlalchemy.ext.asyncio import AsyncSession

    async def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(AsyncSession, "commit", _boom)

    resp = await pg_client.post(
        "/api/v1/auth/login", json={"identifier": "ADMIN001", "password": "Password@123"}
    )
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()


# ---------------------------------------------------------------------------
# PR4: transaction-number generation, steady-state PostgreSQL behavior
# (docs/kickoffs/PR4-architecture-kickoff.md, squash commit
# 91b23b62d864edadb430d1f4335c6b77e59222f0). These exercise
# generate_transaction_no()'s real nextval()-based path directly against
# transaction_no_seq (created ad hoc by pg_transaction_seq for these tests
# — the dedicated migration tests further below prove the actual 0003
# migration file/cutover behavior).
# ---------------------------------------------------------------------------


def _split_transaction_no(value: str) -> tuple[str, str, str]:
    prefix, date_part, suffix = value.split("-")
    return prefix, date_part, suffix


async def test_transaction_no_sequence_generates_unique_monotonic_values_on_postgres(
    pg_session, pg_transaction_seq
):
    from app.crud import transaction as transaction_crud

    values = [await transaction_crud.generate_transaction_no(pg_session) for _ in range(10)]

    assert len(set(values)) == len(values), "repeated calls must never produce the same transaction_no"

    suffixes = []
    for value in values:
        prefix, date_part, suffix = _split_transaction_no(value)
        assert prefix == "TX"
        assert len(date_part) == 8 and date_part.isdigit()
        assert suffix.isdigit()
        assert len(suffix) >= 8, f"suffix {suffix!r} narrower than the 8-digit minimum (Owner Decision 2)"
        suffixes.append(int(suffix))

    assert suffixes == sorted(suffixes), "suffixes must increase monotonically"
    assert all(b > a for a, b in zip(suffixes, suffixes[1:])), "each value must be strictly greater than the last"

    # nextval() itself is non-transactional (§8 of the kickoff) and needs
    # no commit, but end the session's own implicit transaction promptly
    # rather than leaving it open until fixture teardown.
    await pg_session.rollback()


async def test_transaction_no_sequence_does_not_reset_across_date_boundary_on_postgres(
    pg_session, pg_transaction_seq, monkeypatch
):
    # Owner Decision 3: no daily reset. Simulates the calendar date
    # rolling over between two calls and asserts the numeric suffix keeps
    # counting up regardless — only the cosmetic date prefix changes.
    from app.crud import transaction as transaction_crud

    class _FixedDatetime(datetime):
        _current = datetime(2026, 7, 17)

        @classmethod
        def utcnow(cls):
            return cls._current

    monkeypatch.setattr(transaction_crud, "datetime", _FixedDatetime)

    first = await transaction_crud.generate_transaction_no(pg_session)
    _, first_date, first_suffix = _split_transaction_no(first)
    assert first_date == "20260717"

    _FixedDatetime._current = datetime(2026, 7, 18)
    second = await transaction_crud.generate_transaction_no(pg_session)
    _, second_date, second_suffix = _split_transaction_no(second)
    assert second_date == "20260718"

    assert int(second_suffix) == int(first_suffix) + 1, (
        "the numeric suffix must continue monotonically across a date boundary, not reset"
    )

    await pg_session.rollback()


async def test_concurrent_dispatch_burst_produces_unique_transaction_numbers_on_postgres(
    pg_client, pg_seeded_users, pg_transaction_seq
):
    # Simulates a routine-round burst: many concurrent dispatch requests
    # for distinct equipment. This is the core safety property PR4 exists
    # to establish — every successful dispatch must receive a unique
    # transaction_no, with zero duplicates, under real concurrency.
    headers = await _admin_headers(pg_client)

    equipment_count = 25
    qr_codes = []
    for i in range(equipment_count):
        resp = await pg_client.post(
            "/api/v1/equipment",
            headers=headers,
            json={"asset_number": f"PR4-BURST-{i:03d}", "equipment_name": "Burst Test Pump"},
        )
        assert resp.status_code == 201, resp.text
        qr_codes.append(resp.json()["qr_code_value"])

    async def _dispatch(qr: str):
        return await pg_client.post(
            "/api/v1/borrow",
            headers=headers,
            json={"equipment_qr": qr, "borrower_name": "Burst Nurse"},
        )

    responses = await asyncio.gather(*(_dispatch(qr) for qr in qr_codes))

    for resp in responses:
        assert resp.status_code == 201, resp.text

    transaction_numbers = [resp.json()["transaction_no"] for resp in responses]
    assert len(set(transaction_numbers)) == len(transaction_numbers) == equipment_count, (
        "every successful concurrent dispatch must receive a unique transaction_no"
    )
    for value in transaction_numbers:
        prefix, date_part, suffix = _split_transaction_no(value)
        assert prefix == "TX"
        assert len(date_part) == 8 and date_part.isdigit()
        assert suffix.isdigit() and len(suffix) >= 8


async def test_transaction_no_sequence_gap_after_rollback_is_accepted_on_postgres(
    pg_session, pg_transaction_seq
):
    # PostgreSQL sequences are non-transactional: nextval()'s effect is
    # never undone by a rollback. A number drawn just before a failed
    # dispatch is permanently consumed (a gap), and the sequence must
    # still advance correctly afterward rather than reuse or collide.
    from app.crud import transaction as transaction_crud

    first = await transaction_crud.generate_transaction_no(pg_session)
    await pg_session.rollback()  # simulates the rest of that dispatch failing/rolling back

    second = await transaction_crud.generate_transaction_no(pg_session)
    await pg_session.rollback()

    _, _, first_suffix = _split_transaction_no(first)
    _, _, second_suffix = _split_transaction_no(second)
    assert int(second_suffix) > int(first_suffix), "the sequence must advance despite the rollback, not reuse the value"
    assert second != first


async def test_dispatch_failure_after_transaction_no_generation_leaves_safe_gap_on_postgres(
    pg_client, pg_seeded_users, pg_transaction_seq, monkeypatch
):
    # End-to-end version of the gap test above: a real dispatch request
    # that fails *after* generate_transaction_no() has already run must
    # still (a) not corrupt equipment/business state and (b) allow a
    # subsequent, ordinary dispatch of the same equipment to succeed with
    # its own unique transaction_no.
    from app.crud import transaction as transaction_crud

    headers = await _admin_headers(pg_client)
    equipment_resp = await pg_client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "PR4-GAP-0001", "equipment_name": "Gap Test Pump"},
    )
    assert equipment_resp.status_code == 201, equipment_resp.text
    qr = equipment_resp.json()["qr_code_value"]

    original_create = transaction_crud.create
    call_count = {"n": 0}

    async def _boom_once(db, *, data):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated failure after transaction_no was already generated")
        return await original_create(db, data=data)

    monkeypatch.setattr(transaction_crud, "create", _boom_once)

    # Starlette's ServerErrorMiddleware re-raises after sending a 500
    # response; httpx's default ASGITransport re-raises that into the
    # caller. pg_client's dependency override is already active on `app`
    # (set by the pg_client fixture) -- reuse it via a second client whose
    # transport doesn't re-raise, so the 500 response itself can be
    # inspected instead of failing the test on the injected exception.
    raw_transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=raw_transport, base_url="http://test") as raw_client:
        failed = await raw_client.post(
            "/api/v1/borrow",
            headers=headers,
            json={"equipment_qr": qr, "borrower_name": "Gap Nurse"},
        )
    assert failed.status_code == 500, failed.text

    monkeypatch.undo()

    # Equipment must still be AVAILABLE (nothing committed on the failed
    # attempt) and a fresh dispatch must succeed with its own, unique,
    # non-colliding transaction_no.
    retry = await pg_client.post(
        "/api/v1/borrow",
        headers=headers,
        json={"equipment_qr": qr, "borrower_name": "Gap Nurse Retry"},
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["transaction_no"]


# ---------------------------------------------------------------------------
# PR3: migration 0002_audit_request_ids.py, exercised for real via the
# `alembic` CLI against a dedicated scratch database — not simulated by
# Base.metadata.create_all() like every other test in this suite. This is
# the only test that proves the actual migration *files* work (upgrade from
# a fresh DB, downgrade, and re-upgrade as a pre-PR3 DB catching up would).
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SCRATCH_DB_NAME = "mep_test_migration_scratch"


def _admin_dsn() -> str:
    plain = POSTGRES_TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    return plain.rsplit("/", 1)[0] + "/postgres"


def _scratch_dsn(dialect: str) -> str:
    base = POSTGRES_TEST_DATABASE_URL.replace("postgresql+asyncpg://", f"{dialect}://").rsplit("/", 1)[0]
    return f"{base}/{_SCRATCH_DB_NAME}"


async def _recreate_scratch_database() -> None:
    import asyncpg

    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB_NAME}"')
        await conn.execute(f'CREATE DATABASE "{_SCRATCH_DB_NAME}"')
    finally:
        await conn.close()


async def _drop_scratch_database() -> None:
    import asyncpg

    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB_NAME}"')
    finally:
        await conn.close()


def _run_alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\nstdout={result.stdout}\nstderr={result.stderr}"


async def _audit_logs_columns() -> set[str]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("audit_logs")})
    finally:
        await engine.dispose()


async def test_migration_0002_upgrade_downgrade_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # Fresh database: 0001 then 0002 back-to-back must succeed. (0001's
        # create_all() already reflects the current AuditLog model, so 0002
        # must tolerate the columns already existing — see its docstring.)
        _run_alembic("upgrade", "head")
        columns = await _audit_logs_columns()
        assert {"request_id", "correlation_id"} <= columns

        # Downgrade removes exactly what 0002 added, cleanly.
        _run_alembic("downgrade", "0001_initial")
        columns = await _audit_logs_columns()
        assert "request_id" not in columns
        assert "correlation_id" not in columns

        # Re-upgrade simulates a pre-PR3 database catching up.
        _run_alembic("upgrade", "head")
        columns = await _audit_logs_columns()
        assert {"request_id", "correlation_id"} <= columns
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# PR4: migration 0003_transaction_no_seq.py, exercised for real via the same
# scratch-database + `alembic` CLI pattern as 0002's round-trip test above.
# This migration's entire purpose is a *safe cutover* against pre-existing
# data, so its correctness can only be proven by actually running it against
# a populated database — Base.metadata.create_all() (used everywhere else in
# this suite) cannot simulate that.
# ---------------------------------------------------------------------------


async def _seed_transactions(transaction_nos: list[str]) -> None:
    """Inserts one Equipment row and one BorrowTransaction per given
    transaction_no, directly via the ORM against the scratch database
    (post-0002, pre/post-0003 schema — BorrowTransaction/Equipment are
    unaffected by 0003, so this is safe on either side of it)."""
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with session_maker() as session:
            equipment = Equipment(
                asset_number=f"PR4-SEED-{uuid.uuid4().hex[:10]}",
                equipment_name="Seed Equipment",
                qr_code_value=f"PR4-SEED-QR-{uuid.uuid4().hex[:10]}",
            )
            session.add(equipment)
            await session.flush()
            for i, transaction_no in enumerate(transaction_nos):
                session.add(
                    BorrowTransaction(
                        transaction_no=transaction_no,
                        equipment_id=equipment.id,
                        borrower_name=f"Seed {i}",
                        # 'returned', not 'borrowed' — avoids
                        # idx_tx_one_active_borrow's partial unique index,
                        # which only constrains status='borrowed' rows and
                        # is irrelevant to this seeding helper's purpose.
                        status="returned",
                    )
                )
            await session.commit()
            return equipment.id
    finally:
        await engine.dispose()


async def _transaction_no_seq_exists() -> bool:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT to_regclass('transaction_no_seq')"))
            return result.scalar_one() is not None
    finally:
        await engine.dispose()


async def test_migration_0003_seeds_sequence_above_populated_same_day_data():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0002_audit_request_ids")

        today = datetime.utcnow().strftime("%Y%m%d")
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")
        highest_suffix = 123456789  # 9 digits -- above the 8-digit minimum width
        seed_rows = [
            f"TX-{yesterday}-00000042",  # an earlier date
            f"TX-{today}-00000099",  # today (the deployment/migration date)
            f"TX-{today}-12345",  # valid, 5-digit (below the 8-digit minimum -- must still parse)
            f"TX-{today}-{highest_suffix}",  # valid, 9-digit (above the 8-digit minimum) -- the true max
            "TX-TEST-0001",  # malformed (matches this project's own db_session-based test fixture) -- must be skipped, not error
        ]
        await _seed_transactions(seed_rows)

        # This is the actual safety-critical step: cutover must not
        # collide with same-day (or any-day) pre-existing data.
        _run_alembic("upgrade", "head")

        assert await _transaction_no_seq_exists()

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                first_value = (await conn.execute(text("SELECT nextval('transaction_no_seq')"))).scalar_one()
            assert first_value == highest_suffix + 1, (
                "the first post-cutover value must be strictly above the highest valid historical suffix, "
                "seeded from persistent state -- never PostgreSQL's unconditional default of 1"
            )

            # Immediate post-cutover burst: further values must remain
            # strictly increasing and never collide with any pre-existing
            # transaction_no, including the malformed row and the
            # non-8-digit legacy rows.
            async with engine.begin() as conn:
                more_values = [
                    (await conn.execute(text("SELECT nextval('transaction_no_seq')"))).scalar_one()
                    for _ in range(5)
                ]
            assert more_values == sorted(more_values)
            assert len(set(more_values)) == len(more_values)
            assert min(more_values) > highest_suffix

            # The malformed row must still be present, untouched -- the
            # migration must skip it during seeding, not delete or error on it.
            session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_maker() as session:
                rows = (
                    await session.execute(
                        select(BorrowTransaction).where(BorrowTransaction.transaction_no == "TX-TEST-0001")
                    )
                ).scalars().all()
                assert len(rows) == 1

            # Exercise the real, full generate_transaction_no() code path
            # (not just raw nextval()) against this now-cutover database,
            # to prove the actual runtime generator cannot collide either.
            from app.crud import transaction as transaction_crud

            async with session_maker() as session:
                generated = await transaction_crud.generate_transaction_no(session)
            _, generated_date, generated_suffix = generated.split("-")
            assert generated_date == today
            assert int(generated_suffix) > highest_suffix
            assert len(generated_suffix) >= 8
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0003_disaster_recovery_reseed_stays_above_historical_max():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0002_audit_request_ids")
        today = datetime.utcnow().strftime("%Y%m%d")
        await _seed_transactions([f"TX-{today}-00000500"])

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            # Simulate normal operation after the initial cutover: real
            # sequence-generated values become part of "persistent state"
            # too, and must be respected by any later reseed.
            generated_values = []
            async with engine.begin() as conn:
                for _ in range(3):
                    value = (await conn.execute(text("SELECT nextval('transaction_no_seq')"))).scalar_one()
                    generated_values.append(value)
                    await conn.execute(
                        text(
                            "INSERT INTO borrow_transactions "
                            "(id, transaction_no, equipment_id, quantity, borrowed_at, "
                            "borrower_name, status) "
                            "SELECT :id, :tn, id, 1, now(), 'post-cutover', 'returned' "
                            "FROM equipment LIMIT 1"
                        ),
                        {"id": str(uuid.uuid4()), "tn": f"TX-{today}-{value:08d}"},
                    )
            highest_after_normal_ops = max(generated_values)
        finally:
            await engine.dispose()

        # Disaster: the sequence object itself is lost (e.g. a restore
        # from a backup predating it, or an accidental manual DROP).
        _run_alembic("downgrade", "0002_audit_request_ids")
        assert not await _transaction_no_seq_exists()

        # Recovery: recreating it (downgrade->upgrade reruns the exact
        # same 0003 migration code) must reseed from the CURRENT
        # historical maximum -- which now includes the sequence-generated
        # rows above, not just the original seed data.
        _run_alembic("upgrade", "head")
        assert await _transaction_no_seq_exists()

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                next_value = (await conn.execute(text("SELECT nextval('transaction_no_seq')"))).scalar_one()
            assert next_value > highest_after_normal_ops
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0003_upgrade_downgrade_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # Fresh database, no pre-existing transaction_no rows: the
        # sequence must still be created (seeded at 1, as the *result* of
        # scanning zero matching rows -- never a hardcoded default).
        _run_alembic("upgrade", "head")
        assert await _transaction_no_seq_exists()

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                first_value = (await conn.execute(text("SELECT nextval('transaction_no_seq')"))).scalar_one()
            assert first_value == 1
        finally:
            await engine.dispose()

        # Downgrade removes exactly what 0003 added, cleanly, and leaves
        # borrow_transactions/equipment rows untouched (this migration
        # never edits existing rows).
        _run_alembic("downgrade", "0002_audit_request_ids")
        assert not await _transaction_no_seq_exists()

        # Re-upgrade simulates a pre-PR4 database catching up.
        _run_alembic("upgrade", "head")
        assert await _transaction_no_seq_exists()
    finally:
        await _drop_scratch_database()
