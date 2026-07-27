"""PostgreSQL-backed integration tests for structured exception handling.

The main suite runs against SQLite, which does not enforce foreign key
constraints by default — so it cannot prove the IntegrityError SQLSTATE
classification in app.core.db_errors actually works, only that the
pre-flush existence checks in app.core.references do (those work against
any backend). These tests run against a real PostgreSQL database instead,
which does enforce FK/unique/not-null/check constraints, so the
`classify_integrity_error()` SQLSTATE mapping is exercised for real.

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
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db_errors import translate_integrity_error
from app.core.exceptions import DuplicateError, InvalidInputError
from app.core.security import hash_password
from app.crud import master_data as md_crud
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.equipment import Equipment, EquipmentStatus, EquipmentStatusHistory
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import ALL_ROLES, ROLE_ADMINISTRATOR, Role, User
# Roadmap PR7b: every dispatch now requires ward_id, so every HTTP-level
# /api/v1/borrow call in this suite needs a real ward row first --
# create_ward is the same helper test_borrow.py/test_equipment.py/
# test_exception_handling.py use (tests/conftest.py, consolidated here to
# remove a fourth near-duplicate definition).
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.postgres

# pg_seeded_users derives each user's employee_code from its role name
# (f"{role_name.upper()}001") -- Roadmap PR10 renamed the "admin" role to
# "administrator", so the seeded administrator's employee_code is now
# ADMINISTRATOR001, not ADMIN001.
ADMIN_EMPLOYEE_CODE = f"{ROLE_ADMINISTRATOR.upper()}001"

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
    resp = await client.post("/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"})
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


async def test_dispatch_with_invalid_ward_is_not_classified_as_equipment_conflict_on_postgres(
    pg_client, pg_seeded_users, pg_engine
):
    """Codex PR20 review round 1, MAJOR 3: before this fix, every
    IntegrityError from transaction_crud.create() -- including a bad
    ward_id foreign-key reference -- was blanket-mapped to 409
    EquipmentNotAvailableError ("Equipment was just borrowed by someone
    else"), which is wrong and misleading for a request that never
    conflicted with anything. A missing ward must be a distinct, safe 400
    INVALID_INPUT, exactly like every other bad-reference field in this
    codebase (see the ward/equipment tests directly above), and must leave
    no transaction, no equipment status change, and no audit record
    behind."""
    headers = await _admin_headers(pg_client)
    equipment_resp = await pg_client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "PG-BORROW-BADWARD-0001", "equipment_name": "Infusion Pump"},
    )
    assert equipment_resp.status_code == 201, equipment_resp.text
    equipment_id = equipment_resp.json()["id"]

    resp = await pg_client.post(
        "/api/v1/borrow",
        headers=headers,
        json={"equipment_id": equipment_id, "ward_id": str(uuid.uuid4()), "dispatch_type": "on_demand"},
    )
    assert resp.status_code != 409
    body = resp.json()
    assert body["code"] != "EQUIPMENT_NOT_AVAILABLE"
    assert resp.status_code == 400
    assert body["code"] == "INVALID_INPUT"

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as fresh_session:
        equipment_row = (
            await fresh_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
        ).scalar_one()
        assert equipment_row.status == EquipmentStatus.AVAILABLE_AT_POOL, "equipment status must be unchanged"

        tx_rows = (
            await fresh_session.execute(
                select(BorrowTransaction).where(BorrowTransaction.equipment_id == uuid.UUID(equipment_id))
            )
        ).scalars().all()
        assert tx_rows == [], "no transaction may be created for an invalid ward reference"

        audit_rows = (
            await fresh_session.execute(
                select(AuditLog).where(AuditLog.action == "borrow", AuditLog.entity_type == "borrow_transaction")
            )
        ).scalars().all()
        assert audit_rows == [], "no audit record may be created for an invalid ward reference"


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
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
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
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
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
    equipment_ids = []
    for i in range(equipment_count):
        resp = await pg_client.post(
            "/api/v1/equipment",
            headers=headers,
            json={"asset_number": f"PR4-BURST-{i:03d}", "equipment_name": "Burst Test Pump"},
        )
        assert resp.status_code == 201, resp.text
        equipment_ids.append(resp.json()["id"])

    ward_id = await _create_ward(pg_client, headers, "PR4-BURST-WARD")

    async def _dispatch(equipment_id: str):
        return await pg_client.post(
            "/api/v1/borrow",
            headers=headers,
            json={"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand"},
        )

    responses = await asyncio.gather(*(_dispatch(eq_id) for eq_id in equipment_ids))

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


async def test_transaction_no_generation_uses_real_sequence_not_fallback_on_postgres(
    pg_session, pg_transaction_seq
):
    # PR4-D1 (independent review, PR #13): direct proof that the
    # PostgreSQL branch actually calls nextval() rather than silently
    # falling through to the SQLite-style COUNT+LIKE fallback. No
    # BorrowTransaction row is ever inserted/committed by this test, so
    # if the fallback's COUNT-against-existing-rows logic ran here
    # instead, both calls below would see zero matching rows and return
    # the identical value ("...-00000001" both times) rather than
    # advancing.
    from app.crud import transaction as transaction_crud

    assert pg_session.get_bind().dialect.name == "postgresql"

    first = await transaction_crud.generate_transaction_no(pg_session)
    second = await transaction_crud.generate_transaction_no(pg_session)
    assert first != second

    _, _, first_suffix = _split_transaction_no(first)
    _, _, second_suffix = _split_transaction_no(second)
    assert int(second_suffix) == int(first_suffix) + 1

    await pg_session.rollback()


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
    equipment_id = equipment_resp.json()["id"]
    ward_id = await _create_ward(pg_client, headers, "PR4-GAP-WARD")

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
            json={"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand"},
        )
    assert failed.status_code == 500, failed.text

    monkeypatch.undo()

    # Equipment must still be AVAILABLE (nothing committed on the failed
    # attempt) and a fresh dispatch must succeed with its own, unique,
    # non-colliding transaction_no.
    retry = await pg_client.post(
        "/api/v1/borrow",
        headers=headers,
        json={"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand"},
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


def _run_alembic(*args: str, extra_env: dict | None = None) -> None:
    env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
    if extra_env:
        env.update(extra_env)
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
                        # CLOSED, not OPEN — avoids idx_tx_one_active_borrow's
                        # partial unique index, which only constrains
                        # status='open' rows and is irrelevant to this
                        # seeding helper's purpose.
                        status=TransactionStatus.CLOSED,
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


async def test_migration_0003_reseeds_a_preexisting_low_sequence_before_traffic():
    # PR4-M1 (independent review, PR #13): CREATE SEQUENCE IF NOT EXISTS
    # ... START WITH n is a silent no-op when the sequence already
    # exists -- PostgreSQL neither applies START WITH nor touches the
    # existing allocator state. An orphaned/restored/manually-created
    # transaction_no_seq left at a low value, still coexisting with a
    # database that thinks it's only at Alembic revision 0002, must be
    # detected and repaired by upgrade() -- not silently preserved.
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0002_audit_request_ids")

        # Manually create the sequence out-of-band, at a deliberately low
        # value -- simulating a prior partial migration attempt, a
        # manual `CREATE SEQUENCE`, or a restore from a backup that
        # predates the real historical data below. Alembic itself still
        # believes the database is at 0002; nothing about 0003 has run.
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE SEQUENCE transaction_no_seq START WITH 5"))
        finally:
            await engine.dispose()

        today = datetime.utcnow().strftime("%Y%m%d")
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")
        true_highest_suffix = 987654321  # 9 digits -- above the 8-digit minimum width
        seed_rows = [
            f"TX-{yesterday}-00000010",  # an earlier date, still above the orphaned sequence's low value
            f"TX-{today}-00000099",  # today (the deployment/migration date)
            f"TX-{today}-{true_highest_suffix}",  # valid, 9-digit -- the true max
            "TX-TEST-0001",  # malformed -- must be skipped, not error, and must not affect the computation
        ]
        await _seed_transactions(seed_rows)

        # The orphaned sequence's own low value (5) is far below every
        # seeded row -- if upgrade() only relied on CREATE SEQUENCE IF
        # NOT EXISTS, this next nextval() would reproduce an existing
        # suffix immediately.
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                first_value = (await conn.execute(text("SELECT nextval('transaction_no_seq')"))).scalar_one()
            assert first_value > true_highest_suffix, (
                "an existing, orphaned low sequence must be repaired (RESTART WITH) before any traffic "
                "reaches it -- it must never be silently left at its unsafe prior value"
            )

            # The malformed row must still be present and must not have
            # affected the repaired seed value above.
            session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_maker() as session:
                rows = (
                    await session.execute(
                        select(BorrowTransaction).where(BorrowTransaction.transaction_no == "TX-TEST-0001")
                    )
                ).scalars().all()
                assert len(rows) == 1

            # The real runtime generator must also be safe immediately
            # after this repair, not just raw nextval().
            from app.crud import transaction as transaction_crud

            async with session_maker() as session:
                generated = await transaction_crud.generate_transaction_no(session)
            _, generated_date, generated_suffix = generated.split("-")
            assert generated_date == today
            assert int(generated_suffix) > true_highest_suffix
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0003_leaves_an_already_safe_existing_sequence_untouched():
    # The repair in upgrade() must be conditional, not an unconditional
    # reset -- an existing sequence that is already safely ahead of the
    # historical maximum (e.g. from a normal prior run of this same
    # migration) must be left alone.
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0002_audit_request_ids")

        today = datetime.utcnow().strftime("%Y%m%d")
        await _seed_transactions([f"TX-{today}-00000010"])

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                # Already far above the true historical maximum (10).
                await conn.execute(text("CREATE SEQUENCE transaction_no_seq START WITH 999999"))
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                first_value = (await conn.execute(text("SELECT nextval('transaction_no_seq')"))).scalar_one()
            assert first_value == 999999, (
                "an existing sequence already safely ahead of the historical maximum must be left "
                "untouched, not unconditionally reset"
            )
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
                            "SELECT :id, :tn, id, 1, now(), 'post-cutover', 'closed' "
                            "FROM equipment LIMIT 1"
                        ),
                        {"id": str(uuid.uuid4()), "tn": f"TX-{today}-{value:08d}"},
                    )
            highest_after_normal_ops = max(generated_values)
        finally:
            await engine.dispose()

        # Roadmap PR6/PR7: downgrading to 0002 now also runs migrations
        # 0006's and 0007's downgrades, which refuse to proceed for any
        # equipment/borrow_transactions row with a NULL legacy_status (no
        # pre-migration value to reconstruct -- see those migrations'
        # docstrings). The equipment row _seed_transactions created above
        # was inserted directly via the ORM after 0006 had already run, and
        # every borrow_transactions row here (seeded already-CLOSED, or
        # inserted post-cutover after upgrading to head) was never remapped
        # by 0007 either -- neither has any such history, and this test is
        # not exercising 0006 or 0007 at all, so give both a synthetic
        # legacy_status equal to their own current status purely to satisfy
        # that precondition -- irrelevant to this test's actual subject
        # (transaction_no_seq disaster recovery).
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE equipment SET legacy_status = status"))
                await conn.execute(text("UPDATE borrow_transactions SET legacy_status = status"))
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


# ---------------------------------------------------------------------------
# PR5: migration 0004_equipment_item_no_bcm_code.py. Exercised for real via
# the same scratch-database + `alembic` CLI pattern as 0002/0003 above —
# this migration's whole point is to be non-destructive against a database
# that already has equipment/transaction rows, which
# Base.metadata.create_all() (used everywhere else in this suite) cannot
# simulate.
# ---------------------------------------------------------------------------


async def _equipment_columns() -> set[str]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("equipment")}
            )
    finally:
        await engine.dispose()


async def _equipment_indexes() -> list[dict]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_indexes("equipment"))
    finally:
        await engine.dispose()


async def test_migration_0004_preserves_existing_equipment_and_transaction_data():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # Pre-PR5 database: equipment and a completed transaction already
        # exist, seeded before item_no/bcm_code existed at all. Seeded via
        # the ORM (like _seed_transactions above) rather than raw SQL text,
        # so the status Enum column round-trips correctly.
        _run_alembic("upgrade", "0003_transaction_no_seq")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_maker() as session:
                equipment = Equipment(
                    asset_number="AST-PR5-0001", equipment_name="Pre-PR5 Pump", qr_code_value="MEP:AST-PR5-0001"
                )
                session.add(equipment)
                await session.flush()
                equipment_id = equipment.id
                session.add(
                    BorrowTransaction(
                        transaction_no="TX-PR5-0001",
                        equipment_id=equipment.id,
                        borrower_name="Pre-PR5 Borrower",
                        status="returned",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        columns = await _equipment_columns()
        assert {"item_no", "bcm_code"} <= columns

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_maker() as session:
                row = (
                    await session.execute(select(Equipment).where(Equipment.id == equipment_id))
                ).scalar_one()
                assert row.asset_number == "AST-PR5-0001"
                assert row.equipment_name == "Pre-PR5 Pump"
                assert row.item_no is None, "pre-existing equipment must not get an invented item_no"
                assert row.bcm_code is None, "pre-existing equipment must not get an invented bcm_code"

                tx_count = (
                    await session.execute(
                        select(BorrowTransaction).where(BorrowTransaction.transaction_no == "TX-PR5-0001")
                    )
                ).scalars().all()
                assert len(tx_count) == 1, "the pre-existing transaction row must survive the migration untouched"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0004_adds_unique_indexes_for_item_no_and_bcm_code():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # 0004's own index contract, tested at 0004 -- 0005 (a later
        # revision) replaces ix_equipment_bcm_code with a canonical-form
        # functional index; see test_migration_0005_replaces_bcm_code_index_
        # with_canonical_functional_index for that revision's own contract.
        _run_alembic("upgrade", "0004_equipment_item_no_bcm_code")

        indexes = await _equipment_indexes()
        by_name = {idx["name"]: idx for idx in indexes}

        assert "ix_equipment_item_no" in by_name
        assert by_name["ix_equipment_item_no"]["unique"] is True
        assert by_name["ix_equipment_item_no"]["column_names"] == ["item_no"]

        assert "ix_equipment_bcm_code" in by_name
        assert by_name["ix_equipment_bcm_code"]["unique"] is True
        assert by_name["ix_equipment_bcm_code"]["column_names"] == ["bcm_code"]

        # The trigram GIN index isn't reported by SQLAlchemy's generic
        # get_indexes() reflection (it's PostgreSQL-specific access-method
        # metadata) -- check pg_indexes directly instead.
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                exists = (
                    await conn.execute(
                        text("SELECT 1 FROM pg_indexes WHERE indexname = 'idx_equipment_bcm_trgm'")
                    )
                ).scalar_one_or_none()
                assert exists == 1, "the bcm_code trigram index must exist for responsive partial matching"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0004_rejects_duplicate_item_no_and_bcm_code_at_db_level():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO equipment "
                        "(id, asset_number, equipment_name, status, qr_code_value, metadata, item_no, bcm_code) "
                        "VALUES (:id, 'AST-PR5-0002', 'Dup Source', 'available_at_pool', 'MEP:AST-PR5-0002', '{}', "
                        "'ITEM-0001', 'BCM00001')"
                    ),
                    {"id": str(uuid.uuid4())},
                )

            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO equipment "
                            "(id, asset_number, equipment_name, status, qr_code_value, metadata, item_no) "
                            "VALUES (:id, 'AST-PR5-0003', 'Dup Item No', 'available_at_pool', 'MEP:AST-PR5-0003', '{}', "
                            "'ITEM-0001')"
                        ),
                        {"id": str(uuid.uuid4())},
                    )

            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO equipment "
                            "(id, asset_number, equipment_name, status, qr_code_value, metadata, bcm_code) "
                            "VALUES (:id, 'AST-PR5-0004', 'Dup BCM Code', 'available_at_pool', 'MEP:AST-PR5-0004', '{}', "
                            "'BCM00001')"
                        ),
                        {"id": str(uuid.uuid4())},
                    )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# PR14 reconciliation, PR5-H3R: migration 0005_identifier_hardening.py.
# Retires qr_code_value's NOT NULL constraint (See ADR-004) and adopts the
# "persist only canonical values" strategy for BCM Code / Item No (See
# ADR-002): existing data is converted to canonical form, then a CHECK
# constraint on each column proves every stored value is already
# canonical, so the plain per-column UNIQUE indexes from 0004 are already
# exactly canonical-form uniqueness -- no functional/expression index
# needed. Exercised for real via the same scratch-database + `alembic` CLI
# pattern as 0002/0003/0004 above.
# ---------------------------------------------------------------------------


async def _bcm_code_index_names() -> set[str]:
    indexes = await _equipment_indexes()
    return {idx["name"] for idx in indexes}


async def _equipment_check_constraint_names() -> set[str]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'equipment'::regclass AND contype = 'c'"
                    )
                )
            ).fetchall()
            return {r[0] for r in rows}
    finally:
        await engine.dispose()


async def test_migration_0005_upgrade_from_0004_makes_qr_code_value_nullable():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # Upgrade from the prior merged schema (0004), not a fresh head --
        # proves this migration works as an incremental step, not only on a
        # brand-new database.
        #
        # Note: this suite's 0001_initial builds its schema via
        # Base.metadata.create_all() against the *current* ORM model (see
        # 0002/0004's docstrings), so a fresh scratch database stopped at
        # 0004 already has qr_code_value nullable in the ORM's present
        # state -- this harness cannot observe the column's true pre-0005
        # NOT NULL history for a column that predates 0005. What IS
        # provable here is the forward behavior after upgrading to head.
        _run_alembic("upgrade", "0004_equipment_item_no_bcm_code")
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                # No qr_code_value supplied -- must succeed now that the
                # application no longer generates a legacy QR value.
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata) "
                        "VALUES (:id, 'AST-0005-POST', 'Post-0005', 'available_at_pool', '{}')"
                    ),
                    {"id": str(uuid.uuid4())},
                )
                row = (
                    await conn.execute(
                        text("SELECT qr_code_value FROM equipment WHERE asset_number = 'AST-0005-POST'")
                    )
                ).scalar_one()
                assert row is None
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0005_adds_canonical_check_constraints_and_keeps_plain_unique_indexes():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_bcm_code_canonical" in constraints
        assert "ck_equipment_item_no_canonical" in constraints

        # 0004's plain unique indexes are unchanged -- once the CHECK
        # constraints guarantee canonical storage, a plain per-column
        # UNIQUE index already is canonical-form uniqueness; no
        # functional/expression index is needed.
        names = await _bcm_code_index_names()
        assert "ix_equipment_bcm_code" in names
        assert "ix_equipment_item_no" in names
        assert "ix_equipment_bcm_code_canonical" not in names
    finally:
        await _drop_scratch_database()


async def test_migration_0005_check_constraint_rejects_noncanonical_bcm_direct_write():
    """Direct SQL (bypassing the application's normalize_bcm_code
    entirely) attempting to store a non-canonical bcm_code -- lowercase,
    prefixless, or with embedded whitespace -- must be rejected by the
    CHECK constraint, not silently accepted as a technically-different
    stored value."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        from sqlalchemy.exc import IntegrityError

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            for i, bad_value in enumerate(["bcm00777", "00777", "BCM 00777", "BCM"]):
                with pytest.raises(IntegrityError):
                    async with engine.begin() as conn:
                        await conn.execute(
                            text(
                                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                                "VALUES (:id, :asset, 'Noncanonical', 'available', '{}', :bcm)"
                            ),
                            {"id": str(uuid.uuid4()), "asset": f"AST-0005-NONCANON-{i}", "bcm": bad_value},
                        )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0005_check_constraint_rejects_noncanonical_item_no_direct_write():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        from sqlalchemy.exc import IntegrityError

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            for i, bad_value in enumerate([" ITEM01", "ITEM01 ", "  ITEM01  ", ""]):
                with pytest.raises(IntegrityError):
                    async with engine.begin() as conn:
                        await conn.execute(
                            text(
                                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, item_no) "
                                "VALUES (:id, :asset, 'Noncanonical', 'available', '{}', :item_no)"
                            ),
                            {"id": str(uuid.uuid4()), "asset": f"AST-0005-ITEMNC-{i}", "item_no": bad_value},
                        )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0005_unique_index_rejects_exact_canonical_duplicate_direct_write():
    """Complements the CHECK-constraint tests above: two rows that are
    ALREADY in canonical form and byte-for-byte identical are rejected by
    the plain UNIQUE index -- proving the "persist only canonical, then
    plain unique is enough" strategy actually holds end to end."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        from sqlalchemy.exc import IntegrityError

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code, item_no) "
                        "VALUES (:id, 'AST-0005-DUP-1', 'Dup Source', 'available_at_pool', '{}', 'BCM00778', 'ITEM-DUP-01')"
                    ),
                    {"id": str(uuid.uuid4())},
                )

            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                            "VALUES (:id, 'AST-0005-DUP-2', 'Dup BCM', 'available_at_pool', '{}', 'BCM00778')"
                        ),
                        {"id": str(uuid.uuid4())},
                    )

            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, item_no) "
                            "VALUES (:id, 'AST-0005-DUP-3', 'Dup Item', 'available_at_pool', '{}', 'ITEM-DUP-01')"
                        ),
                        {"id": str(uuid.uuid4())},
                    )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def _assert_migration_0005_collision_aborts(seed_sql_pairs: list[tuple[str, str]], expected_snippet: str) -> None:
    """Seeds two colliding rows at revision 0004, then attempts to
    upgrade to head and asserts it aborts clearly (non-zero exit,
    mentions the colliding value) without leaving the CHECK constraints
    behind."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0004_equipment_item_no_bcm_code")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                for asset_number, value_sql in seed_sql_pairs:
                    await conn.execute(text(value_sql), {"asset": asset_number, "id": str(uuid.uuid4())})
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort, not silently succeed, on a pre-existing collision"
        assert expected_snippet in (result.stdout + result.stderr)

        # The database must still be on 0004 -- the failed migration must
        # not have left the CHECK constraints half-applied.
        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_bcm_code_canonical" not in constraints
        assert "ck_equipment_item_no_canonical" not in constraints
    finally:
        await _drop_scratch_database()


async def test_migration_0005_aborts_on_bcm_case_collision():
    await _assert_migration_0005_collision_aborts(
        [
            (
                "AST-0005-CASE-1",
                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                "VALUES (:id, :asset, 'Collide A', 'available', '{}', 'BCM00999')",
            ),
            (
                "AST-0005-CASE-2",
                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                "VALUES (:id, :asset, 'Collide B', 'available', '{}', 'bcm00999')",
            ),
        ],
        "BCM00999",
    )


async def test_migration_0005_aborts_on_bcm_whitespace_collision():
    await _assert_migration_0005_collision_aborts(
        [
            (
                "AST-0005-WS-1",
                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                "VALUES (:id, :asset, 'Collide A', 'available', '{}', 'BCM00998')",
            ),
            (
                "AST-0005-WS-2",
                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                "VALUES (:id, :asset, 'Collide B', 'available', '{}', '  BCM00998  ')",
            ),
        ],
        "BCM00998",
    )


async def test_migration_0005_aborts_on_bcm_prefix_optional_collision():
    await _assert_migration_0005_collision_aborts(
        [
            (
                "AST-0005-PFX-1",
                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                "VALUES (:id, :asset, 'Collide A', 'available', '{}', '00997')",
            ),
            (
                "AST-0005-PFX-2",
                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                "VALUES (:id, :asset, 'Collide B', 'available', '{}', 'BCM00997')",
            ),
        ],
        "BCM00997",
    )


async def test_migration_0005_aborts_on_item_no_whitespace_collision():
    await _assert_migration_0005_collision_aborts(
        [
            (
                "AST-0005-ITEMWS-1",
                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, item_no) "
                "VALUES (:id, :asset, 'Collide A', 'available', '{}', 'ITEM-COLLIDE-01')",
            ),
            (
                "AST-0005-ITEMWS-2",
                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, item_no) "
                "VALUES (:id, :asset, 'Collide B', 'available', '{}', '  ITEM-COLLIDE-01  ')",
            ),
        ],
        "ITEM-COLLIDE-01",
    )


async def _assert_migration_0005_preflight_rejects_single_row(
    seed_asset: str, seed_sql: str, expected_snippet: str, extra_params: dict | None = None
) -> None:
    """Seeds one legacy row at revision 0004 whose value cannot be
    canonicalized at all (as opposed to colliding with another row), then
    asserts upgrading to head aborts clearly and leaves the CHECK
    constraints unapplied."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0004_equipment_item_no_bcm_code")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                params = {"asset": seed_asset, "id": str(uuid.uuid4())}
                if extra_params:
                    params.update(extra_params)
                await conn.execute(text(seed_sql), params)
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort, not silently succeed, on an uncanonicalizable value"
        assert expected_snippet in (result.stdout + result.stderr)

        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_bcm_code_canonical" not in constraints
        assert "ck_equipment_item_no_canonical" not in constraints
    finally:
        await _drop_scratch_database()


async def test_migration_0005_aborts_on_invalid_legacy_bcm_embedded_whitespace():
    """PR5-H3R-MIG: a legacy bcm_code with whitespace embedded within the
    body (not just adjacent to the prefix) cannot be canonicalized at all
    -- the migration's local _canonicalize_bcm_code must reject it during
    preflight with a clear, row-identifying error, not attempt to guess a
    canonical form or crash on the later CHECK-constraint ALTER."""
    await _assert_migration_0005_preflight_rejects_single_row(
        "AST-0005-INVALID-BCM",
        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
        "VALUES (:id, :asset, 'Invalid Legacy', 'available', '{}', 'BCM00 01')",
        "AST-0005-INVALID-BCM",
    )


async def test_migration_0005_aborts_on_invalid_legacy_bcm_prefix_only():
    await _assert_migration_0005_preflight_rejects_single_row(
        "AST-0005-PFXONLY-BCM",
        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
        "VALUES (:id, :asset, 'Prefix Only Legacy', 'available', '{}', 'BCM')",
        "AST-0005-PFXONLY-BCM",
    )


async def test_migration_0005_aborts_on_invalid_legacy_item_no_empty_after_trim():
    await _assert_migration_0005_preflight_rejects_single_row(
        "AST-0005-INVALID-ITEM",
        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, item_no) "
        "VALUES (:id, :asset, 'Invalid Legacy Item', 'available', '{}', '   ')",
        "AST-0005-INVALID-ITEM",
    )


async def test_migration_0005_aborts_on_overlength_legacy_bcm_after_canonicalization():
    """A legacy prefixless bcm_code that already fits the 64-character
    column raw can still overflow it once canonicalized (prefix added) --
    the preflight's length check must catch this and abort with a clear
    error before ever attempting the UPDATE, not surface a raw PostgreSQL
    DataError from a doomed write."""
    overlength_raw = "9" * 64  # fits raw; "BCM" + 64 chars = 67, over the column width
    await _assert_migration_0005_preflight_rejects_single_row(
        "AST-0005-OVERLEN-BCM",
        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
        "VALUES (:id, :asset, 'Overlength Legacy', 'available', '{}', :bcm)",
        "AST-0005-OVERLEN-BCM",
        extra_params={"bcm": overlength_raw},
    )


# ---------------------------------------------------------------------------
# Follow-up fix: migration 0005 previously re-trimmed the body immediately
# after stripping the "BCM" prefix, which silently absorbed a space
# directly between the prefix and the digits -- "BCM 001" was wrongly
# accepted and rewritten to "BCM001", while the runtime application
# (app.services.identifiers.normalize_bcm_code) correctly rejected the
# same input. These tests exercise the exact vectors named in that fix,
# proving the migration now agrees with the runtime: reject, never
# rewrite. See tests/identifier_vectors.py for the shared vector data
# these mirror (duplicated here, not imported, per PR5's "shared
# vectors, separate implementations" requirement -- this file must not
# import from a module that itself might import runtime code).
# ---------------------------------------------------------------------------


async def test_migration_0005_aborts_on_legacy_bcm_space_after_prefix_not_rewritten():
    """The exact regression vector: 'BCM 001' must abort the migration,
    never be silently rewritten to 'BCM001'."""
    await _assert_migration_0005_preflight_rejects_single_row(
        "AST-0005-BCM-SPACE-1",
        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
        "VALUES (:id, :asset, 'Space After Prefix', 'available', '{}', :bcm)",
        "AST-0005-BCM-SPACE-1",
        extra_params={"bcm": "BCM 001"},
    )


async def test_migration_0005_aborts_on_legacy_bcm_outer_and_prefix_space_not_rewritten():
    """' BCM 001 ' combines ordinary outer whitespace (which alone would
    be fine, see the whitespace-collision tests above) with a
    prefix-adjacent space (which is not) -- must still abort."""
    await _assert_migration_0005_preflight_rejects_single_row(
        "AST-0005-BCM-SPACE-2",
        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
        "VALUES (:id, :asset, 'Outer And Prefix Space', 'available', '{}', :bcm)",
        "AST-0005-BCM-SPACE-2",
        extra_params={"bcm": " BCM 001 "},
    )


async def test_migration_0005_aborts_on_legacy_bcm_space_within_prefix_like_text():
    """'BC M001' does not even match the "BCM" prefix (the 4th character
    is a space, not part of a valid prefix), so the whole string is
    treated as the body -- which contains whitespace and must be
    rejected, not partially matched or truncated."""
    await _assert_migration_0005_preflight_rejects_single_row(
        "AST-0005-BCM-SPACE-3",
        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
        "VALUES (:id, :asset, 'Space Within Prefix Text', 'available', '{}', :bcm)",
        "AST-0005-BCM-SPACE-3",
        extra_params={"bcm": "BC M001"},
    )


async def test_migration_0005_still_canonicalizes_valid_surrounding_whitespace():
    """Regression guard for the fix above: ordinary OUTER whitespace
    around an otherwise-clean value (no space between the prefix and the
    body) must still canonicalize normally -- the fix must not have
    become overly strict."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0004_equipment_item_no_bcm_code")

        equipment_id = str(uuid.uuid4())
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                        "VALUES (:id, 'AST-0005-VALID-WS', 'Valid Outer Whitespace', 'available', '{}', :bcm)"
                    ),
                    {"id": equipment_id, "bcm": "  BCM555  "},
                )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(text("SELECT bcm_code FROM equipment WHERE id = :id"), {"id": equipment_id})
                ).scalar_one()
                assert row == "BCM555"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0005_aborts_without_partial_rewrites_or_constraints():
    """Transaction-safety guard: when preflight rejects one row, alembic's
    transactional DDL must roll back the WHOLE attempt -- a different,
    valid-but-non-canonical row that would have been rewritten earlier in
    the same run must be found completely untouched afterward, and
    neither CHECK constraint may exist."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0004_equipment_item_no_bcm_code")

        valid_id = str(uuid.uuid4())
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                # A valid-but-non-canonical row (would normally be
                # rewritten to "BCM777" during this same upgrade).
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                        "VALUES (:id, 'AST-0005-ROLLBACK-VALID', 'Rollback Valid', 'available', '{}', 'bcm777')"
                    ),
                    {"id": valid_id},
                )
                # An uncanonicalizable row that must abort the whole run.
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata, bcm_code) "
                        "VALUES (:id, 'AST-0005-ROLLBACK-INVALID', 'Rollback Invalid', 'available', '{}', :bcm)"
                    ),
                    {"id": str(uuid.uuid4()), "bcm": "BCM 999"},
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort on the invalid row"

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(text("SELECT bcm_code FROM equipment WHERE id = :id"), {"id": valid_id})
                ).scalar_one()
                assert row == "bcm777", "the valid row must not have been partially rewritten by the aborted run"
        finally:
            await engine.dispose()

        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_bcm_code_canonical" not in constraints
        assert "ck_equipment_item_no_canonical" not in constraints
    finally:
        await _drop_scratch_database()


def test_migration_0005_does_not_import_runtime_application_modules():
    """PR5-H3R-MIG static inspection: migration 0005 must remain correct
    even if app.services.identifiers or app.core.exceptions change shape
    in a future PR, so it must not import either -- or any other
    app.* runtime module -- at all. Parses the file's own AST rather than
    grepping text, so a reformatted or aliased import can't slip past
    this check."""
    import ast

    migration_path = _BACKEND_DIR / "alembic" / "versions" / "0005_identifier_hardening.py"
    source = migration_path.read_text()
    tree = ast.parse(source, filename=str(migration_path))

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
            imported_modules.update(f"{node.module}.{alias.name}" for alias in node.names)

    app_imports = {m for m in imported_modules if m == "app" or m.startswith("app.")}
    assert not app_imports, (
        f"migration 0005 must not import any app.* runtime module, found: {sorted(app_imports)}"
    )


async def test_migration_0005_upgrade_downgrade_reupgrade_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0004_equipment_item_no_bcm_code")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        unrelated_id = str(uuid.uuid4())
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO equipment "
                        "(id, asset_number, equipment_name, status, qr_code_value, metadata, bcm_code, item_no) "
                        "VALUES (:id, 'AST-0005-ROUNDTRIP', 'Round Trip Pump', 'available', 'MEP:0005-RT', '{}', "
                        "'bcm777', '  Item-RoundTrip-01  ')"
                    ),
                    {"id": unrelated_id},
                )
                tx_id = str(uuid.uuid4())
                await conn.execute(
                    text(
                        "INSERT INTO borrow_transactions (id, transaction_no, equipment_id, quantity, "
                        "borrowed_at, borrower_name, status) "
                        "VALUES (:tx_id, 'TX-0005-ROUNDTRIP', :eq_id, 1, now(), 'Round Trip Borrower', 'returned')"
                    ),
                    {"tx_id": tx_id, "eq_id": unrelated_id},
                )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_bcm_code_canonical" in constraints
        assert "ck_equipment_item_no_canonical" in constraints

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT bcm_code, item_no FROM equipment WHERE id = :id"), {"id": unrelated_id}
                    )
                ).one()
                # Pre-existing non-canonical data was converted deterministically.
                assert row.bcm_code == "BCM777"
                assert row.item_no == "Item-RoundTrip-01"

                tx_count = (
                    await conn.execute(
                        text("SELECT count(*) FROM borrow_transactions WHERE transaction_no = 'TX-0005-ROUNDTRIP'")
                    )
                ).scalar_one()
                assert tx_count == 1, "unrelated transaction row must survive the migration untouched"
        finally:
            await engine.dispose()

        # Downgrade is safe here: no row has taken a write since upgrade,
        # so no qr_code_value is NULL yet.
        _run_alembic("downgrade", "0004_equipment_item_no_bcm_code")
        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_bcm_code_canonical" not in constraints
        assert "ck_equipment_item_no_canonical" not in constraints

        _run_alembic("upgrade", "head")
        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_bcm_code_canonical" in constraints
        assert "ck_equipment_item_no_canonical" in constraints

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                tx_count = (
                    await conn.execute(
                        text("SELECT count(*) FROM borrow_transactions WHERE transaction_no = 'TX-0005-ROUNDTRIP'")
                    )
                ).scalar_one()
                assert tx_count == 1, "unrelated transaction row must survive downgrade+re-upgrade untouched"
                eq_count = (
                    await conn.execute(text("SELECT count(*) FROM equipment WHERE id = :id"), {"id": unrelated_id})
                ).scalar_one()
                assert eq_count == 1, "unrelated equipment row must survive downgrade+re-upgrade untouched"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0005_downgrade_aborts_if_null_qr_code_value_exists():
    """Once the application has taken writes under 0005 (no qr_code_value
    populated), downgrading must fail clearly rather than silently violate
    the restored NOT NULL constraint or drop data."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, asset_number, equipment_name, status, legacy_status, metadata) "
                        # Roadmap PR6: legacy_status is set here (equal to
                        # status) purely so migration 0006's own downgrade
                        # guard -- which runs first, since 0006 now sits
                        # above 0005 in the chain -- does not itself abort
                        # before 0005's qr_code_value guard (this test's
                        # actual subject) ever gets a chance to fire.
                        "VALUES (:id, 'AST-0005-NULLQR', 'No Legacy QR', 'available_at_pool', 'available_at_pool', '{}')"
                    ),
                    {"id": str(uuid.uuid4())},
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "0004_equipment_item_no_bcm_code"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "downgrade must abort, not silently violate NOT NULL, when data would be lost"
        assert "NULL" in (result.stdout + result.stderr)
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Roadmap PR6: migration 0006_equipment_state_model.py. Collapses the legacy
# 8-value equipment.status domain to the confirmed 4-state model
# (AVAILABLE_AT_POOL, ISSUED_TO_WARD, UNAVAILABLE_DEFECTIVE, DECOMMISSIONED),
# preserving every original value in a new legacy_status column. Exercised
# for real via the same scratch-database + `alembic` CLI pattern as
# 0002-0005 above. See that migration's module docstring for the exact
# mapping table and the owner-confirmed cleaning -> AVAILABLE_AT_POOL
# retirement (this migration must NOT route cleaning through
# UNAVAILABLE_DEFECTIVE).
# ---------------------------------------------------------------------------


async def _insert_equipment_with_status(conn, asset_number: str, status: str) -> str:
    eq_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata) "
            "VALUES (:id, :asset_number, :name, :status, '{}')"
        ),
        {"id": eq_id, "asset_number": asset_number, "name": f"PR6 {status}", "status": status},
    )
    return eq_id


async def test_migration_0006_maps_every_legacy_status_and_preserves_legacy_status():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0005_identifier_hardening")

        expected = {
            "available": "available_at_pool",
            "borrowed": "issued_to_ward",
            "cleaning": "available_at_pool",
            "out_of_service": "unavailable_defective",
            "lost": "unavailable_defective",
            "pm": "unavailable_defective",
            "calibration": "unavailable_defective",
            "repair": "unavailable_defective",
        }

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        ids_by_legacy: dict[str, str] = {}
        try:
            async with engine.begin() as conn:
                for legacy_value in expected:
                    ids_by_legacy[legacy_value] = await _insert_equipment_with_status(
                        conn, f"AST-0006-{legacy_value.upper()}", legacy_value
                    )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                for legacy_value, target_value in expected.items():
                    row = (
                        await conn.execute(
                            text("SELECT status, legacy_status FROM equipment WHERE id = :id"),
                            {"id": ids_by_legacy[legacy_value]},
                        )
                    ).one()
                    assert row.status == target_value, f"{legacy_value!r} must map to {target_value!r}"
                    assert row.legacy_status == legacy_value, (
                        f"legacy_status must preserve the original {legacy_value!r} value exactly"
                    )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0006_cleaning_does_not_map_to_unavailable_defective():
    """Dedicated, standalone assertion for the owner-confirmed cleaning
    retirement -- a cleaning row must become AVAILABLE_AT_POOL, never
    UNAVAILABLE_DEFECTIVE, and never require any migration-review flag."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0005_identifier_hardening")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        eq_id = None
        try:
            async with engine.begin() as conn:
                eq_id = await _insert_equipment_with_status(conn, "AST-0006-CLEANING-ONLY", "cleaning")
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status, legacy_status FROM equipment WHERE id = :id"), {"id": eq_id}
                    )
                ).one()
                assert row.status == "available_at_pool"
                assert row.status != "unavailable_defective"
                assert row.legacy_status == "cleaning"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0006_aborts_on_unexpected_status_value():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0005_identifier_hardening")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await _insert_equipment_with_status(conn, "AST-0006-UNKNOWN", "quarantined")
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort on an unexpected status value"
        assert "quarantined" in (result.stdout + result.stderr)
    finally:
        await _drop_scratch_database()


async def test_migration_0006_aborts_without_partial_remap():
    """Transaction-safety guard, mirroring 0005's equivalent test: when
    preflight rejects one row, the whole attempt must roll back -- a
    different, validly-mappable row must be found completely untouched
    afterward, and the CHECK constraint must not exist."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0005_identifier_hardening")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        valid_id = None
        try:
            async with engine.begin() as conn:
                valid_id = await _insert_equipment_with_status(conn, "AST-0006-ROLLBACK-VALID", "available")
                await _insert_equipment_with_status(conn, "AST-0006-ROLLBACK-INVALID", "quarantined")
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort on the invalid row"

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status, legacy_status FROM equipment WHERE id = :id"), {"id": valid_id}
                    )
                ).one()
                assert row.status == "available", "the valid row must not have been partially remapped"
                assert row.legacy_status is None
        finally:
            await engine.dispose()

        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_status_four_state" not in constraints
    finally:
        await _drop_scratch_database()


async def test_migration_0006_preserves_row_count_and_unrelated_rows():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0005_identifier_hardening")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_ids = []
        try:
            async with engine.begin() as conn:
                for legacy_value in ("available", "borrowed", "cleaning", "repair"):
                    equipment_ids.append(
                        await _insert_equipment_with_status(conn, f"AST-0006-COUNT-{legacy_value}", legacy_value)
                    )
                tx_id = str(uuid.uuid4())
                await conn.execute(
                    text(
                        "INSERT INTO borrow_transactions (id, transaction_no, equipment_id, quantity, "
                        "borrowed_at, borrower_name, status) "
                        "VALUES (:tx_id, 'TX-0006-COUNT', :eq_id, 1, now(), 'PR6 Borrower', 'returned')"
                    ),
                    {"tx_id": tx_id, "eq_id": equipment_ids[0]},
                )
        finally:
            await engine.dispose()

        before_count = len(equipment_ids)

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                after_count = (
                    await conn.execute(
                        text("SELECT count(*) FROM equipment WHERE asset_number LIKE 'AST-0006-COUNT-%'")
                    )
                ).scalar_one()
                assert after_count == before_count, "row count must be unchanged by the remap"

                tx_count = (
                    await conn.execute(
                        text("SELECT count(*) FROM borrow_transactions WHERE transaction_no = 'TX-0006-COUNT'")
                    )
                ).scalar_one()
                assert tx_count == 1, "unrelated transaction row must survive the migration untouched"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0006_adds_four_state_check_constraint():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_status_four_state" in constraints

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await _insert_equipment_with_status(conn, "AST-0006-DIRECT-OLD-VALUE", "repair")
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0006_downgrade_reconstructs_original_statuses_including_cleaning():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0005_identifier_hardening")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        ids_by_legacy: dict[str, str] = {}
        try:
            async with engine.begin() as conn:
                for legacy_value in ("available", "borrowed", "cleaning", "repair"):
                    ids_by_legacy[legacy_value] = await _insert_equipment_with_status(
                        conn, f"AST-0006-DOWNGRADE-{legacy_value}", legacy_value
                    )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "0005_identifier_hardening")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                columns = await conn.run_sync(
                    lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("equipment")}
                )
                assert "legacy_status" not in columns, "legacy_status must be dropped by a full downgrade"

                for legacy_value, eq_id in ids_by_legacy.items():
                    row = (
                        await conn.execute(text("SELECT status FROM equipment WHERE id = :id"), {"id": eq_id})
                    ).scalar_one()
                    assert row == legacy_value, f"downgrade must restore the original {legacy_value!r} value"
        finally:
            await engine.dispose()

        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_status_four_state" not in constraints

        # Re-upgrade round trip: the same rows must remap identically again.
        _run_alembic("upgrade", "head")
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status, legacy_status FROM equipment WHERE id = :id"),
                        {"id": ids_by_legacy["cleaning"]},
                    )
                ).one()
                assert row.status == "available_at_pool"
                assert row.legacy_status == "cleaning"
        finally:
            await engine.dispose()
        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_status_four_state" in constraints
    finally:
        await _drop_scratch_database()


async def test_migration_0006_downgrade_fails_for_rows_with_null_legacy_status():
    """A row created after this migration's upgrade (the 4-state-only
    application never writes an 8-state legacy value) has no legacy_status
    to reconstruct from -- downgrade must fail clearly rather than guess."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata) "
                        "VALUES (:id, 'AST-0006-POST-CUTOVER', 'Post-Cutover Pump', 'available_at_pool', '{}')"
                    ),
                    {"id": str(uuid.uuid4())},
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "0005_identifier_hardening"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "downgrade must abort, not guess, when legacy_status is NULL"

        # No partial restoration: the CHECK constraint must still exist and
        # the row must still read the 4-state value it had before the
        # aborted downgrade attempt.
        constraints = await _equipment_check_constraint_names()
        assert "ck_equipment_status_four_state" in constraints

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status FROM equipment WHERE asset_number = 'AST-0006-POST-CUTOVER'")
                    )
                ).scalar_one()
                assert row == "available_at_pool"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Roadmap PR7: migration 0007_transaction_lifecycle.py. Exercised
# for real via the same scratch-database + `alembic` CLI pattern as
# 0002-0006 above -- mirrors 0006's equipment-status test suite structure
# for the analogous borrow_transactions.status collapse.
# ---------------------------------------------------------------------------


async def _borrow_transactions_check_constraint_names() -> set[str]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'borrow_transactions'::regclass AND contype = 'c'"
                    )
                )
            ).fetchall()
            return {r[0] for r in rows}
    finally:
        await engine.dispose()


async def _insert_borrow_transaction_with_status(
    conn, equipment_id: str, transaction_no: str, status: str, borrower_name: str = "PR7 Borrower"
) -> str:
    tx_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO borrow_transactions (id, transaction_no, equipment_id, quantity, "
            "borrowed_at, borrower_name, status) "
            "VALUES (:id, :tn, :eq_id, 1, now(), :borrower_name, :status)"
        ),
        {"id": tx_id, "tn": transaction_no, "eq_id": equipment_id, "borrower_name": borrower_name, "status": status},
    )
    return tx_id


async def _borrow_transactions_status_column_length() -> int | None:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT character_maximum_length FROM information_schema.columns "
                        "WHERE table_name = 'borrow_transactions' AND column_name = 'status'"
                    )
                )
            ).one()
            return row[0]
    finally:
        await engine.dispose()


async def _insert_bare_equipment(conn, asset_number: str) -> str:
    equipment_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata) "
            "VALUES (:id, :asset_number, 'PR7 Test Equipment', 'available_at_pool', '{}')"
        ),
        {"id": equipment_id, "asset_number": asset_number},
    )
    return equipment_id


async def test_migration_0007_upgrade_downgrade_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # Fresh database, no pre-existing borrow_transactions rows: the
        # CHECK constraint must still be added (result of scanning zero
        # rows -- never skipped just because there was nothing to remap).
        _run_alembic("upgrade", "head")
        constraints = await _borrow_transactions_check_constraint_names()
        assert "ck_borrow_transactions_status_open_closed" in constraints

        # Downgrade removes exactly what 0007 added, cleanly, on an empty table.
        _run_alembic("downgrade", "0006_equipment_state_model")
        constraints = await _borrow_transactions_check_constraint_names()
        assert "ck_borrow_transactions_status_open_closed" not in constraints

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                columns = await conn.run_sync(
                    lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("borrow_transactions")}
                )
                assert "legacy_status" not in columns, "legacy_status must be dropped by a full downgrade"
        finally:
            await engine.dispose()

        # Re-upgrade simulates a pre-PR7 database catching up.
        _run_alembic("upgrade", "head")
        constraints = await _borrow_transactions_check_constraint_names()
        assert "ck_borrow_transactions_status_open_closed" in constraints
    finally:
        await _drop_scratch_database()


async def test_migration_0007_maps_every_legacy_status_and_preserves_legacy_status():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        ids_by_legacy: dict[str, str] = {}
        try:
            async with engine.begin() as conn:
                for legacy_value in ("borrowed", "returned", "overdue"):
                    equipment_id = await _insert_bare_equipment(conn, f"AST-0007-{legacy_value}")
                    ids_by_legacy[legacy_value] = await _insert_borrow_transaction_with_status(
                        conn, equipment_id, f"TX-0007-{legacy_value}", legacy_value
                    )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        expected = {"borrowed": "open", "returned": "closed", "overdue": "open"}
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                for legacy_value, target_value in expected.items():
                    row = (
                        await conn.execute(
                            text("SELECT status, legacy_status FROM borrow_transactions WHERE id = :id"),
                            {"id": ids_by_legacy[legacy_value]},
                        )
                    ).one()
                    assert row.status == target_value, f"{legacy_value!r} must remap to {target_value!r}"
                    assert row.legacy_status == legacy_value, "the exact original value must be preserved"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0007_aborts_on_unexpected_status_value():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-UNKNOWN")
                await _insert_borrow_transaction_with_status(conn, equipment_id, "TX-0007-UNKNOWN", "unknownx")
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort on an unexpected status value"
        assert "unknownx" in (result.stdout + result.stderr)
    finally:
        await _drop_scratch_database()


async def test_migration_0007_partial_unique_index_uses_open_predicate():
    """The "at most one OPEN transaction per equipment" guard must follow
    the renamed status value -- proven by inserting two OPEN rows for the
    same equipment (rejected) and two CLOSED rows for the same equipment
    (allowed, since only OPEN rows are constrained)."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-INDEX")
                await _insert_borrow_transaction_with_status(conn, equipment_id, "TX-0007-INDEX-1", "closed")
                await _insert_borrow_transaction_with_status(conn, equipment_id, "TX-0007-INDEX-2", "closed")
        finally:
            await engine.dispose()

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-INDEX-OPEN")
                await _insert_borrow_transaction_with_status(conn, equipment_id, "TX-0007-INDEX-OPEN-1", "open")
        finally:
            await engine.dispose()

        from sqlalchemy.exc import IntegrityError

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await _insert_borrow_transaction_with_status(
                        conn, equipment_id, "TX-0007-INDEX-OPEN-2", "open"
                    )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0007_downgrade_fails_for_rows_with_null_legacy_status():
    """A row created after this migration's upgrade (the OPEN/CLOSED-only
    application never writes a pre-PR7 legacy value) has no legacy_status
    to reconstruct from -- downgrade must fail clearly rather than guess."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-POST-CUTOVER")
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-POST-CUTOVER", "open"
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "0006_equipment_state_model"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "downgrade must abort, not guess, when legacy_status is NULL"

        # No partial restoration: the CHECK constraint must still exist and
        # the row must still read the value it had before the aborted
        # downgrade attempt.
        constraints = await _borrow_transactions_check_constraint_names()
        assert "ck_borrow_transactions_status_open_closed" in constraints

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT status FROM borrow_transactions WHERE transaction_no = 'TX-0007-POST-CUTOVER'"
                        )
                    )
                ).scalar_one()
                assert row == "open"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0007_status_column_is_varchar_10_on_a_fresh_database():
    """Fresh-schema outcome: a scratch database that has never run any
    migration before, taken straight to head, must end up with
    borrow_transactions.status as VARCHAR(10) -- the width the current ORM
    model (TransactionStatusType(length=10)) declares (Codex PR7a review
    round 1, "Migration 0007 schema convergence")."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")
        assert await _borrow_transactions_status_column_length() == 10
    finally:
        await _drop_scratch_database()


async def test_migration_0007_status_column_converges_to_varchar_10_from_pre_pr7_width():
    """Upgraded-schema outcome: a database that ran migration 0001 before
    this PR's app-code change got a physical VARCHAR(20) status column
    (the pre-PR7 ORM model declared String(20)). Simulate that starting
    condition explicitly, then prove migration 0007's upgrade narrows the
    column to VARCHAR(10) regardless -- converging to the same physical
    width as a database created fresh under today's code (Codex PR7a
    review round 1, "Migration 0007 schema convergence")."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        # Simulate the pre-PR7 physical schema: 0001 ran under the old
        # String(20) model, so status was VARCHAR(20) at this point in a
        # database's real history (0001's create_all() uses whatever
        # Base.metadata looked like when 0001 first ran -- see
        # docs/TECH_DEBT.md TD-002).
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE borrow_transactions ALTER COLUMN status TYPE VARCHAR(20)"))
        finally:
            await engine.dispose()
        assert await _borrow_transactions_status_column_length() == 20

        _run_alembic("upgrade", "head")
        assert await _borrow_transactions_status_column_length() == 10
    finally:
        await _drop_scratch_database()


async def test_migration_0007_downgrade_restores_varchar_20():
    """Downgrade must restore the previous physical type, not just the
    previous values -- the pre-PR7 ORM model declared status as
    String(20) (Codex PR7a review round 1, "Migration 0007 schema
    convergence")."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")
        assert await _borrow_transactions_status_column_length() == 10

        _run_alembic("downgrade", "0006_equipment_state_model")
        assert await _borrow_transactions_status_column_length() == 20
    finally:
        await _drop_scratch_database()


async def test_migration_0007_future_open_collision_preflight_aborts_before_any_write():
    """'borrowed' and 'overdue' are both OPEN-equivalent under the target
    mapping, but the pre-migration unique index only ever guarded
    'borrowed' rows -- a database could legally hold one 'borrowed' row
    and one 'overdue' row for the same equipment simultaneously.
    Remapping both to 'open' would collide on the new unique index;
    migration 0007 must instead detect this before writing anything and
    name the affected equipment_id in its error (Codex PR7a review
    round 1, "Future-OPEN collision preflight")."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-COLLISION")
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-COLLISION-1", "borrowed"
                )
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-COLLISION-2", "overdue"
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort when an equipment has 2+ OPEN-equivalent rows"
        assert equipment_id in (result.stdout + result.stderr), "the error must name the offending equipment_id"

        # No partial write: both rows must still carry their original,
        # unmapped legacy values, and the CHECK constraint this migration
        # adds only after successful remap must not exist.
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT status FROM borrow_transactions WHERE equipment_id = :eq_id ORDER BY status"
                        ),
                        {"eq_id": equipment_id},
                    )
                ).fetchall()
                assert sorted(r[0] for r in rows) == ["borrowed", "overdue"]
        finally:
            await engine.dispose()
        constraints = await _borrow_transactions_check_constraint_names()
        assert "ck_borrow_transactions_status_open_closed" not in constraints
    finally:
        await _drop_scratch_database()


async def test_migration_0007_future_open_collision_preflight_allows_a_single_borrowed_row():
    """Sanity check for the preflight added above: an equipment with
    exactly one OPEN-equivalent row (the common case) must remap and
    upgrade normally -- the new check must not reject legitimate,
    non-colliding data."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-NO-COLLISION")
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-NO-COLLISION", "borrowed"
                )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status FROM borrow_transactions WHERE equipment_id = :eq_id"),
                        {"eq_id": equipment_id},
                    )
                ).one()
                assert row.status == "open"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0007_future_open_collision_preflight_detects_borrowed_plus_open():
    """Codex PR7a review round 2, MAJOR 1: round 1's collision preflight
    only counted 'borrowed'/'overdue' rows, missing the case where an
    equipment already has a genuinely 'open' row (e.g. a table created
    fresh via 0001's create_all()) *and* a legacy 'borrowed' row for the
    same equipment -- both would collapse to 'open' and collide on the
    new unique index. Must be caught before any row is modified."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-COLLISION-BO")
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-COLLISION-BO-1", "borrowed"
                )
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-COLLISION-BO-2", "open"
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort when an equipment has a 'borrowed' + an 'open' row"
        assert equipment_id in (result.stdout + result.stderr), "the error must name the offending equipment_id"

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT status FROM borrow_transactions WHERE equipment_id = :eq_id ORDER BY status"
                        ),
                        {"eq_id": equipment_id},
                    )
                ).fetchall()
                assert sorted(r[0] for r in rows) == ["borrowed", "open"]
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0007_future_open_collision_preflight_detects_overdue_plus_open():
    """Same as the 'borrowed' + 'open' case above, but for 'overdue' + 'open'
    -- the pre-migration unique index never constrained either value, so
    this combination was always legally possible pre-migration."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-COLLISION-OO")
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-COLLISION-OO-1", "overdue"
                )
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-COLLISION-OO-2", "open"
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort when an equipment has an 'overdue' + an 'open' row"
        assert equipment_id in (result.stdout + result.stderr), "the error must name the offending equipment_id"
    finally:
        await _drop_scratch_database()


async def test_migration_0007_future_open_collision_preflight_detects_multiple_open_rows():
    """Two rows already 'open' for the same equipment: the *genuine*
    pre-PR7 unique index (predicate status = 'borrowed') never constrained
    'open' at all, so this fixture was legally constructible on a real
    pre-PR7 production database. This test's own scratch database can't
    reproduce that starting point via a plain "upgrade to 0006" -- because
    0001_initial.py builds its schema from *today's* Base.metadata
    (docs/TECH_DEBT.md TD-002), idx_tx_one_active_borrow is already
    open-predicated even at revision 0006 here. The genuine pre-PR7 index
    is simulated explicitly (mirroring how the schema-convergence tests
    above simulate the pre-PR7 VARCHAR(20) column width), which is exactly
    what lets the fixture -- two already-'open' rows for one equipment --
    be constructed at all. Migration 0007 must still catch it: both rows
    would otherwise coexist post-migration in violation of 'at most one
    OPEN transaction per equipment'."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        try:
            async with engine.begin() as conn:
                # Simulate the genuine pre-PR7 index (see docstring above).
                await conn.execute(text("DROP INDEX IF EXISTS idx_tx_one_active_borrow"))
                await conn.execute(
                    text(
                        "CREATE UNIQUE INDEX idx_tx_one_active_borrow ON borrow_transactions "
                        "(equipment_id) WHERE status = 'borrowed'"
                    )
                )
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-COLLISION-OPEN2")
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-COLLISION-OPEN2-1", "open"
                )
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-COLLISION-OPEN2-2", "open"
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "upgrade must abort when an equipment has two pre-existing 'open' rows"
        assert equipment_id in (result.stdout + result.stderr), "the error must name the offending equipment_id"
    finally:
        await _drop_scratch_database()


async def test_migration_0007_future_open_collision_preflight_allows_a_single_open_row():
    """Sanity check: an equipment with exactly one pre-existing 'open' row
    (the common case for a table created fresh at 0001) must remap and
    upgrade normally."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-NO-COLLISION-OPEN")
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-NO-COLLISION-OPEN", "open"
                )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status, legacy_status FROM borrow_transactions WHERE equipment_id = :eq_id"),
                        {"eq_id": equipment_id},
                    )
                ).one()
                assert row.status == "open"
                assert row.legacy_status == "open", "compatibility marker must equal the row's own status"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0007_preexisting_open_row_survives_upgrade_and_downgrade():
    """Codex PR7a review round 2, MAJOR 2: a row already 'open' before
    this migration ran has no real pre-PR7 legacy value, but round 1 left
    its legacy_status NULL, which made downgrade permanently impossible
    for that database even with zero genuinely new writes. It must now
    get a compatibility marker (legacy_status = its own status, never a
    fabricated legacy value like 'borrowed') and survive a full
    upgrade -> downgrade round trip."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        tx_id = None
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-PREEXIST-OPEN")
                tx_id = await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-PREEXIST-OPEN", "open"
                )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status, legacy_status FROM borrow_transactions WHERE id = :id"),
                        {"id": tx_id},
                    )
                ).one()
                assert row.status == "open"
                # No fabrication: the compatibility marker is the row's own
                # status, never a value from the real legacy domain.
                assert row.legacy_status == "open"
                assert row.legacy_status not in ("borrowed", "returned", "overdue")
        finally:
            await engine.dispose()

        _run_alembic("downgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status FROM borrow_transactions WHERE id = :id"),
                        {"id": tx_id},
                    )
                ).one()
                assert row.status == "open", "downgrade must restore the row to its true pre-migration state"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0007_preexisting_closed_row_survives_upgrade_and_downgrade():
    """Same as the 'open' case above, but for a pre-existing 'closed' row."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        equipment_id = None
        tx_id = None
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-PREEXIST-CLOSED")
                tx_id = await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-PREEXIST-CLOSED", "closed"
                )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status, legacy_status FROM borrow_transactions WHERE id = :id"),
                        {"id": tx_id},
                    )
                ).one()
                assert row.status == "closed"
                assert row.legacy_status == "closed"
                assert row.legacy_status not in ("borrowed", "returned", "overdue")
        finally:
            await engine.dispose()

        _run_alembic("downgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status FROM borrow_transactions WHERE id = :id"),
                        {"id": tx_id},
                    )
                ).one()
                assert row.status == "closed", "downgrade must restore the row to its true pre-migration state"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0007_mixed_legacy_and_target_domain_rows_upgrade_and_downgrade():
    """A single migration run covering both populations at once: one row
    with a genuine legacy value ('borrowed') and one row already in the
    target domain ('closed') for two different equipment. Both must
    upgrade correctly (distinct legacy_status semantics) and both must
    independently survive a downgrade back to their own true
    pre-migration value."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        legacy_equipment_id = None
        legacy_tx_id = None
        target_equipment_id = None
        target_tx_id = None
        try:
            async with engine.begin() as conn:
                legacy_equipment_id = await _insert_bare_equipment(conn, "AST-0007-MIXED-LEGACY")
                legacy_tx_id = await _insert_borrow_transaction_with_status(
                    conn, legacy_equipment_id, "TX-0007-MIXED-LEGACY", "borrowed"
                )
                target_equipment_id = await _insert_bare_equipment(conn, "AST-0007-MIXED-TARGET")
                target_tx_id = await _insert_borrow_transaction_with_status(
                    conn, target_equipment_id, "TX-0007-MIXED-TARGET", "closed"
                )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                legacy_row = (
                    await conn.execute(
                        text("SELECT status, legacy_status FROM borrow_transactions WHERE id = :id"),
                        {"id": legacy_tx_id},
                    )
                ).one()
                assert legacy_row.status == "open"
                assert legacy_row.legacy_status == "borrowed", "genuine preserved legacy value"

                target_row = (
                    await conn.execute(
                        text("SELECT status, legacy_status FROM borrow_transactions WHERE id = :id"),
                        {"id": target_tx_id},
                    )
                ).one()
                assert target_row.status == "closed"
                assert target_row.legacy_status == "closed", "synthetic compatibility marker, not a fabricated legacy value"
        finally:
            await engine.dispose()

        _run_alembic("downgrade", "0006_equipment_state_model")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                legacy_row = (
                    await conn.execute(
                        text("SELECT status FROM borrow_transactions WHERE id = :id"),
                        {"id": legacy_tx_id},
                    )
                ).one()
                assert legacy_row.status == "borrowed", "the genuine legacy row restores to its real original value"

                target_row = (
                    await conn.execute(
                        text("SELECT status FROM borrow_transactions WHERE id = :id"),
                        {"id": target_tx_id},
                    )
                ).one()
                assert target_row.status == "closed", "the pre-existing-target row restores to its true prior state"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0007_downgrade_still_fails_for_genuinely_new_post_upgrade_row():
    """Codex PR7a review round 2, MAJOR 2: the compatibility-marker policy
    must not weaken the fail-closed guard for rows that did not exist when
    migration 0007 ran at all -- a row inserted by the OPEN/CLOSED-only
    application after upgrade never writes legacy_status, so it is
    genuinely unreconstructable and downgrade must still abort for it,
    exactly as it did before this round's fix."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0007-GENUINELY-NEW")
                await _insert_borrow_transaction_with_status(
                    conn, equipment_id, "TX-0007-GENUINELY-NEW", "open"
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "0006_equipment_state_model"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "downgrade must still abort for a row created after upgrade, with no legacy_status"
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Roadmap PR7b: migration 0008_dispatch_fields.py. Exercised for real via the
# same scratch-database + `alembic` CLI pattern as 0002-0007 above -- this
# migration is purely additive (no legacy-value remap), so these tests focus
# on: the new columns/constraints landing correctly, historical data being
# left untouched (not fabricated or auto-assigned), the CHECK constraints
# actually rejecting invalid combinations, and the downgrade guard.
# ---------------------------------------------------------------------------


async def _borrow_transactions_columns() -> set[str]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("borrow_transactions")}
            )
    finally:
        await engine.dispose()


async def _insert_ward(conn, code: str) -> str:
    ward_id = str(uuid.uuid4())
    await conn.execute(
        text("INSERT INTO wards (id, code, name) VALUES (:id, :code, :code)"),
        {"id": ward_id, "code": code},
    )
    return ward_id


async def _insert_pre_0008_borrow_transaction(
    conn,
    equipment_id: str,
    transaction_no: str,
    *,
    ward_id: str | None = None,
    borrower_name: str,
    due_at=None,
    quantity: int = 1,
    status: str = "closed",
) -> str:
    """Inserts a row using only the columns that genuinely exist at
    revision 0007 -- no dispatch_type/routine_round, borrower_name always
    supplied (it is still NOT NULL at this point). Used only against a
    database whose schema has been reconstructed to the real pre-0008
    shape (see test_migration_0008_upgrade_against_reconstructed_
    production_schema_preserves_data_and_converges) -- inserting through
    this helper against a schema that still has dispatch_type/routine_round
    would silently prove nothing about the real migration path."""
    tx_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO borrow_transactions (id, transaction_no, equipment_id, quantity, "
            "borrowed_at, due_at, borrower_name, ward_id, status) "
            "VALUES (:id, :tn, :eq_id, :quantity, now(), :due_at, :borrower_name, :ward_id, :status)"
        ),
        {
            "id": tx_id,
            "tn": transaction_no,
            "eq_id": equipment_id,
            "quantity": quantity,
            "due_at": due_at,
            "borrower_name": borrower_name,
            "ward_id": ward_id,
            "status": status,
        },
    )
    return tx_id


async def _insert_borrow_transaction_full(
    conn,
    equipment_id: str,
    transaction_no: str,
    *,
    ward_id: str | None = None,
    borrower_name: str | None = "PR7b Borrower",
    due_at=None,
    quantity: int = 1,
    dispatch_type: str | None = None,
    routine_round: str | None = None,
    status: str = "closed",
) -> str:
    tx_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO borrow_transactions (id, transaction_no, equipment_id, quantity, "
            "borrowed_at, due_at, borrower_name, ward_id, dispatch_type, routine_round, status) "
            "VALUES (:id, :tn, :eq_id, :quantity, now(), :due_at, :borrower_name, :ward_id, "
            ":dispatch_type, :routine_round, :status)"
        ),
        {
            "id": tx_id,
            "tn": transaction_no,
            "eq_id": equipment_id,
            "quantity": quantity,
            "due_at": due_at,
            "borrower_name": borrower_name,
            "ward_id": ward_id,
            "dispatch_type": dispatch_type,
            "routine_round": routine_round,
            "status": status,
        },
    )
    return tx_id


async def test_migration_0008_upgrade_against_reconstructed_production_schema_preserves_data_and_converges():
    """Codex PR20 review round 1, MAJOR 2: the previous version of this
    test inserted "historical" rows after `_run_alembic("upgrade",
    "0007_transaction_lifecycle")`, but TD-002 (docs/TECH_DEBT.md) means
    0001_initial.py builds its schema from *today's* live Base.metadata --
    so that "0007" database already had dispatch_type/routine_round
    columns and a nullable borrower_name from 0001 onward, which real
    production history at revision 0007 never had. That is not a
    production-like starting state.

    This version reconstructs the actual pre-0008 production schema by
    running 0008's own real downgrade() -- raw ALTER TABLE DDL, written
    with no dependency on ORM metadata (see that migration's docstring) --
    which is the only way to arrive at a schema shape that genuinely
    matches "only migrations through 0007 have ever run here", independent
    of TD-002. Full flow: upgrade to head (through 0007) -> downgrade to
    0007 (reconstructs the real pre-0008 shape) -> insert representative
    historical rows against that reconstructed schema -> upgrade to 0008
    -> verify ADD COLUMN/DROP NOT NULL/CHECK enforcement/historical
    preservation -> downgrade -> upgrade again -> compare the resulting
    schema against the genuinely fresh-head snapshot taken at the very
    start -> confirm every row, historical and unrelated, survived the
    whole round trip unchanged.
    """
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # Baseline: a genuinely fresh `upgrade head` schema, captured before
        # any downgrade/reconstruction happens on this database.
        _run_alembic("upgrade", "head")
        fresh_head_columns = await _borrow_transactions_columns()
        fresh_head_constraints = await _borrow_transactions_check_constraint_names()

        # Reconstruct the real pre-0008 production schema via 0008's own
        # downgrade() DDL (not a hand-rolled guess in this test file).
        _run_alembic("downgrade", "0007_transaction_lifecycle")
        pre_0008_columns = await _borrow_transactions_columns()
        assert "dispatch_type" not in pre_0008_columns
        assert "routine_round" not in pre_0008_columns

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                nullable = (
                    await conn.execute(
                        text(
                            "SELECT is_nullable FROM information_schema.columns "
                            "WHERE table_name = 'borrow_transactions' AND column_name = 'borrower_name'"
                        )
                    )
                ).scalar_one()
                assert nullable == "NO", "reconstructed pre-0008 schema must have borrower_name NOT NULL"
        finally:
            await engine.dispose()

        # Representative historical rows against the reconstructed schema:
        # one with a NULL ward_id (pre-PR7b rows never had one), plus an
        # unrelated row that this migration must never touch.
        historical_due_at = datetime(2026, 1, 5, 9, 30)
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0008-PROD-HIST")
                historical_id = await _insert_pre_0008_borrow_transaction(
                    conn,
                    equipment_id,
                    "TX-0008-PROD-HIST",
                    ward_id=None,
                    borrower_name="Pre-PR7b Nurse",
                    due_at=historical_due_at,
                    quantity=3,
                )
                unrelated_equipment_id = await _insert_bare_equipment(conn, "AST-0008-PROD-UNRELATED")
                unrelated_id = await _insert_pre_0008_borrow_transaction(
                    conn, unrelated_equipment_id, "TX-0008-PROD-UNRELATED", borrower_name="Unrelated Nurse"
                )
        finally:
            await engine.dispose()

        # The real 0008 upgrade, against the real pre-0008 schema.
        _run_alembic("upgrade", "head")

        columns = await _borrow_transactions_columns()
        assert {"dispatch_type", "routine_round"} <= columns, "0008 must ADD COLUMN dispatch_type/routine_round"

        constraints = await _borrow_transactions_check_constraint_names()
        assert {
            "ck_borrow_transactions_dispatch_type",
            "ck_borrow_transactions_routine_round",
            "ck_borrow_transactions_routine_round_consistency",
        } <= constraints

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                nullable = (
                    await conn.execute(
                        text(
                            "SELECT is_nullable FROM information_schema.columns "
                            "WHERE table_name = 'borrow_transactions' AND column_name = 'borrower_name'"
                        )
                    )
                ).scalar_one()
                assert nullable == "YES", "0008 must DROP NOT NULL on borrower_name"

                row = (
                    await conn.execute(
                        text(
                            "SELECT borrower_name, due_at, quantity, dispatch_type, routine_round, ward_id "
                            "FROM borrow_transactions WHERE id = :id"
                        ),
                        {"id": historical_id},
                    )
                ).one()
                assert row.borrower_name == "Pre-PR7b Nurse", "historical borrower_name must not be erased"
                assert row.due_at == historical_due_at, "historical due_at must not be erased"
                assert row.quantity == 3, "historical quantity must not be erased"
                assert row.dispatch_type is None, "a pre-PR7b row has no reliable dispatch_type -- must stay NULL"
                assert row.routine_round is None
                assert row.ward_id is None, "migration 0008 must never fabricate a ward_id for a historical row"

                unrelated_row = (
                    await conn.execute(
                        text("SELECT borrower_name, quantity FROM borrow_transactions WHERE id = :id"),
                        {"id": unrelated_id},
                    )
                ).one()
                assert unrelated_row.borrower_name == "Unrelated Nurse", "an unrelated historical row must survive"
                assert unrelated_row.quantity == 1
        finally:
            await engine.dispose()

        # The CHECK constraints are actually enforced against this
        # upgraded-from-production database, not merely present.
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            with pytest.raises(Exception):
                async with engine.begin() as conn:
                    await _insert_borrow_transaction_full(
                        conn,
                        equipment_id,
                        "TX-0008-PROD-BAD",
                        dispatch_type="on_demand",
                        routine_round="06:00",
                    )
        finally:
            await engine.dispose()

        # Downgrade, then upgrade again, and confirm the resulting schema
        # converges on the exact same fresh-head schema captured at the
        # start -- and that both rows survived the entire round trip.
        _run_alembic("downgrade", "0007_transaction_lifecycle")
        _run_alembic("upgrade", "head")

        reconverged_columns = await _borrow_transactions_columns()
        reconverged_constraints = await _borrow_transactions_check_constraint_names()
        assert reconverged_columns == fresh_head_columns
        assert reconverged_constraints == fresh_head_constraints

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT borrower_name, due_at, quantity FROM borrow_transactions WHERE id = :id"),
                        {"id": historical_id},
                    )
                ).one()
                assert row.borrower_name == "Pre-PR7b Nurse"
                assert row.due_at == historical_due_at
                assert row.quantity == 3

                unrelated_row = (
                    await conn.execute(
                        text("SELECT borrower_name FROM borrow_transactions WHERE id = :id"), {"id": unrelated_id}
                    )
                ).one()
                assert unrelated_row.borrower_name == "Unrelated Nurse"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0008_check_constraint_rejects_invalid_dispatch_type_and_round_combinations():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0008-CHK")
                ward_id = await _insert_ward(conn, "W-0008-CHK")

            # on_demand + a routine_round value: rejected by the consistency CHECK.
            with pytest.raises(Exception):
                async with engine.begin() as conn:
                    await _insert_borrow_transaction_full(
                        conn,
                        equipment_id,
                        "TX-0008-BAD-1",
                        ward_id=ward_id,
                        dispatch_type="on_demand",
                        routine_round="06:00",
                    )

            # routine_round dispatch_type with no round value: rejected.
            with pytest.raises(Exception):
                async with engine.begin() as conn:
                    await _insert_borrow_transaction_full(
                        conn,
                        equipment_id,
                        "TX-0008-BAD-2",
                        ward_id=ward_id,
                        dispatch_type="routine_round",
                        routine_round=None,
                    )

            # an unrecognized dispatch_type value: rejected by the domain CHECK.
            with pytest.raises(Exception):
                async with engine.begin() as conn:
                    await _insert_borrow_transaction_full(
                        conn,
                        equipment_id,
                        "TX-0008-BAD-3",
                        ward_id=ward_id,
                        dispatch_type="urgent",
                    )

            # an unrecognized routine_round value: rejected by the domain CHECK.
            with pytest.raises(Exception):
                async with engine.begin() as conn:
                    await _insert_borrow_transaction_full(
                        conn,
                        equipment_id,
                        "TX-0008-BAD-4",
                        ward_id=ward_id,
                        dispatch_type="routine_round",
                        routine_round="09:00",
                    )

            # the two valid combinations must both succeed.
            async with engine.begin() as conn:
                await _insert_borrow_transaction_full(
                    conn, equipment_id, "TX-0008-OK-1", ward_id=ward_id, dispatch_type="on_demand"
                )
                await _insert_borrow_transaction_full(
                    conn,
                    equipment_id,
                    "TX-0008-OK-2",
                    ward_id=ward_id,
                    dispatch_type="routine_round",
                    routine_round="11:00",
                )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0008_downgrade_round_trip_and_fresh_upgraded_schema_converge():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # Fresh database, no pre-existing rows: upgrade adds everything...
        _run_alembic("upgrade", "head")
        columns = await _borrow_transactions_columns()
        assert {"dispatch_type", "routine_round"} <= columns
        constraints = await _borrow_transactions_check_constraint_names()
        assert {
            "ck_borrow_transactions_dispatch_type",
            "ck_borrow_transactions_routine_round",
            "ck_borrow_transactions_routine_round_consistency",
        } <= constraints

        # ...downgrade removes exactly what 0008 added, cleanly, on an empty table...
        _run_alembic("downgrade", "0007_transaction_lifecycle")
        columns = await _borrow_transactions_columns()
        assert "dispatch_type" not in columns
        assert "routine_round" not in columns
        constraints = await _borrow_transactions_check_constraint_names()
        assert "ck_borrow_transactions_dispatch_type" not in constraints
        assert "ck_borrow_transactions_routine_round" not in constraints
        assert "ck_borrow_transactions_routine_round_consistency" not in constraints

        # ...and re-upgrade simulates a pre-PR7b database catching up, landing
        # on the exact same schema a genuinely fresh `upgrade head` produces
        # (TD-002 schema-convergence property this migration's docstring
        # documents).
        _run_alembic("upgrade", "head")
        columns_after_reupgrade = await _borrow_transactions_columns()
        assert columns_after_reupgrade == columns | {"dispatch_type", "routine_round"}
        constraints_after_reupgrade = await _borrow_transactions_check_constraint_names()
        assert {
            "ck_borrow_transactions_dispatch_type",
            "ck_borrow_transactions_routine_round",
            "ck_borrow_transactions_routine_round_consistency",
        } <= constraints_after_reupgrade
    finally:
        await _drop_scratch_database()


async def test_migration_0008_downgrade_fails_closed_when_a_row_has_null_borrower_name():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                equipment_id = await _insert_bare_equipment(conn, "AST-0008-NULLBN")
                ward_id = await _insert_ward(conn, "W-0008-NULLBN")
                # A dispatch created "after" this migration's upgrade, under
                # the new contract that no longer supplies borrower_name.
                await _insert_borrow_transaction_full(
                    conn,
                    equipment_id,
                    "TX-0008-NULLBN",
                    ward_id=ward_id,
                    borrower_name=None,
                    dispatch_type="on_demand",
                )
        finally:
            await engine.dispose()

        env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "0007_transaction_lifecycle"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0, "downgrade must abort when a row has a NULL borrower_name"
        assert "borrower_name" in (result.stdout + result.stderr)
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Roadmap PR8A (docs/design/PR8_IMPLEMENTATION_PLAN.md; docs/audits/
# 04-consolidated-implementation-plan.md Part C P0 / Backend Audit Finding
# 14.1 Critical): atomic-receipt concurrency guard. Two or more concurrent
# POST /api/v1/return/{id} requests for the SAME open transaction must resolve
# to exactly one winner (200, status closed) and N-1 losers (409, Roadmap
# PR8C: RECEIPT_RACE_LOST for a genuine race loss, TRANSACTION_ALREADY_RETURNED
# for a genuine sequential repeat), with the losers producing ZERO side effects:
# no equipment status change, no equipment_status_history row, no audit row,
# no overwrite of the winner's receipt fields.
#
# Only a real PostgreSQL database with real per-request connections can prove
# this: the guard is a conditional `UPDATE ... WHERE status = 'open'` decided
# by affected-row count (app.crud.transaction.close), and PostgreSQL's row
# locking under READ COMMITTED is what makes "exactly one UPDATE matches"
# true. SQLite's single-connection test path can only prove the rowcount logic
# sequentially (tests/test_borrow.py::
# test_repository_close_second_call_on_closed_row_reports_loss_and_preserves_winner),
# never the race itself -- mirroring how the dispatch-side guard's real proof
# lives in test_concurrent_dispatch_burst_produces_unique_transaction_numbers_
# on_postgres above, not in the SQLite suite.
# ---------------------------------------------------------------------------


async def _dispatch_one_open_transaction(pg_client, headers, *, asset_number: str, ward_code: str):
    """Creates one piece of equipment, dispatches it on-demand to a fresh
    ward, and returns (transaction_id, equipment_id) for an OPEN transaction
    ready to be raced on by concurrent receipts."""
    eq_resp = await pg_client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": asset_number, "equipment_name": "Receipt Race Pump"},
    )
    assert eq_resp.status_code == 201, eq_resp.text
    equipment_id = eq_resp.json()["id"]

    ward_id = await _create_ward(pg_client, headers, ward_code)

    borrow_resp = await pg_client.post(
        "/api/v1/borrow",
        headers=headers,
        json={"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand"},
    )
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx = borrow_resp.json()
    assert tx["status"] == "open"
    assert tx["equipment"]["status"] == "issued_to_ward"
    return tx["id"], equipment_id


# Codex PR26 review round 1, HIGH 1: pg_engine (fixture above) does not
# override SQLAlchemy's default AsyncAdaptedQueuePool sizing (pool_size=5,
# max_overflow=10 -- 15 connections total), and every concurrent HTTP request
# in the burst below holds one connection for its full duration (pg_client's
# override_get_db opens one session per request). Synchronizing more parties
# than that would risk a pool-exhaustion deadlock (a party can't reach the
# barrier without first acquiring a connection); this cap keeps the
# synchronized group comfortably under capacity, with headroom for pg_session
# and other fixture connections, while still forcing genuine contention on
# the conditional UPDATE for every concurrency level in the required matrix.
_RECEIPT_RACE_BARRIER_CAP = 10


@pytest.mark.parametrize("concurrency", [1, 2, 5, 10, 50])
async def test_concurrent_receipt_burst_produces_exactly_one_winner_on_postgres(
    pg_client, pg_seeded_users, pg_transaction_seq, pg_session, concurrency, monkeypatch
):
    """Roadmap PR8A core safety property, across the required matrix
    (1 / 2 / 5 / 10 / 50 concurrent receipts for one transaction): exactly one
    request wins (200, closed), the rest get 409 (Roadmap PR8C:
    RECEIPT_RACE_LOST for a genuine race loss, TRANSACTION_ALREADY_RETURNED
    for a genuine sequential repeat -- see the loser-code assertions below),
    and persistent database state -- not just the HTTP responses -- shows the
    receipt happened exactly once, with the winner's own payload persisted.

    Codex PR26 review round 1, HIGH 1: asyncio.gather() alone only starts the
    HTTP requests concurrently -- it does not guarantee more than one of them
    actually reaches the vulnerable window (having read status == OPEN, not
    yet having raced the conditional UPDATE) at the same time. Without a
    synchronization point, the whole burst could legitimately resolve
    sequentially -- each request's own initial SELECT already observing the
    previous request's committed CLOSED, so every "loser" is rejected by the
    Case A fast-path in app.services.borrow_service.return_equipment() and
    the conditional UPDATE/rowcount guard this test exists to prove is never
    actually raced. The barrier below forces a bounded group of concurrent
    requests to all reach transaction_crud.close() -- i.e. to have all passed
    the initial OPEN read -- before any of them is allowed to proceed into
    the real conditional UPDATE against real PostgreSQL. The wrapper still
    calls the unmodified production transaction_crud.close(); only the
    timing is constrained, nothing about the DB result or rowcount is mocked
    (see the app.crud.transaction.create() wrapping pattern used elsewhere in
    this file, e.g. test_dispatch_failure_after_transaction_no_generation_
    leaves_safe_gap_on_postgres, for the same call-the-real-function style).
    """
    from app.crud import transaction as transaction_crud

    headers = await _admin_headers(pg_client)
    tx_id, equipment_id = await _dispatch_one_open_transaction(
        pg_client,
        headers,
        asset_number=f"PR8A-RCPT-{concurrency:03d}",
        ward_code=f"PR8A-RCPT-WARD-{concurrency:03d}",
    )

    barrier_size = min(concurrency, _RECEIPT_RACE_BARRIER_CAP)
    barrier = asyncio.Barrier(barrier_size)
    entrants = {"n": 0}
    original_close = transaction_crud.close

    # Roadmap PR8C, Codex review round 1, MEDIUM 2: identify -- not just
    # count -- which specific requests actually crossed the barrier, so the
    # assertions below can be scoped to that exact subset instead of
    # inferring it from timing. `kwargs["notes"]` is each request's own
    # unique marker (see `_receipt` below), captured here before
    # `transaction_crud.close()`'s own `notes` handling runs, so it always
    # equals the raw marker string.
    synced_markers: list[str] = []

    async def _synchronized_close(db, tx, **kwargs):
        # Synchronous check-and-increment: no `await` between reading and
        # updating entrants["n"], so this is atomic under asyncio's
        # cooperative scheduling -- exactly `barrier_size` calls (the first
        # to arrive) wait, matching the barrier's party count exactly, so it
        # always releases cleanly with no leftover waiters.
        entrants["n"] += 1
        seat = entrants["n"]
        if seat <= barrier_size:
            synced_markers.append(kwargs.get("notes"))
            await barrier.wait()
        return await original_close(db, tx, **kwargs)

    monkeypatch.setattr(transaction_crud, "close", _synchronized_close)

    # Codex PR26 review round 1, MEDIUM 2: an identical payload across every
    # request cannot prove the persisted/response outcome is specifically the
    # *winner's* -- any request's fields would look the same. Each request
    # instead carries a unique marker in `notes`, so after the race we can
    # assert that only the winning request's marker was ever persisted, and
    # every loser's marker is absent (i.e. no loser wrote anything).
    async def _receipt(marker: str):
        return await pg_client.post(
            f"/api/v1/return/{tx_id}", headers=headers, json={"receipt_outcome": "usable", "notes": marker}
        )

    # Zero-padded to a fixed width: an unpadded "race-marker-1" would be a
    # literal substring of "race-marker-13"/"...-19" etc, so a marker
    # `in`-containment check against the wrong index could pass by accident
    # once concurrency reaches double digits. Equal-width numeric suffixes
    # can only be substrings of each other by being identical.
    markers = [f"race-marker-{i:03d}" for i in range(concurrency)]
    responses = await asyncio.gather(*(_receipt(marker) for marker in markers))
    statuses = [r.status_code for r in responses]

    # --- HTTP-level: exactly one winner, the rest are clean 409s -----------
    assert statuses.count(200) == 1, f"expected exactly one 200 winner, got statuses={statuses}"
    assert statuses.count(409) == concurrency - 1, f"expected {concurrency - 1} 409 losers, got statuses={statuses}"
    assert set(statuses) <= {200, 409}, f"no other status is acceptable, got {statuses}"

    winner_index = next(i for i, r in enumerate(responses) if r.status_code == 200)
    winner = responses[winner_index]
    winner_marker = markers[winner_index]
    assert winner.json()["status"] == "closed", "the winning receipt response must report the transaction closed"
    assert winner_marker in (winner.json()["notes"] or ""), (
        "the winning response must reflect its own request's marker, not a stale/mixed value"
    )

    # Roadmap PR8C: every loser here reached transaction_crud.close() at all
    # (i.e. entered `entrants`), which only happens after this specific
    # request's own read already observed the transaction as OPEN -- so
    # every one of them is a genuine race loss (Case B), never a sequential
    # repeat (Case A), and must get RECEIPT_RACE_LOST. This is deterministic
    # whenever `barrier_size == concurrency` (concurrency <= the pool-bound
    # cap below): asyncio.Barrier(barrier_size) only ever releases once
    # exactly `barrier_size` calls reach it, so if this test passes at all
    # (doesn't hang), every one of the `concurrency` requests necessarily
    # called close() and raced together at the barrier. Above the cap
    # (concurrency == 50, barrier_size fixed at 10), the connection pool
    # (15 total) queues most of the extra requests, so some of them
    # legitimately observe an already-CLOSED row at their own read and take
    # the Case A path instead -- both codes are valid there.
    if concurrency <= _RECEIPT_RACE_BARRIER_CAP:
        for loser in (r for r in responses if r.status_code == 409):
            assert loser.json()["code"] == "RECEIPT_RACE_LOST", (
                "every synchronized loser at or under the barrier cap is a genuine race loss, never a "
                "sequential repeat"
            )
    else:
        # Codex review round 1, MEDIUM 2: a loose "either code is acceptable
        # for every loser" check does not prove the barrier-synchronized
        # requests actually reached and raced the real conditional UPDATE --
        # a test with a broken/no-op barrier could still pass it. Scope the
        # strong assertion to exactly the requests `_synchronized_close`
        # recorded as having crossed the barrier (`synced_markers`), using
        # each request's own unique marker to correlate it back to its
        # response, rather than relying on response order or timing.
        assert len(synced_markers) == barrier_size, (
            f"expected exactly {barrier_size} requests to reach the barrier and be recorded, "
            f"got {len(synced_markers)}"
        )
        marker_to_response = dict(zip(markers, responses))
        synced_responses = [marker_to_response[marker] for marker in synced_markers]
        for r in synced_responses:
            assert r.status_code in (200, 409), (
                f"a barrier-synchronized request must resolve to either the winner (200) or a conflict (409), "
                f"got {r.status_code}"
            )
        race_lost_count = sum(
            1 for r in synced_responses if r.status_code == 409 and r.json()["code"] == "RECEIPT_RACE_LOST"
        )
        # Exactly one request wins overall; at most one of the barrier-synced
        # requests can be that winner, so at least `barrier_size - 1` of them
        # must have lost specifically through the conditional-UPDATE race
        # (RECEIPT_RACE_LOST) -- proving the barrier actually forced genuine
        # contention among this subset, not merely that some 409 happened.
        assert race_lost_count >= barrier_size - 1, (
            f"expected at least {barrier_size - 1} of the {barrier_size} barrier-synchronized requests to lose "
            f"via RECEIPT_RACE_LOST (proving they raced the real conditional UPDATE), got {race_lost_count}"
        )

        # Every loser overall (synced or queued behind the connection pool)
        # must still use one of the two documented conflict codes.
        for loser in (r for r in responses if r.status_code == 409):
            assert loser.json()["code"] in {"RECEIPT_RACE_LOST", "TRANSACTION_ALREADY_RETURNED"}, (
                f"unexpected error code for a receipt-burst loser above the barrier cap: {loser.json()['code']!r}"
            )

    # --- Persistent database state: the receipt happened EXACTLY once ------
    # Fresh snapshot: end any implicit transaction on this observer session so
    # the SELECTs below see everything the winning request committed.
    await pg_session.rollback()

    tx_row = (
        await pg_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx_id)))
    ).scalar_one()
    assert tx_row.status == TransactionStatus.CLOSED, "the transaction must be closed exactly once"
    assert tx_row.returned_at is not None
    assert tx_row.condition_on_return == "usable", "only the winner's outcome may be persisted"
    assert tx_row.received_by_user_id is not None

    # The response body must match the refreshed, persisted row exactly --
    # not merely "some" 200 response with plausible-looking fields.
    assert winner.json()["receipt_outcome"] == tx_row.condition_on_return
    # Roadmap PR8B Codex review round 1, finding 2: a receipt under the
    # current contract must never populate the legacy field, even under
    # real concurrency.
    assert winner.json()["legacy_condition_on_return"] is None
    assert winner.json()["notes"] == tx_row.notes

    assert winner_marker in (tx_row.notes or ""), "the persisted row must carry the winner's own marker"
    for i, other_marker in enumerate(markers):
        if i != winner_index:
            assert other_marker not in (tx_row.notes or ""), (
                f"loser marker {other_marker!r} must never be persisted -- only the winner ({winner_marker!r}) may write"
            )

    audit_rows = (
        await pg_session.execute(
            select(AuditLog).where(
                AuditLog.action == "return",
                AuditLog.entity_type == "borrow_transaction",
                AuditLog.entity_id == uuid.UUID(tx_id),
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 1, f"exactly one 'return' audit row must exist, found {len(audit_rows)}"

    receipt_history_rows = (
        await pg_session.execute(
            select(EquipmentStatusHistory).where(
                EquipmentStatusHistory.equipment_id == uuid.UUID(equipment_id),
                EquipmentStatusHistory.from_status == EquipmentStatus.ISSUED_TO_WARD.value,
            )
        )
    ).scalars().all()
    assert len(receipt_history_rows) == 1, (
        f"exactly one receipt (issued_to_ward -> ...) status-history row must exist, found {len(receipt_history_rows)}"
    )

    tx_count_for_equipment = (
        await pg_session.execute(
            select(func.count())
            .select_from(BorrowTransaction)
            .where(BorrowTransaction.equipment_id == uuid.UUID(equipment_id))
        )
    ).scalar_one()
    assert tx_count_for_equipment == 1, (
        "exactly one transaction row must exist for this equipment -- no duplicate receipt row was created"
    )

    equipment_row = (
        await pg_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
    ).scalar_one()
    assert equipment_row.status == EquipmentStatus.AVAILABLE_AT_POOL, (
        "the equipment must reflect exactly one receipt transition (available condition -> AVAILABLE_AT_POOL)"
    )

    await pg_session.rollback()


# ---------------------------------------------------------------------------
# Roadmap PR9A: concurrent ward-correction requests for the SAME transaction,
# all racing from the SAME originally-read ward_id, must resolve to exactly
# one winner (200, the corrected ward persisted) and N-1 losers (409
# WARD_CORRECTION_CONFLICT), with the losers producing ZERO side effects: no
# overwrite of the winner's ward_id, no audit row. Mirrors the receipt-race
# burst test above (Roadmap PR8A/PR8C) -- same conditional-UPDATE-decided-by-
# affected-rowcount shape (app.crud.transaction.correct_ward), applied to a
# different column with no lifecycle involvement.
#
# Only a real PostgreSQL database with real per-request connections can prove
# this, for the same reason as the receipt-race test: PostgreSQL's row
# locking under READ COMMITTED is what makes "exactly one UPDATE matches"
# true under genuine concurrency. SQLite's single-connection test path can
# only prove the rowcount logic sequentially
# (tests/test_ward_correction.py::
# test_repository_correct_ward_second_call_on_stale_read_reports_conflict).
# ---------------------------------------------------------------------------

# Same rationale as _RECEIPT_RACE_BARRIER_CAP above: pg_engine's default
# connection pool holds 15 connections total (pool_size=5 + max_overflow=10),
# and every concurrent HTTP request in the burst holds one for its duration.
# Kept comfortably under that cap, with headroom for pg_session and other
# fixture connections.
_WARD_CORRECTION_BARRIER_CAP = 10


@pytest.mark.parametrize("concurrency", [2, 5, 10])
async def test_concurrent_ward_correction_produces_exactly_one_winner_on_postgres(
    pg_client, pg_seeded_users, pg_transaction_seq, pg_session, concurrency, monkeypatch
):
    """Roadmap PR9A core concurrency safety property: N concurrent requests
    each attempting to correct the same transaction's ward -- all reading the
    same original ward_id -- must produce exactly one winner and N-1
    deterministic conflicts, never a silently-accepted lost update.
    """
    assert concurrency <= _WARD_CORRECTION_BARRIER_CAP
    from app.crud import transaction as transaction_crud

    headers = await _admin_headers(pg_client)
    tx_id, _equipment_id = await _dispatch_one_open_transaction(
        pg_client,
        headers,
        asset_number=f"PR9A-WC-{concurrency:03d}",
        ward_code=f"PR9A-O-{concurrency:02d}",
    )

    # Each concurrent request targets a distinct destination ward, so the
    # persisted winner can be identified unambiguously afterward -- an
    # identical target across every request could not prove *which* request's
    # write actually landed (same rationale as the receipt-race test's unique
    # per-request `notes` marker). Ward.code is String(20) -- kept short.
    target_ward_ids = [
        await _create_ward(pg_client, headers, f"PR9A-T-{concurrency:02d}-{i:02d}") for i in range(concurrency)
    ]

    barrier = asyncio.Barrier(concurrency)
    original_correct_ward = transaction_crud.correct_ward

    async def _synchronized_correct_ward(db, tx, **kwargs):
        # Forces every one of the `concurrency` requests to have already
        # completed its own read of the transaction (app.services.
        # borrow_service.correct_ward's get_by_id + same-ward check) before
        # any of them is allowed to proceed into the real conditional UPDATE
        # -- otherwise asyncio.gather() alone does not guarantee more than
        # one request actually reaches the vulnerable window at once (same
        # reasoning as the receipt-race test's barrier).
        await barrier.wait()
        return await original_correct_ward(db, tx, **kwargs)

    monkeypatch.setattr(transaction_crud, "correct_ward", _synchronized_correct_ward)

    async def _correct(ward_id: str, marker: str):
        return await pg_client.post(
            f"/api/v1/transactions/{tx_id}/correct-ward",
            headers=headers,
            json={"ward_id": ward_id, "reason": f"race-marker-{marker}"},
        )

    markers = [f"{i:03d}" for i in range(concurrency)]
    responses = await asyncio.gather(
        *(_correct(ward_id, marker) for ward_id, marker in zip(target_ward_ids, markers))
    )
    statuses = [r.status_code for r in responses]

    assert statuses.count(200) == 1, f"expected exactly one 200 winner, got statuses={statuses}"
    assert statuses.count(409) == concurrency - 1, f"expected {concurrency - 1} 409 losers, got statuses={statuses}"
    assert set(statuses) <= {200, 409}, f"no other status is acceptable, got {statuses}"

    # Every loser must be the ward-correction-specific conflict code -- never
    # a receipt-flow code (Roadmap PR8C's RECEIPT_RACE_LOST/
    # TRANSACTION_ALREADY_RETURNED), and never a silent 200 masking a lost
    # update.
    for r in responses:
        if r.status_code == 409:
            assert r.json()["code"] == "WARD_CORRECTION_CONFLICT", (
                f"unexpected error code for a ward-correction-burst loser: {r.json()['code']!r}"
            )

    winner_index = next(i for i, r in enumerate(responses) if r.status_code == 200)
    winner = responses[winner_index]
    winner_ward_id = target_ward_ids[winner_index]
    assert winner.json()["ward_id"] == winner_ward_id, (
        "the winning response must reflect its own request's target ward"
    )

    # --- Persistent database state: the correction happened EXACTLY once ---
    await pg_session.rollback()

    tx_row = (
        await pg_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx_id)))
    ).scalar_one()
    assert str(tx_row.ward_id) == winner_ward_id, "the persisted ward_id must match the winner's target, not a loser's"

    audit_rows = (
        await pg_session.execute(
            select(AuditLog).where(
                AuditLog.action == "ward_correction",
                AuditLog.entity_type == "borrow_transaction",
                AuditLog.entity_id == uuid.UUID(tx_id),
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 1, f"exactly one 'ward_correction' audit row must exist, found {len(audit_rows)}"

    audit_row = audit_rows[0]
    assert audit_row.after_data["ward_id"] == winner_ward_id, (
        "the audit row's recorded after-value must match the committed winner"
    )
    assert audit_row.before_data["ward_id"] != winner_ward_id, (
        "the audit row's recorded before-value must be the original ward, never a loser's target"
    )
    for i, ward_id in enumerate(target_ward_ids):
        if i != winner_index:
            assert audit_row.after_data["ward_id"] != ward_id, (
                "the audit row must never record a loser's target ward as the applied correction"
            )


# ---------------------------------------------------------------------------
# Roadmap PR10: migration 0009_role_consolidation.py, exercised for real via
# the same scratch-database + `alembic` CLI pattern as 0002-0008 above. This
# migration is not mechanical (see its own docstring) -- these tests prove
# every one of its fail-closed guarantees: safe auto-mapping, the
# ambiguous-role manifest mechanism (missing/invalid/incomplete), no user
# deletion, no silent privilege change, and a lossless downgrade round trip.
# ---------------------------------------------------------------------------

_MEP_PR10_ROLE_MAPPING_ENV = "MEP_PR10_ROLE_MAPPING"


def _run_alembic_allow_failure(*args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": _scratch_dsn("postgresql+asyncpg")}
    env.pop(_MEP_PR10_ROLE_MAPPING_ENV, None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


async def _insert_role_row(conn, name: str, permissions: dict | None = None) -> str:
    role_id = str(uuid.uuid4())
    await conn.execute(
        text("INSERT INTO roles (id, name, permissions) VALUES (:id, :name, CAST(:permissions AS jsonb))"),
        {"id": role_id, "name": name, "permissions": json.dumps(permissions or {})},
    )
    return role_id


async def _insert_legacy_user_row(conn, employee_code: str, role_id: str) -> str:
    user_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO users (id, employee_code, full_name, email, password_hash, role_id, is_active) "
            "VALUES (:id, :employee_code, :full_name, :email, :password_hash, :role_id, true)"
        ),
        {
            "id": user_id,
            "employee_code": employee_code,
            "full_name": f"Test {employee_code}",
            "email": f"{employee_code.lower()}@mep-hospital-test.dev",
            "password_hash": hash_password("Password@123"),
            "role_id": role_id,
        },
    )
    return user_id


async def _role_names() -> set[str]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT name FROM roles"))
            return {row[0] for row in result.all()}
    finally:
        await engine.dispose()


async def _user_count() -> int:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT count(*) FROM users"))
            return result.scalar_one()
    finally:
        await engine.dispose()


async def _role_name_for_employee_code(employee_code: str) -> str:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT roles.name FROM users JOIN roles ON users.role_id = roles.id "
                    "WHERE users.employee_code = :code"
                ),
                {"code": employee_code},
            )
            return result.scalar_one()
    finally:
        await engine.dispose()


async def _legacy_role_name_column_value(employee_code: str) -> str | None:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT legacy_role_name FROM users WHERE employee_code = :code"), {"code": employee_code}
            )
            return result.scalar_one()
    finally:
        await engine.dispose()


async def _user_id_for_employee_code(employee_code: str) -> str:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT id FROM users WHERE employee_code = :code"), {"code": employee_code}
            )
            return str(result.scalar_one())
    finally:
        await engine.dispose()


async def _set_user_role_directly(employee_code: str, role_name: str) -> None:
    """Simulates a legitimate post-upgrade role change made through the
    ordinary application API (POST/PATCH /api/v1/users) -- a plain
    role_id UPDATE, nothing migration-specific. Used only to prove
    downgrade() detects and refuses to overwrite this kind of change."""
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = :role_name) "
                    "WHERE employee_code = :code"
                ),
                {"role_name": role_name, "code": employee_code},
            )
    finally:
        await engine.dispose()


def _stringify_uuids(row: dict) -> dict:
    """asyncpg returns uuid columns as uuid.UUID objects via raw text()
    queries -- normalize to str (preserving None, e.g. a deliberately
    NULL user_id) so callers can compare against the plain str ids the
    other helpers in this file already return."""
    return {
        key: (str(value) if key in ("user_id", "entity_id") and value is not None else value)
        for key, value in row.items()
    }


async def _role_migration_audit_rows(entity_id: str | None = None, action: str | None = None) -> list[dict]:
    """action=None returns rows for BOTH directions (role_migration_upgrade
    and role_migration_downgrade) -- pass one of those two literal strings
    to see only that direction's provenance."""
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            query = (
                "SELECT user_id, entity_id, action, before_data, after_data, correlation_id FROM audit_logs "
                "WHERE action = ANY(:actions)"
            )
            actions = [action] if action is not None else ["role_migration_upgrade", "role_migration_downgrade"]
            params: dict = {"actions": actions}
            if entity_id is not None:
                query += " AND entity_id = :entity_id"
                params["entity_id"] = entity_id
            result = await conn.execute(text(query), params)
            return [_stringify_uuids(dict(row._mapping)) for row in result.all()]
    finally:
        await engine.dispose()


async def _user_role_migration_rows(revision: str = "0009_role_consolidation") -> list[dict]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT user_id, revision, legacy_role, legacy_role_id, migrated_role, migrated_role_id "
                    "FROM user_role_migrations WHERE revision = :revision"
                ),
                {"revision": revision},
            )
            rows = [_stringify_uuids(dict(row._mapping)) for row in result.all()]
            for row in rows:
                row["legacy_role_id"] = str(row["legacy_role_id"])
                row["migrated_role_id"] = str(row["migrated_role_id"])
            return rows
    finally:
        await engine.dispose()


async def _role_snapshot_rows(revision: str = "0009_role_consolidation") -> list[dict]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT legacy_role_id, legacy_role_name, legacy_role_permissions "
                    "FROM role_migration_snapshots WHERE revision = :revision"
                ),
                {"revision": revision},
            )
            rows = [dict(row._mapping) for row in result.all()]
            for row in rows:
                row["legacy_role_id"] = str(row["legacy_role_id"])
            return rows
    finally:
        await engine.dispose()


async def _role_row_by_id(role_id: str) -> dict | None:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT id, name, permissions FROM roles WHERE id = :id"), {"id": role_id}
            )
            row = result.mappings().one_or_none()
            if row is None:
                return None
            row = dict(row)
            row["id"] = str(row["id"])
            return row
    finally:
        await engine.dispose()


async def _all_role_rows() -> list[dict]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT id, name, permissions FROM roles ORDER BY name"))
            rows = [dict(row._mapping) for row in result.all()]
            for row in rows:
                row["id"] = str(row["id"])
            return rows
    finally:
        await engine.dispose()


async def _user_role_id(employee_code: str) -> str:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT role_id FROM users WHERE employee_code = :code"), {"code": employee_code}
            )
            return str(result.scalar_one())
    finally:
        await engine.dispose()


async def _table_exists(table_name: str) -> bool:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT to_regclass(:name)"), {"name": table_name})
            return result.scalar_one() is not None
    finally:
        await engine.dispose()


async def _ownership_rows(revision: str = "0009_role_consolidation") -> list[dict]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT role_id, role_name, existed_before_upgrade, created_by_migration, "
                    "pre_upgrade_permissions FROM confirmed_role_ownership WHERE revision = :revision"
                ),
                {"revision": revision},
            )
            rows = [dict(row._mapping) for row in result.all()]
            for row in rows:
                row["role_id"] = str(row["role_id"])
            return rows
    finally:
        await engine.dispose()


async def _user_row(employee_code: str) -> dict:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, full_name, email, password_hash, is_active FROM users "
                    "WHERE employee_code = :code"
                ),
                {"code": employee_code},
            )
            return dict(result.mappings().one())
    finally:
        await engine.dispose()


async def test_migration_0009_safe_auto_map_upgrades_admin_and_viewer_roles():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            viewer_role_id = await _insert_role_row(conn, "viewer")
            await _insert_legacy_user_row(conn, "SAFEADMIN01", admin_role_id)
            await _insert_legacy_user_row(conn, "SAFEVIEWER1", viewer_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")

        assert await _role_name_for_employee_code("SAFEADMIN01") == "administrator"
        assert await _role_name_for_employee_code("SAFEVIEWER1") == "read_only"

        names = await _role_names()
        assert names == {"administrator", "equipment_pool_staff", "read_only"}, (
            f"legacy roles must be fully removed once no user references them, got {names}"
        )

        # Provenance: legacy_role_name records the exact pre-migration value.
        assert await _legacy_role_name_column_value("SAFEADMIN01") == "admin"
        assert await _legacy_role_name_column_value("SAFEVIEWER1") == "viewer"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_ambiguous_role_without_manifest_aborts_and_changes_nothing():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "AMBIGUOUS01", bme_role_id)
        await engine.dispose()

        result = _run_alembic_allow_failure("upgrade", "head")
        assert result.returncode != 0, "upgrade must abort when an ambiguous-role user has no manifest coverage"
        assert "MEP_PR10_ROLE_MAPPING" in (result.stdout + result.stderr)

        # Fails closed atomically: not even the safe/no-op parts of this
        # revision (e.g. the legacy_role_name column add) persist.
        assert await _role_names() == {"biomedical_engineer"}, "no role rewrite may occur on an aborted upgrade"
        assert await _role_name_for_employee_code("AMBIGUOUS01") == "biomedical_engineer", (
            "an aborted migration must never leave a user with an upgraded/changed role"
        )
    finally:
        await _drop_scratch_database()


async def test_migration_0009_ambiguous_role_with_valid_manifest_succeeds():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            nurse_role_id = await _insert_role_row(conn, "ward_nurse")
            await _insert_legacy_user_row(conn, "NURSE001", nurse_role_id)
        await engine.dispose()

        manifest = json.dumps([{"employee_code": "NURSE001", "target_role": "equipment_pool_staff"}])
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})

        assert await _role_name_for_employee_code("NURSE001") == "equipment_pool_staff"
        assert await _legacy_role_name_column_value("NURSE001") == "ward_nurse"
        assert await _role_names() == {"administrator", "equipment_pool_staff", "read_only"}
    finally:
        await _drop_scratch_database()


async def test_migration_0009_manifest_invalid_target_role_aborts():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            transport_role_id = await _insert_role_row(conn, "transport_staff")
            await _insert_legacy_user_row(conn, "TRANSPORT01", transport_role_id)
        await engine.dispose()

        # "manager" is not one of the 3 confirmed roles -- this must never
        # be treated as an implicit privilege grant.
        manifest = json.dumps([{"employee_code": "TRANSPORT01", "target_role": "manager"}])
        result = _run_alembic_allow_failure("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        assert result.returncode != 0

        assert await _role_name_for_employee_code("TRANSPORT01") == "transport_staff"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_manifest_nonexistent_employee_code_aborts():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "REALUSER01", bme_role_id)
        await engine.dispose()

        # Covers REALUSER01 (so the coverage check alone would pass) but
        # also references a code that names no real account.
        manifest = json.dumps(
            [
                {"employee_code": "REALUSER01", "target_role": "equipment_pool_staff"},
                {"employee_code": "GHOST404", "target_role": "administrator"},
            ]
        )
        result = _run_alembic_allow_failure("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        assert result.returncode != 0
        assert "GHOST404" in (result.stdout + result.stderr)

        assert await _role_name_for_employee_code("REALUSER01") == "biomedical_engineer"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_manifest_duplicate_employee_code_aborts():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "DUPCODE01", bme_role_id)
        await engine.dispose()

        manifest = json.dumps(
            [
                {"employee_code": "DUPCODE01", "target_role": "administrator"},
                {"employee_code": "DUPCODE01", "target_role": "read_only"},
            ]
        )
        result = _run_alembic_allow_failure("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        assert result.returncode != 0

        assert await _role_name_for_employee_code("DUPCODE01") == "biomedical_engineer"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_never_deletes_a_user_row():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            viewer_role_id = await _insert_role_row(conn, "viewer")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "COUNTA01", admin_role_id)
            await _insert_legacy_user_row(conn, "COUNTV01", viewer_role_id)
            await _insert_legacy_user_row(conn, "COUNTB01", bme_role_id)
        await engine.dispose()

        before = await _user_count()
        assert before == 3

        manifest = json.dumps([{"employee_code": "COUNTB01", "target_role": "administrator"}])
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})

        after = await _user_count()
        assert after == before, "role consolidation must only ever change role_id, never delete a user"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_check_constraint_rejects_a_retired_role_name():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            from sqlalchemy.exc import DBAPIError

            async with engine.begin() as conn:
                with pytest.raises(DBAPIError):
                    await conn.execute(
                        text("INSERT INTO roles (id, name, permissions) VALUES (:id, 'admin', '{}'::jsonb)"),
                        {"id": str(uuid.uuid4())},
                    )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_round_trip_restores_legacy_roles_losslessly():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "ROUNDTRIP1", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        assert await _role_name_for_employee_code("ROUNDTRIP1") == "administrator"

        _run_alembic("downgrade", "0008_dispatch_fields")
        assert await _role_name_for_employee_code("ROUNDTRIP1") == "admin", (
            "downgrade must losslessly restore the pre-migration role from legacy_role_name"
        )
        names = await _role_names()
        assert "admin" in names

        # Re-upgrade simulates a database catching back up -- must converge
        # to the same confirmed state again.
        _run_alembic("upgrade", "head")
        assert await _role_name_for_employee_code("ROUNDTRIP1") == "administrator"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_aborts_for_a_user_created_after_upgrade():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT id FROM roles WHERE name = 'equipment_pool_staff'"))
            new_role_id = result.scalar_one()
            # legacy_role_name is left NULL -- exactly what a user created
            # through the application after this migration's upgrade would
            # have (see app.models.user.User.legacy_role_name's docstring).
            await _insert_legacy_user_row(conn, "POSTMIGUSER", new_role_id)
        await engine.dispose()

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0, "downgrade must abort rather than fabricate a legacy role"

        # Nothing changed: the new-model role rows are still present.
        assert await _role_names() == {"administrator", "equipment_pool_staff", "read_only"}
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Codex review round 1 on PR #36 (review 4766143140), blocker 1: migration
# role changes must carry truthful, atomic provenance -- a dedicated audit
# row per changed user, never a fabricated authenticated actor.
# ---------------------------------------------------------------------------


async def test_migration_0009_upgrade_writes_one_audit_row_per_changed_user_with_no_fabricated_actor():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            viewer_role_id = await _insert_role_row(conn, "viewer")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            # An "already migrated" user, standing in for a row this
            # migration must never touch or audit -- simulates a partial
            # prior run's own new-model role already existing.
            admin_confirmed_role_id = await _insert_role_row(conn, "administrator")
            await _insert_legacy_user_row(conn, "AUDITADMIN1", admin_role_id)
            await _insert_legacy_user_row(conn, "AUDITVIEWR1", viewer_role_id)
            await _insert_legacy_user_row(conn, "AUDITBME001", bme_role_id)
            await _insert_legacy_user_row(conn, "ALREADYNEW1", admin_confirmed_role_id)
        await engine.dispose()

        manifest = json.dumps([{"employee_code": "AUDITBME001", "target_role": "equipment_pool_staff"}])
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})

        admin_id = await _user_id_for_employee_code("AUDITADMIN1")
        viewer_id = await _user_id_for_employee_code("AUDITVIEWR1")
        bme_id = await _user_id_for_employee_code("AUDITBME001")
        already_new_id = await _user_id_for_employee_code("ALREADYNEW1")

        all_rows = await _role_migration_audit_rows()
        assert len(all_rows) == 3, f"expected exactly 3 changed users to be audited, got {len(all_rows)}"

        by_entity = {row["entity_id"]: row for row in all_rows}
        assert set(by_entity) == {admin_id, viewer_id, bme_id}
        assert already_new_id not in by_entity, "an already-confirmed-role user must never receive a role-change audit record"

        assert by_entity[admin_id]["before_data"] == {"role": "admin"}
        assert by_entity[admin_id]["after_data"]["role"] == "administrator"
        assert by_entity[viewer_id]["before_data"] == {"role": "viewer"}
        assert by_entity[viewer_id]["after_data"]["role"] == "read_only"
        assert by_entity[bme_id]["before_data"] == {"role": "biomedical_engineer"}
        assert by_entity[bme_id]["after_data"]["role"] == "equipment_pool_staff"

        for row in all_rows:
            assert row["user_id"] is None, "a migration-provenance audit row must never name a fabricated authenticated actor"
            assert row["action"] == "role_migration_upgrade"
            assert row["after_data"]["revision"] == "0009_role_consolidation"
            assert row["correlation_id"] == "0009_role_consolidation"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_upgrade_downgrade_reupgrade_audit_trail_stays_deterministic():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "DETERM0001", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        first_upgrade_rows = await _role_migration_audit_rows(action="role_migration_upgrade")
        assert len(first_upgrade_rows) == 1
        assert await _role_migration_audit_rows(action="role_migration_downgrade") == []

        _run_alembic("downgrade", "0008_dispatch_fields")
        assert await _role_name_for_employee_code("DETERM0001") == "admin"
        # H1: downgrade itself writes its own append-only provenance row,
        # distinct in action from the upgrade row above -- never zero,
        # never merged into/overwriting the upgrade row.
        downgrade_rows = await _role_migration_audit_rows(action="role_migration_downgrade")
        assert len(downgrade_rows) == 1

        _run_alembic("upgrade", "head")
        assert await _role_name_for_employee_code("DETERM0001") == "administrator"

        # Deterministic: a fresh, real role change on re-upgrade produces
        # exactly one more upgrade-action audit row (audit_logs is an
        # append-only history, not overwritten) -- never zero (silently
        # dropped) and never more than one extra (duplicated). The single
        # downgrade-action row from the round trip above must still be
        # present, untouched, alongside it.
        second_pass_upgrade_rows = await _role_migration_audit_rows(action="role_migration_upgrade")
        assert len(second_pass_upgrade_rows) == 2
        assert await _role_migration_audit_rows(action="role_migration_downgrade") == downgrade_rows

        all_rows = await _role_migration_audit_rows()
        assert len(all_rows) == 3, "3 total provenance rows: 2 upgrades + 1 downgrade, all preserved"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_audit_write_failure_prevents_partial_role_migration():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "AUDITFAIL01", admin_role_id)
            # Force the migration's own audit_logs INSERT to fail with a
            # realistic database-level error, standing in for any audit
            # write failure -- renaming the table is simpler and just as
            # valid a failure injection as a broken constraint.
            await conn.execute(text("ALTER TABLE audit_logs RENAME TO audit_logs_disabled_for_test"))
        await engine.dispose()

        result = _run_alembic_allow_failure("upgrade", "head")
        assert result.returncode != 0, "upgrade must abort when the migration-provenance audit write fails"

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE audit_logs_disabled_for_test RENAME TO audit_logs"))
        await engine.dispose()

        assert await _role_name_for_employee_code("AUDITFAIL01") == "admin", (
            "a failed audit write must roll back the role rewrite it was supposed to accompany"
        )
        assert await _role_names() == {"admin"}, (
            "a failed audit write must roll back the whole transaction, including the new role rows"
        )
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Codex review round 1 on PR #36 (review 4766143140), blocker 2: the
# mapping manifest may only ever remap a user whose CURRENT role is
# genuinely ambiguous -- never admin, never viewer, never an already-
# confirmed role, never an unrecognized role, and never a nonexistent user.
# ---------------------------------------------------------------------------


async def test_migration_0009_manifest_entry_for_admin_is_rejected():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "OVERRIDEADM", admin_role_id)
            await _insert_legacy_user_row(conn, "REALAMBIG01", bme_role_id)
        await engine.dispose()

        manifest = json.dumps(
            [
                {"employee_code": "REALAMBIG01", "target_role": "equipment_pool_staff"},
                {"employee_code": "OVERRIDEADM", "target_role": "read_only"},
            ]
        )
        result = _run_alembic_allow_failure("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        assert result.returncode != 0, "a manifest entry for a current admin user must be rejected"
        assert "OVERRIDEADM" in (result.stdout + result.stderr)

        assert await _role_name_for_employee_code("OVERRIDEADM") == "admin"
        assert await _role_name_for_employee_code("REALAMBIG01") == "biomedical_engineer"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_manifest_entry_for_viewer_is_rejected():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            viewer_role_id = await _insert_role_row(conn, "viewer")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "OVERRIDEVWR", viewer_role_id)
            await _insert_legacy_user_row(conn, "REALAMBIG02", bme_role_id)
        await engine.dispose()

        manifest = json.dumps(
            [
                {"employee_code": "REALAMBIG02", "target_role": "equipment_pool_staff"},
                {"employee_code": "OVERRIDEVWR", "target_role": "administrator"},
            ]
        )
        result = _run_alembic_allow_failure("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        assert result.returncode != 0, "a manifest entry for a current viewer user must be rejected"
        assert "OVERRIDEVWR" in (result.stdout + result.stderr)

        assert await _role_name_for_employee_code("OVERRIDEVWR") == "viewer"
        assert await _role_name_for_employee_code("REALAMBIG02") == "biomedical_engineer"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_manifest_entry_for_already_migrated_role_is_rejected():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            confirmed_role_id = await _insert_role_row(conn, "administrator")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "ALREADYCONF", confirmed_role_id)
            await _insert_legacy_user_row(conn, "REALAMBIG03", bme_role_id)
        await engine.dispose()

        manifest = json.dumps(
            [
                {"employee_code": "REALAMBIG03", "target_role": "equipment_pool_staff"},
                {"employee_code": "ALREADYCONF", "target_role": "read_only"},
            ]
        )
        result = _run_alembic_allow_failure("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        assert result.returncode != 0, "a manifest entry for a user who already holds a confirmed role must be rejected"
        assert "ALREADYCONF" in (result.stdout + result.stderr)

        assert await _role_name_for_employee_code("ALREADYCONF") == "administrator"
        assert await _role_name_for_employee_code("REALAMBIG03") == "biomedical_engineer"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_manifest_entry_for_unrecognized_role_is_rejected():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            # A role name outside both the legacy and confirmed domains
            # entirely -- never ambiguous, never safe, never confirmed.
            unknown_role_id = await _insert_role_row(conn, "guest")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "UNKNOWNROLE", unknown_role_id)
            await _insert_legacy_user_row(conn, "REALAMBIG04", bme_role_id)
        await engine.dispose()

        manifest = json.dumps(
            [
                {"employee_code": "REALAMBIG04", "target_role": "equipment_pool_staff"},
                {"employee_code": "UNKNOWNROLE", "target_role": "read_only"},
            ]
        )
        result = _run_alembic_allow_failure("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        assert result.returncode != 0, "a manifest entry for a user with an unrecognized current role must be rejected"
        assert "UNKNOWNROLE" in (result.stdout + result.stderr)

        assert await _role_name_for_employee_code("UNKNOWNROLE") == "guest"
        assert await _role_name_for_employee_code("REALAMBIG04") == "biomedical_engineer"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_one_invalid_manifest_entry_aborts_every_update():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            nurse_role_id = await _insert_role_row(conn, "ward_nurse")
            await _insert_legacy_user_row(conn, "VALIDADMIN1", admin_role_id)
            await _insert_legacy_user_row(conn, "VALIDAMBIG1", bme_role_id)
            await _insert_legacy_user_row(conn, "VALIDAMBIG2", nurse_role_id)
        await engine.dispose()

        manifest = json.dumps(
            [
                {"employee_code": "VALIDAMBIG1", "target_role": "equipment_pool_staff"},
                {"employee_code": "VALIDAMBIG2", "target_role": "administrator"},
                {"employee_code": "VALIDADMIN1", "target_role": "read_only"},  # the one invalid entry
            ]
        )
        result = _run_alembic_allow_failure("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        assert result.returncode != 0

        # Every user is untouched -- not just the invalid entry's target.
        assert await _role_name_for_employee_code("VALIDADMIN1") == "admin"
        assert await _role_name_for_employee_code("VALIDAMBIG1") == "biomedical_engineer"
        assert await _role_name_for_employee_code("VALIDAMBIG2") == "ward_nurse"
        assert await _role_migration_audit_rows() == []
    finally:
        await _drop_scratch_database()


async def test_migration_0009_no_audit_records_written_on_failed_manifest_validation():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "NOAUDITADM1", admin_role_id)
            await _insert_legacy_user_row(conn, "NOAUDITAMB1", bme_role_id)
        await engine.dispose()

        manifest = json.dumps(
            [
                {"employee_code": "NOAUDITAMB1", "target_role": "equipment_pool_staff"},
                {"employee_code": "NOAUDITADM1", "target_role": "read_only"},
            ]
        )
        result = _run_alembic_allow_failure("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        assert result.returncode != 0

        assert await _role_migration_audit_rows() == [], "a validation-aborted run must write zero provenance rows"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_manifest_only_changes_ambiguous_role_users():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            viewer_role_id = await _insert_role_row(conn, "viewer")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "MIXEDADMIN1", admin_role_id)
            await _insert_legacy_user_row(conn, "MIXEDVIEWR1", viewer_role_id)
            await _insert_legacy_user_row(conn, "MIXEDAMBIG1", bme_role_id)
        await engine.dispose()

        manifest = json.dumps([{"employee_code": "MIXEDAMBIG1", "target_role": "equipment_pool_staff"}])
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})

        # The safe automatic mapping applied to admin/viewer, entirely
        # independent of the manifest.
        assert await _role_name_for_employee_code("MIXEDADMIN1") == "administrator"
        assert await _role_name_for_employee_code("MIXEDVIEWR1") == "read_only"
        # The manifest applied only to the ambiguous-role user.
        assert await _role_name_for_employee_code("MIXEDAMBIG1") == "equipment_pool_staff"

        rows = await _user_role_migration_rows()
        by_code = {}
        for row in rows:
            employee_code = None
            for code in ("MIXEDADMIN1", "MIXEDVIEWR1", "MIXEDAMBIG1"):
                if row["user_id"] == await _user_id_for_employee_code(code):
                    employee_code = code
            by_code[employee_code] = row
        assert by_code["MIXEDADMIN1"]["legacy_role"] == "admin"
        assert by_code["MIXEDVIEWR1"]["legacy_role"] == "viewer"
        assert by_code["MIXEDAMBIG1"]["legacy_role"] == "biomedical_engineer"
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Codex review round 1 on PR #36 (review 4766143140), blocker 3: downgrade
# must be lossless per-user (never inferred from the new role alone) and
# must never overwrite a legitimate post-upgrade role change.
# ---------------------------------------------------------------------------


async def test_migration_0009_downgrade_restores_each_ambiguous_legacy_role_exactly_even_when_mapped_to_the_same_new_role():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            nurse_role_id = await _insert_role_row(conn, "ward_nurse")
            transport_role_id = await _insert_role_row(conn, "transport_staff")
            await _insert_legacy_user_row(conn, "RESTOREBME1", bme_role_id)
            await _insert_legacy_user_row(conn, "RESTORENUR1", nurse_role_id)
            await _insert_legacy_user_row(conn, "RESTORETRN1", transport_role_id)
        await engine.dispose()

        # All three ambiguous legacy roles deliberately mapped to the SAME
        # confirmed role -- proves downgrade cannot be reverse-inferred
        # from the new role alone.
        manifest = json.dumps(
            [
                {"employee_code": "RESTOREBME1", "target_role": "equipment_pool_staff"},
                {"employee_code": "RESTORENUR1", "target_role": "equipment_pool_staff"},
                {"employee_code": "RESTORETRN1", "target_role": "equipment_pool_staff"},
            ]
        )
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        for code in ("RESTOREBME1", "RESTORENUR1", "RESTORETRN1"):
            assert await _role_name_for_employee_code(code) == "equipment_pool_staff"

        _run_alembic("downgrade", "0008_dispatch_fields")

        assert await _role_name_for_employee_code("RESTOREBME1") == "biomedical_engineer"
        assert await _role_name_for_employee_code("RESTORENUR1") == "ward_nurse"
        assert await _role_name_for_employee_code("RESTORETRN1") == "transport_staff"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_restores_admin_and_viewer_exactly():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            viewer_role_id = await _insert_role_row(conn, "viewer")
            await _insert_legacy_user_row(conn, "RESTOREADM1", admin_role_id)
            await _insert_legacy_user_row(conn, "RESTOREVWR1", viewer_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "0008_dispatch_fields")

        assert await _role_name_for_employee_code("RESTOREADM1") == "admin"
        assert await _role_name_for_employee_code("RESTOREVWR1") == "viewer"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_aborts_when_a_migrated_users_role_changed_after_upgrade():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "DIVERGED001", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        assert await _role_name_for_employee_code("DIVERGED001") == "administrator"

        # A legitimate post-upgrade role change, e.g. an Administrator
        # later reassigning this user via PATCH /api/v1/users/{id}.
        await _set_user_role_directly("DIVERGED001", "read_only")

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0, "downgrade must abort rather than overwrite a legitimate post-upgrade role change"
        assert "DIVERGED001" in (result.stdout + result.stderr)

        # Untouched -- the post-upgrade change survives.
        assert await _role_name_for_employee_code("DIVERGED001") == "read_only"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_abort_causes_no_partial_role_restoration():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            viewer_role_id = await _insert_role_row(conn, "viewer")
            await _insert_legacy_user_row(conn, "PARTIALA001", admin_role_id)
            await _insert_legacy_user_row(conn, "PARTIALB001", viewer_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        assert await _role_name_for_employee_code("PARTIALA001") == "administrator"
        assert await _role_name_for_employee_code("PARTIALB001") == "read_only"

        # Only ONE of the two migrated users diverges after upgrade.
        await _set_user_role_directly("PARTIALA001", "equipment_pool_staff")

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0

        # Neither user was restored -- the undiverged user must not be
        # partially downgraded while its sibling blocks the run.
        assert await _role_name_for_employee_code("PARTIALA001") == "equipment_pool_staff"
        assert await _role_name_for_employee_code("PARTIALB001") == "read_only"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_migration_metadata_is_complete_and_lossless():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "METAADMIN01", admin_role_id)
            await _insert_legacy_user_row(conn, "METAAMBIG01", bme_role_id)
        await engine.dispose()

        manifest = json.dumps([{"employee_code": "METAAMBIG01", "target_role": "read_only"}])
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})

        admin_id = await _user_id_for_employee_code("METAADMIN01")
        ambig_id = await _user_id_for_employee_code("METAAMBIG01")

        rows = await _user_role_migration_rows()
        by_user = {row["user_id"]: row for row in rows}
        assert set(by_user) == {admin_id, ambig_id}
        assert by_user[admin_id]["legacy_role"] == "admin"
        assert by_user[admin_id]["migrated_role"] == "administrator"
        assert by_user[admin_id]["revision"] == "0009_role_consolidation"
        assert by_user[ambig_id]["legacy_role"] == "biomedical_engineer"
        assert by_user[ambig_id]["migrated_role"] == "read_only"
        assert by_user[ambig_id]["revision"] == "0009_role_consolidation"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_repeated_downgrade_cannot_silently_corrupt_roles():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "REPEATDG001", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "0008_dispatch_fields")
        assert await _role_name_for_employee_code("REPEATDG001") == "admin"

        # alembic itself is already at 0008 -- asking to downgrade to 0008
        # again must be a safe no-op, never a corrupting second attempt to
        # "restore" an already-restored role.
        _run_alembic("downgrade", "0008_dispatch_fields")
        assert await _role_name_for_employee_code("REPEATDG001") == "admin"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_preserves_credentials_and_unrelated_user_fields():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "PRESERVE001", admin_role_id)
        await engine.dispose()

        before = await _user_row("PRESERVE001")

        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "0008_dispatch_fields")

        after = await _user_row("PRESERVE001")
        assert after["id"] == before["id"]
        assert after["full_name"] == before["full_name"]
        assert after["email"] == before["email"]
        assert after["password_hash"] == before["password_hash"]
        assert after["is_active"] == before["is_active"]
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Codex review round 2 on PR #36 (review 4769035499), remaining blocker H1:
# downgrade role restorations must be audited too, with an action string
# distinguishable from the upgrade direction, and that audit write must be
# part of the same atomic downgrade -- never fabricating an actor.
# ---------------------------------------------------------------------------


async def test_migration_0009_downgrade_writes_one_audit_row_per_restored_user_with_no_fabricated_actor():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            viewer_role_id = await _insert_role_row(conn, "viewer")
            await _insert_legacy_user_row(conn, "DGADMIN001", admin_role_id)
            await _insert_legacy_user_row(conn, "DGVIEWER01", viewer_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        admin_id = await _user_id_for_employee_code("DGADMIN001")
        viewer_id = await _user_id_for_employee_code("DGVIEWER01")

        _run_alembic("downgrade", "0008_dispatch_fields")

        rows = await _role_migration_audit_rows(action="role_migration_downgrade")
        assert len(rows) == 2, f"expected exactly one downgrade audit row per restored user, got {len(rows)}"

        by_entity = {row["entity_id"]: row for row in rows}
        assert set(by_entity) == {admin_id, viewer_id}
        assert by_entity[admin_id]["before_data"] == {"role": "administrator"}
        assert by_entity[admin_id]["after_data"]["role"] == "admin"
        assert by_entity[viewer_id]["before_data"] == {"role": "read_only"}
        assert by_entity[viewer_id]["after_data"]["role"] == "viewer"

        for row in rows:
            assert row["user_id"] is None, "a downgrade provenance row must never name a fabricated authenticated actor"
            assert row["action"] == "role_migration_downgrade"
            assert row["after_data"]["revision"] == "0009_role_consolidation"
            assert row["correlation_id"] == "0009_role_consolidation"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_audit_action_distinguishable_from_upgrade_audit_action():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "DISTINCT001", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "0008_dispatch_fields")

        upgrade_rows = await _role_migration_audit_rows(action="role_migration_upgrade")
        downgrade_rows = await _role_migration_audit_rows(action="role_migration_downgrade")
        assert len(upgrade_rows) == 1
        assert len(downgrade_rows) == 1
        assert upgrade_rows[0]["action"] != downgrade_rows[0]["action"]
        assert {row["action"] for row in upgrade_rows} == {"role_migration_upgrade"}
        assert {row["action"] for row in downgrade_rows} == {"role_migration_downgrade"}
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_audit_write_failure_prevents_partial_role_restoration():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "DGAUDITFAIL", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        assert await _role_name_for_employee_code("DGAUDITFAIL") == "administrator"

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE audit_logs RENAME TO audit_logs_disabled_for_test"))
        await engine.dispose()

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0, "downgrade must abort when the downgrade-provenance audit write fails"

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE audit_logs_disabled_for_test RENAME TO audit_logs"))
        await engine.dispose()

        assert await _role_name_for_employee_code("DGAUDITFAIL") == "administrator", (
            "a failed downgrade audit write must roll back the role restoration it was supposed to accompany"
        )
        assert await _role_names() == {"administrator", "equipment_pool_staff", "read_only"}, (
            "a failed downgrade audit write must roll back the whole transaction -- no legacy role "
            "row may be partially recreated"
        )
    finally:
        await _drop_scratch_database()


async def test_migration_0009_failed_downgrade_preflight_creates_no_downgrade_audit_events():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "NODGADUDIT1", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        await _set_user_role_directly("NODGADUDIT1", "read_only")  # legitimate post-upgrade change

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0

        assert await _role_migration_audit_rows(action="role_migration_downgrade") == [], (
            "an aborted downgrade preflight must write zero downgrade-provenance rows"
        )
    finally:
        await _drop_scratch_database()


async def test_migration_0009_failed_downgrade_preflight_leaves_migration_metadata_tables_intact():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "METAINTACT1", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        await _set_user_role_directly("METAINTACT1", "read_only")

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0

        assert await _table_exists("user_role_migrations") is True
        assert await _table_exists("role_migration_snapshots") is True
        assert await _user_role_migration_rows() != [], "downgrade metadata must survive an aborted preflight"
        assert await _role_snapshot_rows() != [], "role snapshot metadata must survive an aborted preflight"
        assert await _legacy_role_name_column_value("METAINTACT1") == "admin", (
            "the legacy_role_name provenance column must not be dropped by an aborted downgrade"
        )
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Codex review round 2 on PR #36 (review 4769035499), remaining blocker H3:
# downgrade must restore the EXACT pre-upgrade role row -- same roles.id,
# same permissions JSONB -- and the exact original user-role assignment,
# never a same-named row with a freshly generated id, never inferred
# permissions, never a collapsed record when several legacy roles mapped to
# the same new role.
# ---------------------------------------------------------------------------


async def test_migration_0009_snapshot_captures_exact_legacy_role_id_and_permissions():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin", permissions={"can_do": ["a", "b"], "level": 3})
            await _insert_legacy_user_row(conn, "SNAPADMIN01", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")

        snapshots = await _role_snapshot_rows()
        admin_snap = next(row for row in snapshots if row["legacy_role_name"] == "admin")
        assert admin_snap["legacy_role_id"] == admin_role_id, "the snapshot must capture the role's exact original id"
        assert admin_snap["legacy_role_permissions"] == {"can_do": ["a", "b"], "level": 3}, (
            "the snapshot must capture the role's exact original permissions, not an empty/inferred value"
        )
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_restores_exact_original_role_id_not_a_new_uuid():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "EXACTID0001", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "0008_dispatch_fields")

        restored = await _role_row_by_id(admin_role_id)
        assert restored is not None, "the exact original role id must exist again after downgrade"
        assert restored["name"] == "admin"

        all_rows = await _all_role_rows()
        admin_rows = [row for row in all_rows if row["name"] == "admin"]
        assert len(admin_rows) == 1, "downgrade must never leave more than one row for a restored legacy role"
        assert admin_rows[0]["id"] == admin_role_id, "downgrade must never generate a fresh id for a restored role"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_restores_role_permissions_exactly_including_nested_values():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        permissions = {"scope": {"equipment": ["view", "edit"]}, "flag": True, "count": 0, "note": None}
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin", permissions=permissions)
            await _insert_legacy_user_row(conn, "NESTEDPERM1", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "0008_dispatch_fields")

        restored = await _role_row_by_id(admin_role_id)
        assert restored["permissions"] == permissions, (
            "every column of the restored role, including nested/null JSONB values, must round-trip exactly"
        )
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_restores_distinct_permission_sets_for_different_legacy_roles_mapped_to_same_new_role():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        bme_permissions = {"scope": "biomedical", "can_service_equipment": True}
        nurse_permissions = {"scope": "nursing", "can_service_equipment": False}
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer", permissions=bme_permissions)
            nurse_role_id = await _insert_role_row(conn, "ward_nurse", permissions=nurse_permissions)
            await _insert_legacy_user_row(conn, "DISTPERM001", bme_role_id)
            await _insert_legacy_user_row(conn, "DISTPERM002", nurse_role_id)
        await engine.dispose()

        # Both ambiguous legacy roles deliberately mapped to the SAME
        # confirmed role -- their distinct original permission sets must
        # still be recoverable, never merged or reverse-inferred.
        manifest = json.dumps(
            [
                {"employee_code": "DISTPERM001", "target_role": "equipment_pool_staff"},
                {"employee_code": "DISTPERM002", "target_role": "equipment_pool_staff"},
            ]
        )
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        _run_alembic("downgrade", "0008_dispatch_fields")

        restored_bme = await _role_row_by_id(bme_role_id)
        restored_nurse = await _role_row_by_id(nurse_role_id)
        assert restored_bme["permissions"] == bme_permissions
        assert restored_nurse["permissions"] == nurse_permissions
        assert restored_bme["permissions"] != restored_nurse["permissions"]
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_restores_exact_user_role_ids_without_collapsing():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            nurse_role_id = await _insert_role_row(conn, "ward_nurse")
            await _insert_legacy_user_row(conn, "COLLAPSE001", bme_role_id)
            await _insert_legacy_user_row(conn, "COLLAPSE002", nurse_role_id)
        await engine.dispose()

        manifest = json.dumps(
            [
                {"employee_code": "COLLAPSE001", "target_role": "equipment_pool_staff"},
                {"employee_code": "COLLAPSE002", "target_role": "equipment_pool_staff"},
            ]
        )
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        _run_alembic("downgrade", "0008_dispatch_fields")

        assert bme_role_id != nurse_role_id
        assert await _user_role_id("COLLAPSE001") == bme_role_id, (
            "each user must be restored to their own exact original legacy role id, never a collapsed shared one"
        )
        assert await _user_role_id("COLLAPSE002") == nurse_role_id
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_aborts_when_snapshot_row_is_missing():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "NOSNAPSHOT1", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")

        # Simulate the snapshot row being lost/corrupted independently of
        # the per-user migration metadata -- downgrade must refuse to
        # fabricate a role row it has no exact record of.
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM role_migration_snapshots WHERE legacy_role_id = :id"), {"id": admin_role_id}
            )
        await engine.dispose()

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0, "downgrade must abort when a referenced role snapshot is missing"
        assert admin_role_id in (result.stdout + result.stderr)

        assert await _role_name_for_employee_code("NOSNAPSHOT1") == "administrator", (
            "no role may be restored when its snapshot is missing"
        )
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_aborts_when_restoring_role_id_would_collide():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "COLLIDE0001", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")

        # Simulate some other row now legitimately occupying the exact id
        # the snapshot needs to restore -- e.g. an operational anomaly
        # unrelated to this migration. Dropping the CHECK constraint here
        # is test setup only (mirrors this file's audit_logs RENAME
        # failure-injection pattern elsewhere) -- downgrade() itself drops
        # the same constraint unconditionally as its own first step.
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE roles DROP CONSTRAINT IF EXISTS ck_roles_name_confirmed"))
            await conn.execute(
                text("INSERT INTO roles (id, name, permissions) VALUES (:id, 'orphan_role', '{}'::jsonb)"),
                {"id": admin_role_id},
            )
        await engine.dispose()

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0, "downgrade must abort rather than overwrite a role id already in use"
        assert admin_role_id in (result.stdout + result.stderr)

        assert await _role_name_for_employee_code("COLLIDE0001") == "administrator", (
            "no role change may occur when restoring would collide"
        )
        orphan = await _role_row_by_id(admin_role_id)
        assert orphan is not None and orphan["name"] == "orphan_role", (
            "the unrelated row occupying the colliding id must be left untouched"
        )
    finally:
        await _drop_scratch_database()


async def test_migration_0009_role_id_generation_remains_valid_after_downgrade_no_sequence_dependency():
    # roles.id is a UUID (UUIDPKMixin), never backed by a PostgreSQL
    # sequence -- restoring explicit legacy ids during downgrade has no
    # sequence state to repair (unlike transaction_no_seq in migration
    # 0003). This proves ordinary new-role-id generation still behaves
    # normally immediately afterward.
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin")
            await _insert_legacy_user_row(conn, "SEQCHECK001", admin_role_id)
        await engine.dispose()

        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE roles DROP CONSTRAINT IF EXISTS ck_roles_name_confirmed"))
                new_id = str(uuid.uuid4())
                await conn.execute(
                    text("INSERT INTO roles (id, name, permissions) VALUES (:id, 'brand_new_role', '{}'::jsonb)"),
                    {"id": new_id},
                )
                result = await conn.execute(text("SELECT id FROM roles WHERE id = :id"), {"id": new_id})
                assert str(result.scalar_one()) == new_id
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0009_full_round_trip_preserves_roles_ids_permissions_and_user_assignments_exactly():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "admin", permissions={"admin_scope": True})
            viewer_role_id = await _insert_role_row(conn, "viewer", permissions={"read": ["all"]})
            bme_role_id = await _insert_role_row(
                conn, "biomedical_engineer", permissions={"scope": "biomedical", "level": 2}
            )
            nurse_role_id = await _insert_role_row(conn, "ward_nurse", permissions={"scope": "nursing"})
            transport_role_id = await _insert_role_row(conn, "transport_staff", permissions={})
            await _insert_legacy_user_row(conn, "RTADMIN001", admin_role_id)
            await _insert_legacy_user_row(conn, "RTADMIN002", admin_role_id)
            await _insert_legacy_user_row(conn, "RTVIEWER01", viewer_role_id)
            await _insert_legacy_user_row(conn, "RTBME00001", bme_role_id)
            await _insert_legacy_user_row(conn, "RTNURSE001", nurse_role_id)
            await _insert_legacy_user_row(conn, "RTTRANSP01", transport_role_id)
        await engine.dispose()

        before_roles = sorted(
            [
                {"id": admin_role_id, "name": "admin", "permissions": {"admin_scope": True}},
                {"id": viewer_role_id, "name": "viewer", "permissions": {"read": ["all"]}},
                {"id": bme_role_id, "name": "biomedical_engineer", "permissions": {"scope": "biomedical", "level": 2}},
                {"id": nurse_role_id, "name": "ward_nurse", "permissions": {"scope": "nursing"}},
                {"id": transport_role_id, "name": "transport_staff", "permissions": {}},
            ],
            key=lambda row: row["name"],
        )
        before_assignments = {
            "RTADMIN001": admin_role_id,
            "RTADMIN002": admin_role_id,
            "RTVIEWER01": viewer_role_id,
            "RTBME00001": bme_role_id,
            "RTNURSE001": nurse_role_id,
            "RTTRANSP01": transport_role_id,
        }

        manifest = json.dumps(
            [
                {"employee_code": "RTBME00001", "target_role": "equipment_pool_staff"},
                {"employee_code": "RTNURSE001", "target_role": "read_only"},
                {"employee_code": "RTTRANSP01", "target_role": "equipment_pool_staff"},
            ]
        )
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        _run_alembic("downgrade", "0008_dispatch_fields")

        after_roles = await _all_role_rows()
        assert after_roles == before_roles, (
            "every legacy role row must round-trip with identical id, name, and permissions -- "
            "row-by-row equality, not just matching counts"
        )

        after_assignments = {code: await _user_role_id(code) for code in before_assignments}
        assert after_assignments == before_assignments, (
            "every user must be restored to the exact original legacy role id, with no collapsing "
            "between users who shared a legacy role and no cross-assignment between users who "
            "happened to migrate to the same new role"
        )
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Codex review round 3 on PR #36 (review 4769328243), the remaining blocker:
# downgrade must never delete a confirmed-role row (administrator,
# equipment_pool_staff, read_only) merely because of its name -- only a role
# this revision's own confirmed_role_ownership record proves it CREATED may
# ever be deleted. A role that already existed under that name before
# upgrade() ran must survive downgrade unconditionally, with its exact id
# and pre-upgrade permissions restored.
# ---------------------------------------------------------------------------


async def test_migration_0009_upgrade_reuses_pre_existing_administrator_role_and_records_ownership():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "administrator", permissions={"pre_existing": True})
        await engine.dispose()

        _run_alembic("upgrade", "head")

        # Reused, never a fresh id.
        role = await _role_row_by_id(admin_role_id)
        assert role is not None
        assert role["name"] == "administrator"
        assert role["permissions"] == {"pre_existing": True}, "upgrade() must never overwrite a reused role's permissions"

        ownership = await _ownership_rows()
        admin_ownership = next(row for row in ownership if row["role_name"] == "administrator")
        assert admin_ownership["role_id"] == admin_role_id
        assert admin_ownership["existed_before_upgrade"] is True
        assert admin_ownership["created_by_migration"] is False
        assert admin_ownership["pre_upgrade_permissions"] == {"pre_existing": True}

        _run_alembic("downgrade", "0008_dispatch_fields")

        # Not deleted, exact id and permissions restored/unchanged.
        role = await _role_row_by_id(admin_role_id)
        assert role is not None, "downgrade must never delete a role that existed before this migration's upgrade"
        assert role["name"] == "administrator"
        assert role["permissions"] == {"pre_existing": True}
    finally:
        await _drop_scratch_database()


async def test_migration_0009_upgrade_reuses_pre_existing_read_only_role_and_records_ownership():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            read_only_role_id = await _insert_role_row(conn, "read_only", permissions={"scope": "reports_only"})
        await engine.dispose()

        _run_alembic("upgrade", "head")

        role = await _role_row_by_id(read_only_role_id)
        assert role is not None
        assert role["name"] == "read_only"
        assert role["permissions"] == {"scope": "reports_only"}

        ownership = await _ownership_rows()
        read_only_ownership = next(row for row in ownership if row["role_name"] == "read_only")
        assert read_only_ownership["role_id"] == read_only_role_id
        assert read_only_ownership["existed_before_upgrade"] is True
        assert read_only_ownership["created_by_migration"] is False
        assert read_only_ownership["pre_upgrade_permissions"] == {"scope": "reports_only"}

        _run_alembic("downgrade", "0008_dispatch_fields")

        role = await _role_row_by_id(read_only_role_id)
        assert role is not None, "downgrade must never delete a role that existed before this migration's upgrade"
        assert role["name"] == "read_only"
        assert role["permissions"] == {"scope": "reports_only"}
    finally:
        await _drop_scratch_database()


async def test_migration_0009_upgrade_creates_confirmed_role_and_records_ownership():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")
        # No pre-existing confirmed-role rows at all -- upgrade() must create all 3.

        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT id FROM roles WHERE name = 'equipment_pool_staff'"))
                created_role_id = str(result.scalar_one())
        finally:
            await engine.dispose()

        ownership = await _ownership_rows()
        staff_ownership = next(row for row in ownership if row["role_name"] == "equipment_pool_staff")
        assert staff_ownership["role_id"] == created_role_id
        assert staff_ownership["existed_before_upgrade"] is False
        assert staff_ownership["created_by_migration"] is True
        assert staff_ownership["pre_upgrade_permissions"] is None

        _run_alembic("downgrade", "0008_dispatch_fields")

        role = await _role_row_by_id(created_role_id)
        assert role is None, "a role this migration created, with no unrelated reference, must be deleted on downgrade"
    finally:
        await _drop_scratch_database()


async def test_migration_0009_mixed_ownership_upgrade_downgrade_preserves_pre_existing_role_and_removes_only_created_roles():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            # One confirmed role pre-exists...
            admin_role_id = await _insert_role_row(conn, "administrator", permissions={"pre_existing": True})
            await _insert_legacy_user_row(conn, "MIXPREEXST", admin_role_id)
            # ...the other two do not, and legacy users exercise both the
            # safe auto-map and the ambiguous-role manifest path.
            legacy_viewer_role_id = await _insert_role_row(conn, "viewer")
            legacy_bme_role_id = await _insert_role_row(conn, "biomedical_engineer")
            await _insert_legacy_user_row(conn, "MIXVIEWER01", legacy_viewer_role_id)
            await _insert_legacy_user_row(conn, "MIXBME00001", legacy_bme_role_id)
        await engine.dispose()

        before_admin_row = await _role_row_by_id(admin_role_id)

        manifest = json.dumps([{"employee_code": "MIXBME00001", "target_role": "equipment_pool_staff"}])
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})

        ownership = await _ownership_rows()
        by_name = {row["role_name"]: row for row in ownership}
        assert by_name["administrator"]["existed_before_upgrade"] is True
        assert by_name["administrator"]["created_by_migration"] is False
        assert by_name["equipment_pool_staff"]["existed_before_upgrade"] is False
        assert by_name["equipment_pool_staff"]["created_by_migration"] is True
        assert by_name["read_only"]["existed_before_upgrade"] is False
        assert by_name["read_only"]["created_by_migration"] is True

        _run_alembic("downgrade", "0008_dispatch_fields")

        # Pre-existing role: unchanged id and metadata, still present.
        after_admin_row = await _role_row_by_id(admin_role_id)
        assert after_admin_row == before_admin_row

        # Only the two migration-created roles are gone.
        names = await _role_names()
        assert "administrator" in names
        assert "equipment_pool_staff" not in names
        assert "read_only" not in names

        # Legacy roles/assignments restored exactly.
        assert await _role_name_for_employee_code("MIXVIEWER01") == "viewer"
        assert await _role_name_for_employee_code("MIXBME00001") == "biomedical_engineer"
        # The pre-existing administrator user was never touched by this
        # migration in either direction -- still on the same reused role.
        assert await _user_role_id("MIXPREEXST") == admin_role_id
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_aborts_on_post_upgrade_reference_to_migration_created_role():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT id FROM roles WHERE name = 'equipment_pool_staff'"))
            staff_role_id = str(result.scalar_one())
            # A brand-new user, assigned this migration-created role AFTER
            # upgrade ran -- e.g. via the ordinary POST /api/v1/users API.
            # Never migrated by 0009; no user_role_migrations row for them.
            await _insert_legacy_user_row(conn, "POSTREF0001", staff_role_id)
        await engine.dispose()

        before_role_names = await _role_names()
        before_user_count = await _user_count()

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0, "downgrade must abort when a migration-created role has an unrelated post-upgrade reference"
        assert staff_role_id in (result.stdout + result.stderr)

        # Nothing changed at all.
        assert await _role_names() == before_role_names
        assert await _user_count() == before_user_count
        assert await _role_name_for_employee_code("POSTREF0001") == "equipment_pool_staff"
        assert await _role_migration_audit_rows(action="role_migration_downgrade") == []
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_aborts_when_ownership_provenance_is_missing():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM confirmed_role_ownership WHERE role_name = 'administrator'")
            )
        await engine.dispose()

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0, "downgrade must abort when a confirmed role has no ownership provenance"
        assert "administrator" in (result.stdout + result.stderr)

        # Nothing changed -- still on the 3-role model.
        assert await _role_names() == {"administrator", "equipment_pool_staff", "read_only"}
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_aborts_when_ownership_role_id_is_mismatched():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            # Simulate ownership metadata drifting from reality: the
            # recorded role_id no longer matches any real invariant this
            # migration itself maintains.
            await conn.execute(
                text(
                    "UPDATE confirmed_role_ownership SET role_id = :fake_id "
                    "WHERE role_name = 'administrator'"
                ),
                {"fake_id": str(uuid.uuid4())},
            )
        await engine.dispose()

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0, "downgrade must abort when ownership's role_id does not match the current role"
        assert "administrator" in (result.stdout + result.stderr)

        assert await _role_names() == {"administrator", "equipment_pool_staff", "read_only"}
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_treats_same_name_different_primary_key_as_not_owned():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            # The original 'administrator' row this revision owns is
            # replaced (deleted, then recreated under the same name with a
            # brand-new id) by something entirely outside this migration --
            # e.g. a manual operator fix. The ownership record still names
            # the OLD id.
            await conn.execute(text("ALTER TABLE roles DROP CONSTRAINT IF EXISTS ck_roles_name_confirmed"))
            await conn.execute(text("DELETE FROM roles WHERE name = 'administrator'"))
            new_id = str(uuid.uuid4())
            await conn.execute(
                text("INSERT INTO roles (id, name, permissions) VALUES (:id, 'administrator', '{}'::jsonb)"),
                {"id": new_id},
            )
        await engine.dispose()

        result = _run_alembic_allow_failure("downgrade", "0008_dispatch_fields")
        assert result.returncode != 0, (
            "a role name match must never be treated as ownership proof when the primary key differs"
        )
        assert "administrator" in (result.stdout + result.stderr)
    finally:
        await _drop_scratch_database()


async def test_migration_0009_ownership_table_rejects_duplicate_provenance_for_same_role_name():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            from sqlalchemy.exc import DBAPIError

            async with engine.begin() as conn:
                with pytest.raises(DBAPIError):
                    await conn.execute(
                        text(
                            "INSERT INTO confirmed_role_ownership "
                            "(id, revision, role_id, role_name, existed_before_upgrade, created_by_migration) "
                            "VALUES (:id, '0009_role_consolidation', :role_id, 'administrator', true, false)"
                        ),
                        {"id": str(uuid.uuid4()), "role_id": str(uuid.uuid4())},
                    )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0009_ownership_table_rejects_contradictory_ownership_flags():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            from sqlalchemy.exc import DBAPIError

            async with engine.begin() as conn:
                with pytest.raises(DBAPIError):
                    await conn.execute(
                        text(
                            "INSERT INTO confirmed_role_ownership "
                            "(id, revision, role_id, role_name, existed_before_upgrade, created_by_migration) "
                            "VALUES (:id, '0009_role_consolidation', :role_id, 'zz_corrupt_role', true, true)"
                        ),
                        {"id": str(uuid.uuid4()), "role_id": str(uuid.uuid4())},
                    )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0009_downgrade_preserves_pre_existing_role_and_its_users_credentials():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            admin_role_id = await _insert_role_row(conn, "administrator")
            await _insert_legacy_user_row(conn, "PREEXISTUSR", admin_role_id)
        await engine.dispose()

        before = await _user_row("PREEXISTUSR")

        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", "0008_dispatch_fields")

        after = await _user_row("PREEXISTUSR")
        assert after == before, "a user on a reused pre-existing role, never migrated, must be completely untouched"
        assert await _user_role_id("PREEXISTUSR") == admin_role_id
    finally:
        await _drop_scratch_database()


async def test_migration_0009_mixed_ownership_round_trip_preserves_everything_exactly():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0008_dispatch_fields")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        async with engine.begin() as conn:
            # Pre-existing confirmed role, with its own pre-existing user,
            # entirely outside this migration's business.
            admin_role_id = await _insert_role_row(conn, "administrator", permissions={"pre_existing": True})
            await _insert_legacy_user_row(conn, "RT2ADMIN01", admin_role_id)

            # Legacy roles/users this migration actually processes.
            viewer_role_id = await _insert_role_row(conn, "viewer", permissions={"read": ["all"]})
            bme_role_id = await _insert_role_row(conn, "biomedical_engineer", permissions={"scope": "biomedical"})
            await _insert_legacy_user_row(conn, "RT2VIEWER1", viewer_role_id)
            await _insert_legacy_user_row(conn, "RT2BME0001", bme_role_id)
        await engine.dispose()

        before_admin_row = await _role_row_by_id(admin_role_id)
        before_admin_user_role = await _user_role_id("RT2ADMIN01")

        before_legacy_roles = sorted(
            [
                {"id": viewer_role_id, "name": "viewer", "permissions": {"read": ["all"]}},
                {"id": bme_role_id, "name": "biomedical_engineer", "permissions": {"scope": "biomedical"}},
            ],
            key=lambda row: row["name"],
        )
        before_legacy_assignments = {"RT2VIEWER1": viewer_role_id, "RT2BME0001": bme_role_id}

        manifest = json.dumps([{"employee_code": "RT2BME0001", "target_role": "equipment_pool_staff"}])
        _run_alembic("upgrade", "head", extra_env={_MEP_PR10_ROLE_MAPPING_ENV: manifest})
        _run_alembic("downgrade", "0008_dispatch_fields")

        # Pre-existing role and its user: byte-for-byte unchanged.
        assert await _role_row_by_id(admin_role_id) == before_admin_row
        assert await _user_role_id("RT2ADMIN01") == before_admin_user_role

        # Legacy roles/assignments this migration DID process: fully
        # restored, row-by-row, not merely by count.
        after_legacy_roles = sorted(
            [row for row in await _all_role_rows() if row["name"] in {"viewer", "biomedical_engineer"}],
            key=lambda row: row["name"],
        )
        assert after_legacy_roles == before_legacy_roles
        after_legacy_assignments = {code: await _user_role_id(code) for code in before_legacy_assignments}
        assert after_legacy_assignments == before_legacy_assignments

        # Only the confirmed roles this migration actually created are gone.
        names = await _role_names()
        assert names == {"administrator", "viewer", "biomedical_engineer"}
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Roadmap PR12 review finding PR12-M1 / PR12-M1R: migration
# 0010_inventory_import_columns.py's real upgrade/downgrade/re-upgrade
# behavior from an actual 0009 baseline, proven against a real PostgreSQL
# database.
#
# Structural trap this repeatedly fell into (PR12-M1R): migration
# 0001_initial.py builds its schema from `Base.metadata.create_all()` --
# the *current* ORM model, which already declares `asset_id` and
# `raw_source_status`. On a fresh scratch database, upgrading only to
# 0009_role_consolidation therefore already has both columns (0010's own
# `ADD COLUMN IF NOT EXISTS` becomes a silent no-op), and once a genuine
# downgrade later drops them for real, any query built through the
# current `Equipment` ORM class fails with `UndefinedColumnError` because
# the model still declares columns the live database no longer has.
#
# So this suite proves two things independently, exactly as the review
# requires:
#   1. Fresh-schema convergence: a brand-new database upgraded straight
#      to head ends up with the columns/index (this alone does NOT prove
#      migration 0010 did the work -- 0001 could have supplied them).
#   2. Historical-schema round trip: a database deliberately stripped of
#      the 0010 additions after reaching 0009 (simulating the schema a
#      real pre-PR12 deployment would have) is upgraded through Alembic,
#      which must perform the ADD COLUMN work for real this time, then is
#      downgraded and re-upgraded. All inspection/seeding across the
#      "historical" window uses raw SQL (`_equipment_columns`/
#      `_equipment_indexes`/`text()`), never the current ORM class, so the
#      test cannot accidentally depend on the schema already matching it.
# ---------------------------------------------------------------------------


async def test_migration_0010_fresh_database_upgrade_to_head_converges_on_expected_schema():
    """Fresh-schema convergence only -- does not by itself prove 0010 did
    the work (0001 already builds from current ORM metadata), but proves
    a brand-new deployment ends up in the right final state."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")
        columns = await _equipment_columns()
        assert {"asset_id", "raw_source_status"} <= columns

        indexes = await _equipment_indexes()
        by_name = {idx["name"]: idx for idx in indexes}
        assert "ix_equipment_asset_id" in by_name
        assert by_name["ix_equipment_asset_id"]["unique"] is False
        assert by_name["ix_equipment_asset_id"]["column_names"] == ["asset_id"]
    finally:
        await _drop_scratch_database()


async def _strip_0010_additions_to_build_historical_0009_schema(engine) -> None:
    """After `alembic upgrade 0009_role_consolidation` on a fresh scratch
    database, `asset_id`/`raw_source_status`/`ix_equipment_asset_id`
    already exist -- supplied by 0001_initial's `Base.metadata.create_all()`
    against the *current* ORM model, not by any migration between 0002
    and 0009. This deliberately removes them via raw DDL so the database
    is actually shaped like a real pre-0010 deployment before migration
    0010 is exercised through Alembic."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS ix_equipment_asset_id"))
        await conn.execute(text("ALTER TABLE equipment DROP COLUMN IF EXISTS raw_source_status"))
        await conn.execute(text("ALTER TABLE equipment DROP COLUMN IF EXISTS asset_id"))


async def _insert_historical_pre_0010_equipment(engine, *, asset_number: str, equipment_name: str) -> str:
    """Raw-SQL insert (not the ORM) -- the live schema at this point in
    the test is the historical pre-0010 shape, which the current
    `Equipment` model no longer accurately describes."""
    equipment_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata) "
                "VALUES (:id, :asset_number, :equipment_name, 'available_at_pool', '{}')"
            ),
            {"id": equipment_id, "asset_number": asset_number, "equipment_name": equipment_name},
        )
    return equipment_id


async def _fetch_equipment_row_via_raw_sql(engine, equipment_id: str) -> dict | None:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT * FROM equipment WHERE id = :id"), {"id": equipment_id})
        row = result.mappings().first()
        return dict(row) if row is not None else None


async def test_migration_0010_historical_0009_upgrade_downgrade_re_upgrade_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0009_role_consolidation")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            await _strip_0010_additions_to_build_historical_0009_schema(engine)

            # Genuine historical baseline, confirmed absent -- not assumed.
            columns = await _equipment_columns()
            assert "asset_id" not in columns
            assert "raw_source_status" not in columns
            indexes = await _equipment_indexes()
            assert "ix_equipment_asset_id" not in {idx["name"] for idx in indexes}

            # Representative pre-0010 row, seeded via raw SQL against the
            # actual historical schema (the ORM model does not describe
            # this database state and must not be used here).
            equipment_id = await _insert_historical_pre_0010_equipment(
                engine, asset_number="AST-PR12-HIST-0001", equipment_name="Pre-PR12 Pump"
            )
        finally:
            await engine.dispose()

        # Real upgrade through Alembic -- 0010's ADD COLUMN work now
        # actually executes against a database that genuinely lacks the
        # columns, rather than silently no-op'ing.
        _run_alembic("upgrade", "head")
        columns = await _equipment_columns()
        assert {"asset_id", "raw_source_status"} <= columns
        indexes = await _equipment_indexes()
        by_name = {idx["name"]: idx for idx in indexes}
        assert "ix_equipment_asset_id" in by_name
        assert by_name["ix_equipment_asset_id"]["unique"] is False
        assert by_name["ix_equipment_asset_id"]["column_names"] == ["asset_id"]

        # The pre-existing row survives with both new columns NULL. At
        # this point the live schema matches the current ORM exactly, so
        # both raw SQL and the ORM are valid; use the ORM to also prove
        # the model can write back into the newly added columns like any
        # inventory-import-created row.
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_maker() as session:
                row = (await session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))).scalar_one()
                assert row.equipment_name == "Pre-PR12 Pump"
                assert row.asset_id is None
                assert row.raw_source_status is None
                row.asset_id = "AID-0001"
                row.raw_source_status = "Active"
                await session.commit()
        finally:
            await engine.dispose()

        # Real downgrade -- columns/index genuinely dropped. From this
        # point until the re-upgrade below, only raw SQL is valid: the
        # current ORM class still declares asset_id/raw_source_status,
        # and a SELECT built through it would raise UndefinedColumnError
        # against a database that no longer has them.
        _run_alembic("downgrade", "0009_role_consolidation")
        columns = await _equipment_columns()
        assert "asset_id" not in columns
        assert "raw_source_status" not in columns
        indexes = await _equipment_indexes()
        assert "ix_equipment_asset_id" not in {idx["name"] for idx in indexes}

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            # asset_id/raw_source_status values written after the upgrade
            # are necessarily discarded with the dropped columns --
            # documented, expected downgrade behavior (see 0010's
            # docstring). Only pre-0010 fields are expected to survive.
            row = await _fetch_equipment_row_via_raw_sql(engine, equipment_id)
            assert row is not None
            assert row["equipment_name"] == "Pre-PR12 Pump"
            assert "asset_id" not in row
            assert "raw_source_status" not in row
        finally:
            await engine.dispose()

        # Re-upgrade: convergence proven a second time, from the real
        # historical-turned-downgraded state, not merely once from fresh.
        _run_alembic("upgrade", "head")
        columns = await _equipment_columns()
        assert {"asset_id", "raw_source_status"} <= columns
        indexes = await _equipment_indexes()
        assert "ix_equipment_asset_id" in {idx["name"] for idx in indexes}

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_maker() as session:
                row = (await session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))).scalar_one()
                assert row.equipment_name == "Pre-PR12 Pump"
                # Re-added columns start NULL again -- the downgrade's
                # column drop was real, not a no-op.
                assert row.asset_id is None
                assert row.raw_source_status is None
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


# ---------------------------------------------------------------------------
# Roadmap PR14B (Pagination Performance): migration 0011 adds two composite
# ordering indexes -- ix_equipment_created_at_id, ix_borrow_transactions_
# created_at_id -- matching app.crud.equipment.search()'s and app.crud.
# transaction.search()'s real `ORDER BY created_at DESC, id DESC` cursor-
# pagination clause. Index-only: no column, constraint, or data change. See
# docs/audits/06-pr14b-pagination-index-evidence.md for the full
# EXPLAIN (ANALYZE, BUFFERS) evidence this migration is based on.
# ---------------------------------------------------------------------------

EQUIPMENT_INDEX_NAME = "ix_equipment_created_at_id"
TRANSACTIONS_INDEX_NAME = "ix_borrow_transactions_created_at_id"


async def _pagination_indexdefs() -> dict[str, str]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE indexname IN (:eq, :tx)"),
                {"eq": EQUIPMENT_INDEX_NAME, "tx": TRANSACTIONS_INDEX_NAME},
            )
            return {row.indexname: row.indexdef for row in result.all()}
    finally:
        await engine.dispose()


async def test_migration_0011_fresh_database_upgrade_to_head_converges_on_expected_schema():
    """Fresh-schema convergence only -- 0001 never creates these indexes
    (they are deliberately absent from the ORM models, see 0011's own
    docstring on why), so this also proves 0011 is not silently skipped
    on a brand-new deployment."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")
        indexdefs = await _pagination_indexdefs()
        assert set(indexdefs) == {"ix_equipment_created_at_id", "ix_borrow_transactions_created_at_id"}
    finally:
        await _drop_scratch_database()


async def test_migration_0011_historical_0010_upgrade_downgrade_re_upgrade_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # 0001 never creates these indexes regardless of ORM state (see
        # 0011's docstring), so 0010 is already a genuine "index absent"
        # baseline -- no raw-DDL stripping needed here, unlike 0010's own
        # historical test against 0009's ORM-drifted columns.
        _run_alembic("upgrade", "0010_inventory_import_columns")
        indexdefs = await _pagination_indexdefs()
        assert indexdefs == {}

        _run_alembic("upgrade", "head")
        indexdefs = await _pagination_indexdefs()
        assert set(indexdefs) == {"ix_equipment_created_at_id", "ix_borrow_transactions_created_at_id"}

        _run_alembic("downgrade", "0010_inventory_import_columns")
        indexdefs = await _pagination_indexdefs()
        assert indexdefs == {}

        _run_alembic("upgrade", "head")
        indexdefs = await _pagination_indexdefs()
        assert set(indexdefs) == {"ix_equipment_created_at_id", "ix_borrow_transactions_created_at_id"}
    finally:
        await _drop_scratch_database()


async def test_migration_0011_indexes_are_descending_matching_the_orm_query_order():
    """app.crud.equipment.search() and app.crud.transaction.search() both
    `.order_by(Model.created_at.desc(), Model.id.desc())` -- an ascending
    index on the same columns would not let PostgreSQL satisfy that
    ORDER BY without a Sort node, defeating the point of this migration."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")
        indexdefs = await _pagination_indexdefs()
        assert "DESC" in indexdefs["ix_equipment_created_at_id"]
        assert "created_at" in indexdefs["ix_equipment_created_at_id"]
        assert "DESC" in indexdefs["ix_borrow_transactions_created_at_id"]
        assert "created_at" in indexdefs["ix_borrow_transactions_created_at_id"]
    finally:
        await _drop_scratch_database()


async def test_migration_0011_planner_uses_the_new_index_for_first_page_equipment_query():
    """Review condition: 'the index is considered justified only if
    PostgreSQL actually chooses it' -- verified structurally via EXPLAIN,
    not assumed. Seeds enough rows that an unindexed first-page query
    would need a real sequential scan + sort, then asserts the planner's
    *actual* chosen plan (not just that the index exists) uses an Index
    Scan and contains no Sort node, for exactly the query app.crud.
    equipment.search() issues with no filters and no cursor."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata) "
                        "SELECT gen_random_uuid(), 'PLAN-' || g, 'Plan Test Device', 'available_at_pool', '{}' "
                        "FROM generate_series(1, 3000) AS g"
                    )
                )
            async with engine.connect() as conn:
                await conn.execute(text("ANALYZE equipment"))
                plan_rows = (
                    await conn.execute(
                        text(
                            "EXPLAIN SELECT * FROM equipment WHERE deleted_at IS NULL "
                            "ORDER BY created_at DESC, id DESC LIMIT 26"
                        )
                    )
                ).all()
                plan_text = "\n".join(row[0] for row in plan_rows)
                assert "Index Scan" in plan_text, f"expected an Index Scan, got:\n{plan_text}"
                assert "Sort" not in plan_text, f"an Index Scan should make a separate Sort node unnecessary:\n{plan_text}"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0011_cursor_pagination_returns_identical_complete_result_set():
    """Correctness, not just performance: paginating through every row
    with app.crud.equipment.search() (index present) must visit every
    seeded row exactly once, in the same order a single unpaginated query
    would return them -- proving the index changed the query plan, not
    the result."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        from app.crud import equipment as equipment_crud

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_maker() as session:
                for i in range(120):
                    session.add(
                        Equipment(asset_number=f"PAGE-{i:04d}", equipment_name=f"Pagination Device {i}")
                    )
                await session.commit()

            async with session_maker() as session:
                seen_ids: list[str] = []
                cursor = None
                for _ in range(20):  # 120 rows / limit 10 -> 12 pages; generous upper bound
                    rows, cursor, total = await equipment_crud.search(session, limit=10, cursor=cursor)
                    seen_ids.extend(str(r.id) for r in rows)
                    if cursor is None:
                        break

                assert total == 120
                assert len(seen_ids) == 120, "every row must be visited exactly once across all pages"
                assert len(set(seen_ids)) == 120, "no row may be returned on more than one page"

                unpaginated, _, _ = await equipment_crud.search(session, limit=120)
                assert [str(r.id) for r in unpaginated] == seen_ids, (
                    "paginated traversal order must match a single unpaginated page's order"
                )
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_migration_0011_count_star_behavior_is_unchanged():
    """Explicit non-regression check for the Repository Owner's standing
    instruction that PR14B must not touch COUNT(*) behavior: `total` from
    app.crud.equipment.search() must still be a genuine, unindexed
    COUNT(*) over deleted_at IS NULL, not an index-derived estimate."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        from app.crud import equipment as equipment_crud

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_maker() as session:
                for i in range(15):
                    session.add(Equipment(asset_number=f"CNT-{i:04d}", equipment_name=f"Count Device {i}"))
                deleted = Equipment(asset_number="CNT-DELETED", equipment_name="Soft Deleted")
                session.add(deleted)
                await session.flush()
                deleted.deleted_at = datetime.utcnow()
                await session.commit()

            async with session_maker() as session:
                _, _, total = await equipment_crud.search(session, limit=5)
                assert total == 15, "soft-deleted rows must still be excluded from the count, exactly as before"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def _mark_index_invalid(engine, index_name: str) -> None:
    """Simulates the exact state PostgreSQL leaves behind when a `CREATE
    INDEX CONCURRENTLY` build is interrupted (process killed, connection
    lost, deadlock, genuine build failure): a relation with the target
    name exists, but `pg_index.indisvalid` is false. Manipulating
    `pg_index` directly (rather than actually interrupting a build, which
    is not deterministically reproducible in a test) is the standard way
    to reproduce this state for testing -- the migration code under test
    only ever reads this catalog state, never distinguishes how it arose."""
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE pg_index SET indisvalid = false WHERE indexrelid = to_regclass(:name)"),
            {"name": index_name},
        )


async def test_migration_0011_interrupted_concurrent_build_fails_closed_not_silent_skip():
    """Merge-blocking review finding: a bare `CREATE INDEX CONCURRENTLY
    IF NOT EXISTS` retry cannot tell an INVALID index (left behind by an
    interrupted build) apart from a genuinely completed one -- both
    satisfy `IF NOT EXISTS`, so a naive retry would silently skip forever
    and Alembic would record the migration as successful while the
    intended index is still unusable. This proves the actual failure
    mode end to end: a real `CREATE INDEX CONCURRENTLY` build, manually
    invalidated to reproduce an interrupted-build state, then a real
    `alembic upgrade` rerun through the CLI (not just calling the
    migration function directly) -- and that the rerun fails loudly
    rather than reporting success, does not partially apply, and that
    the documented recovery step (drop, then re-run) actually works."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0010_inventory_import_columns")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    text(f"CREATE INDEX CONCURRENTLY {EQUIPMENT_INDEX_NAME} ON equipment (created_at DESC, id DESC)")
                )
            await _mark_index_invalid(engine, EQUIPMENT_INDEX_NAME)

            # Confirm the simulated pre-condition before exercising the
            # migration against it -- this test must prove a genuinely
            # INVALID index, not assume one.
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT indisvalid, indisready FROM pg_index WHERE indexrelid = to_regclass(:name)"),
                        {"name": EQUIPMENT_INDEX_NAME},
                    )
                ).one()
                assert row.indisvalid is False, "test setup must produce a genuinely INVALID index before proceeding"
        finally:
            await engine.dispose()

        result = _run_alembic_allow_failure("upgrade", "head")
        assert result.returncode != 0, (
            "a rerun against an INVALID pre-existing index must fail, not silently report success:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        combined_output = result.stdout + result.stderr
        assert "not usable" in combined_output or "indisvalid" in combined_output, (
            f"failure must explain the detected invalid-index state, not fail for an unrelated reason:\n{combined_output}"
        )

        # Confirm the failure did not leave partial/misleading state: the
        # transactions index (unaffected by the simulated failure) must
        # still be genuinely absent -- the migration must not have
        # partially applied past the equipment index's failure.
        engine2 = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine2.connect() as conn:
                exists = (
                    await conn.execute(
                        text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
                        {"name": TRANSACTIONS_INDEX_NAME},
                    )
                ).scalar_one_or_none()
                assert exists is None, "the migration must not partially apply past the first failure"

            # Recovery path: drop the invalid index (the documented
            # operator remediation) and confirm the migration then
            # succeeds cleanly.
            async with engine2.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {EQUIPMENT_INDEX_NAME}"))
        finally:
            await engine2.dispose()

        _run_alembic("upgrade", "head")
        indexdefs = await _pagination_indexdefs()
        assert set(indexdefs) == {EQUIPMENT_INDEX_NAME, TRANSACTIONS_INDEX_NAME}
    finally:
        await _drop_scratch_database()


async def test_migration_0011_mismatched_definition_fails_closed():
    """Second fail-closed path: an existing, *valid* index that happens
    to share the expected name but not the expected definition (e.g. a
    manually created index, or a name collision from unrelated tooling)
    must not be silently treated as "this migration's work is already
    done" either."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "0010_inventory_import_columns")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                # Ascending, not the expected descending composite order --
                # valid and ready, but not what this migration expects.
                await conn.execute(text(f"CREATE INDEX {EQUIPMENT_INDEX_NAME} ON equipment (created_at ASC)"))
        finally:
            await engine.dispose()

        result = _run_alembic_allow_failure("upgrade", "head")
        assert result.returncode != 0, "a mismatched existing index must fail the migration, not be silently accepted"
        combined_output = result.stdout + result.stderr
        assert "does not match" in combined_output or "Expected" in combined_output, (
            f"failure must explain the detected definition mismatch:\n{combined_output}"
        )
    finally:
        await _drop_scratch_database()


async def test_migration_0011_planner_uses_the_new_index_for_first_page_transaction_query():
    """Same 'presence alone is insufficient' requirement as the equipment
    planner test above, verified independently for borrow_transactions --
    the two tables have independent indexes and independent query shapes
    (no `deleted_at` filter on transactions)."""
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")

        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, asset_number, equipment_name, status, metadata) "
                        "VALUES (gen_random_uuid(), 'PLANTX-EQ-0001', 'Plan Test Device', 'available_at_pool', '{}')"
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO borrow_transactions "
                        "(id, transaction_no, equipment_id, quantity, status, condition_on_return, borrowed_at) "
                        "SELECT gen_random_uuid(), 'PLANTX-' || g, "
                        "(SELECT id FROM equipment WHERE asset_number = 'PLANTX-EQ-0001'), "
                        "1, 'closed', 'available', now() "
                        "FROM generate_series(1, 3000) AS g"
                    )
                )
            async with engine.connect() as conn:
                await conn.execute(text("ANALYZE borrow_transactions"))
                plan_rows = (
                    await conn.execute(
                        text("EXPLAIN SELECT * FROM borrow_transactions ORDER BY created_at DESC, id DESC LIMIT 26")
                    )
                ).all()
                plan_text = "\n".join(row[0] for row in plan_rows)
                assert "Index Scan" in plan_text, f"expected an Index Scan, got:\n{plan_text}"
                assert "Sort" not in plan_text, f"an Index Scan should make a separate Sort node unnecessary:\n{plan_text}"
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()
