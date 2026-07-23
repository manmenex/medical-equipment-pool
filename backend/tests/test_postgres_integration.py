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
from app.models.user import ALL_ROLES, Role, User
# Roadmap PR7b: every dispatch now requires ward_id, so every HTTP-level
# /api/v1/borrow call in this suite needs a real ward row first --
# create_ward is the same helper test_borrow.py/test_equipment.py/
# test_exception_handling.py use (tests/conftest.py, consolidated here to
# remove a fourth near-duplicate definition).
from tests.conftest import create_ward as _create_ward

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

    async def _synchronized_close(db, tx, **kwargs):
        # Synchronous check-and-increment: no `await` between reading and
        # updating entrants["n"], so this is atomic under asyncio's
        # cooperative scheduling -- exactly `barrier_size` calls (the first
        # to arrive) wait, matching the barrier's party count exactly, so it
        # always releases cleanly with no leftover waiters.
        entrants["n"] += 1
        seat = entrants["n"]
        if seat <= barrier_size:
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
