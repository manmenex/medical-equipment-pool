"""Roadmap PR19A2 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §9,
§10, §11, §12, §13). Covers: source freeze/admission, off-thread parsing,
batch validation (no N+1), validation snapshot atomicity, warning
semantics, lease/heartbeat, completion fencing, recovery, and the
validate/recover/errors API surface."""

import asyncio
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit import AUDIT_ACTION_IMPORT_RECOVERY, AUDIT_ENTITY_IMPORT_SESSION
from app.core.exceptions import ImportSessionInvalidStateError
from app.crud import import_job as import_job_crud
from app.crud import import_session as import_crud
from app.models.audit import AuditLog
from app.models.import_session import ImportJob, ImportRowError, ImportSession, ImportSource
from app.models.user import User
from app.services import import_lease, import_validation_service
from app.services.import_adapter import FieldError, ImportAdapter, RawImportRecord, get_adapter, register_adapter, unregister_adapter
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

VALID_CHECKSUM = "a" * 64
DATASET_TYPE = "pr19a2_test_dataset"


class FakeAdapter(ImportAdapter):
    """Test/fake adapter (§10: "Use test/fake adapters only") -- records
    call counts and the thread it parsed on, so tests can assert the N+1
    guard and off-thread execution structurally, not by inference."""

    dataset_type = DATASET_TYPE
    ruleset_version = "1"

    def __init__(self, *, rows: int = 3, field_errors_by_row: dict | None = None, raise_on_parse: bool = False):
        self.rows = rows
        self.field_errors_by_row = field_errors_by_row or {}
        self.raise_on_parse = raise_on_parse
        self.parse_calls = 0
        self.parse_thread_ident: int | None = None
        self.preload_calls = 0
        self.validate_calls = 0

    def parse(self, raw_input):
        self.parse_calls += 1
        self.parse_thread_ident = threading.get_ident()
        if self.raise_on_parse:
            raise RuntimeError("simulated adapter parse crash")
        return [RawImportRecord(row_number=i + 1, fields={"n": i}) for i in range(self.rows)]

    async def preload_business_context(self, db, records):
        self.preload_calls += 1
        return {"seen": len(records)}

    def validate_business_rules(self, record, context):
        self.validate_calls += 1
        assert context == {"seen": self.rows}, "preload_business_context's return value must reach every record"
        return self.field_errors_by_row.get(record.row_number, [])


@pytest_asyncio.fixture(autouse=True)
async def _patch_validation_service_session_factory(db_engine, monkeypatch):
    """`import_validation_service` uses `app.services.import_lease`'s
    shared renewal-loop/fence-lost-audit helpers, which import
    `AsyncSessionLocal` from `app.db.session` at module level, bound to
    `settings.DATABASE_URL`'s own engine -- a different, never-migrated
    in-memory SQLite database than this test module's `db_engine`
    fixture. The heartbeat renewal loop and TX2/TX3 all open their own
    session via that name, so it must be repointed at this test's own
    engine (the same convention `tests/test_dashboard_stream.py` already
    established for `app.api.v1.dashboard`'s own direct
    `AsyncSessionLocal` usage). Patched on `import_lease`, not
    `import_validation_service`, since PR19A3's H1 fix moved these
    mechanics into the one shared module every phase (validate, dry-run,
    execute) now calls -- see `test_import_execution.py`'s identical
    `_patch_execution_session_factories` fixture."""
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(import_lease, "AsyncSessionLocal", session_maker)


@pytest_asyncio.fixture
async def fake_adapter():
    adapter = FakeAdapter()
    register_adapter(adapter)
    yield adapter
    unregister_adapter(DATASET_TYPE)


async def _create_and_register(client: AsyncClient, headers: dict, *, dataset_type: str = DATASET_TYPE) -> dict:
    created = (await client.post("/api/v1/import-sessions", headers=headers, json={"dataset_type": dataset_type})).json()
    reg = await client.post(
        f"/api/v1/import-sessions/{created['id']}/source",
        headers=headers,
        json={"checksum": VALID_CHECKSUM, "byte_size": 100},
    )
    assert reg.status_code == 201, reg.text
    return created


async def _get_user_id(db_session, role: str = "administrator") -> uuid.UUID:
    result = await db_session.execute(select(User).where(User.employee_code == f"{role.upper()}001"))
    return result.scalar_one().id


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------


async def test_no_adapter_registered_by_default(seeded_users):
    assert get_adapter("some_dataset_nobody_registered") is None


async def test_adapter_registry_isolated_by_fixture(fake_adapter, seeded_users):
    assert get_adapter(DATASET_TYPE) is fake_adapter


async def test_validate_without_registered_adapter_returns_422(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers, dataset_type="no_adapter_for_this_type")
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "IMPORT_ADAPTER_NOT_REGISTERED"


# ---------------------------------------------------------------------------
# §6 Source freeze
# ---------------------------------------------------------------------------


async def test_validate_freezes_registered_source(client: AsyncClient, seeded_users, fake_adapter, db_session):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 200, r.text

    source = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session["id"])))
    ).scalar_one()
    assert source.status == "frozen"
    assert source.frozen_at is not None


async def test_validate_without_registered_source_returns_409(client: AsyncClient, seeded_users, fake_adapter):
    headers = await auth_headers(client)
    created = (await client.post("/api/v1/import-sessions", headers=headers, json={"dataset_type": DATASET_TYPE})).json()
    r = await client.post(f"/api/v1/import-sessions/{created['id']}/validate", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "IMPORT_SOURCE_NOT_REGISTERED"


async def test_frozen_source_cannot_be_corrected(client: AsyncClient, seeded_users, fake_adapter):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)

    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": "b" * 64, "byte_size": 999},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "IMPORT_SOURCE_MISMATCH"


async def test_correction_vs_freeze_race_only_one_wins(client: AsyncClient, seeded_users, db_session):
    """§6/§15.2: whichever of {a pre-freeze correction, a concurrent
    freeze} actually commits first wins the row's `status='registered'`
    state; the other's CAS affects zero rows and takes its own
    already-defined miss branch. Simulated deterministically: freeze the
    row directly (as validate admission would, mid-race), then attempt a
    correction -- the correction must observe the row as already frozen
    and fail closed, never silently reapply on top of a frozen row."""
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])

    # Simulate the freeze winning the race first.
    frozen, _session_row, _job_row = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )
    assert frozen is True

    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": "c" * 64, "byte_size": 1},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_SOURCE_MISMATCH"


async def test_validate_never_starts_before_freeze_commit(client: AsyncClient, seeded_users, db_session):
    """A crashing adapter (parse() raises immediately) must still have
    already committed the freeze -- admission and freeze are one
    transaction that commits before any parse/validate work begins."""
    crashing = FakeAdapter(raise_on_parse=True)
    register_adapter(crashing)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "validation_failed"

        source = (
            await db_session.execute(
                select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session["id"]))
            )
        ).scalar_one()
        assert source.status == "frozen"
    finally:
        unregister_adapter(DATASET_TYPE)


# ---------------------------------------------------------------------------
# §10 Adapter / off-thread execution
# ---------------------------------------------------------------------------


async def test_parse_runs_off_the_event_loop(client: AsyncClient, seeded_users, fake_adapter):
    main_thread_ident = threading.get_ident()
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 200, r.text
    assert fake_adapter.parse_calls == 1
    assert fake_adapter.parse_thread_ident is not None
    assert fake_adapter.parse_thread_ident != main_thread_ident


async def test_fake_parser_returns_deterministic_rows(client: AsyncClient, seeded_users, db_session):
    adapter = FakeAdapter(rows=4)
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["total_rows"] == 4
        assert r.json()["status"] == "validated"
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_parser_exception_follows_tx1_tx2_contract(client: AsyncClient, seeded_users, db_session):
    crashing = FakeAdapter(raise_on_parse=True)
    register_adapter(crashing)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "validation_failed"
        assert body["failure_reason"] is not None
        # §22: never the raw exception message/content.
        assert "simulated adapter parse crash" not in body["failure_reason"]

        job = (
            await db_session.execute(select(ImportJob).where(ImportJob.import_session_id == uuid.UUID(session["id"])))
        ).scalar_one()
        assert job.status == "failed"
        assert job.error_message is not None
        assert "simulated adapter parse crash" not in job.error_message
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_bounded_row_count(client: AsyncClient, seeded_users, monkeypatch):
    monkeypatch.setattr(import_validation_service, "MAX_IMPORT_ROWS", 2)
    adapter = FakeAdapter(rows=3)
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "validation_failed"
    finally:
        unregister_adapter(DATASET_TYPE)


# ---------------------------------------------------------------------------
# §9.4.2 Rollback-safe failure publication (ORM-expiry regression)
# ---------------------------------------------------------------------------
# `run_validation`'s failure path calls `await db.rollback()` before
# publishing via TX2. SQLAlchemy expires every ORM object attached to a
# session on rollback regardless of `expire_on_commit` -- a bare attribute
# access on one of those now-expired objects afterward (outside an awaited
# context) raises `sqlalchemy.exc.MissingGreenlet`. These tests force a real
# database round-trip inside the post-admission transaction (so there is
# genuine in-memory state for rollback to expire) before the failure, which
# is what previously reproduced the crash.


class _DbBackedFailingAdapter(ImportAdapter):
    """Case 1: `preload_business_context` performs a real, awaited query --
    making TX1's transaction genuinely active, not merely theoretically
    open -- before `validate_business_rules` raises."""

    dataset_type = DATASET_TYPE
    ruleset_version = "1"

    def __init__(self, *, rows: int = 2):
        self.rows = rows

    def parse(self, raw_input):
        return [RawImportRecord(row_number=i + 1, fields={}) for i in range(self.rows)]

    async def preload_business_context(self, db, records):
        await db.execute(select(ImportSession).limit(1))
        return None

    def validate_business_rules(self, record, context):
        raise RuntimeError("simulated business-rule crash after an active preload query")


async def test_failure_after_db_backed_preload_publishes_cleanly(client: AsyncClient, seeded_users, db_session):
    """Case 1: a real query runs in preload, then validation raises. TX1
    must roll back and TX2 must still publish `validation_failed` -- no
    `MissingGreenlet` from touching expired ORM state afterward."""
    adapter = _DbBackedFailingAdapter()
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "validation_failed"
        assert body["failure_reason"] is not None
        # §22: never the raw exception message/content.
        assert "simulated business-rule crash" not in body["failure_reason"]

        job = (
            await db_session.execute(select(ImportJob).where(ImportJob.import_session_id == uuid.UUID(session["id"])))
        ).scalar_one()
        assert job.status == "failed"
        assert job.error_message is not None
        assert "simulated business-rule crash" not in job.error_message
    finally:
        unregister_adapter(DATASET_TYPE)


class _DbBackedFindingThenFailAdapter(ImportAdapter):
    """Case 2: preload issues a real, executed write statement (not merely
    a read, and not merely a same-process Python list append) -- a genuine
    `UPDATE` sent to the database -- before `validate_business_rules`
    raises. `run_validation`'s own `db.add_all(findings)` is never reached
    in this scenario since the exception propagates out of the row loop
    before that call, which is exactly why this adapter must generate its
    own real database write to make the failing transaction genuinely
    active."""

    dataset_type = DATASET_TYPE
    ruleset_version = "1"

    def __init__(self, *, rows: int = 2):
        self.rows = rows

    def parse(self, raw_input):
        return [RawImportRecord(row_number=i + 1, fields={}) for i in range(self.rows)]

    async def preload_business_context(self, db, records):
        # A real write statement, actually sent to the database (0 rows
        # affected is fine -- what matters is that a genuine transaction
        # is now active with real executed SQL, not just a pending add).
        await db.execute(
            update(ImportJob).where(ImportJob.id == uuid.uuid4()).values(heartbeat_at=datetime.now(timezone.utc))
        )
        return None

    def validate_business_rules(self, record, context):
        raise RuntimeError("simulated crash after a real write was already executed in this transaction")


async def test_failure_after_active_transaction_discards_partial_data(client: AsyncClient, seeded_users, db_session):
    """Case 2: at least one real, executed write statement happens inside
    the post-admission transaction before the crash. Assert: rollback
    completes, failure publication succeeds without `MissingGreenlet`,
    job/session state is correct, and no partial validation data survives
    (no findings are ever persisted for this attempt)."""
    adapter = _DbBackedFindingThenFailAdapter()
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "validation_failed"
        assert body["failure_reason"] is not None

        job = (
            await db_session.execute(select(ImportJob).where(ImportJob.import_session_id == uuid.UUID(session["id"])))
        ).scalar_one()
        assert job.status == "failed"

        findings = (
            (await db_session.execute(select(ImportRowError).where(ImportRowError.import_job_id == job.id)))
            .scalars()
            .all()
        )
        assert findings == [], "no partial validation data may survive TX1's rollback"
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_late_worker_failure_publication_fenced_after_recovery(client: AsyncClient, seeded_users, db_session):
    """Case 3: TX2's failure publication uses the session version captured
    at admission time (exactly as `run_validation` does), and that captured
    value must still be correctly fenced out once a concurrent recovery has
    moved the session on -- mirroring the already-covered success-path
    fencing (`test_late_worker_cannot_publish_after_recovery`) for the
    failure path this fix touches directly. Fixing the ORM-expiry crash must
    never come at the cost of weakening this fencing check."""
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])

    owner_a = uuid.uuid4()
    _existed, session_row, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=owner_a, lease_duration_seconds=300
    )
    # Exactly what run_validation captures immediately after admission.
    captured_job_id = job.id
    captured_admitted_version = session_row.version

    await db_session.execute(
        ImportJob.__table__.update()
        .where(ImportJob.id == job.id)
        .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    recover_resp = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert recover_resp.status_code == 200

    late_failure_result = await import_job_crud.fenced_failure(
        db_session,
        job_id=captured_job_id,
        lease_owner=owner_a,
        lease_generation=1,
        session_id=session_id,
        expected_version=captured_admitted_version,
        failure_status="validation_failed",
        bounded_error_message="x",
    )
    assert late_failure_result is None, (
        "a worker fenced out by recovery must never publish failure using its captured (now stale) admitted "
        "version either"
    )


# ---------------------------------------------------------------------------
# §11 Batch validation / N+1 guard
# ---------------------------------------------------------------------------


async def test_preload_business_context_called_exactly_once(client: AsyncClient, seeded_users):
    adapter = FakeAdapter(rows=5)
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        assert adapter.preload_calls == 1
        assert adapter.validate_calls == 5
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_validate_business_rules_receives_no_db_session():
    """Structural guarantee (§11): the signature itself has no session
    parameter -- verified by introspection, not merely by convention."""
    import inspect

    sig = inspect.signature(ImportAdapter.validate_business_rules)
    assert "db" not in sig.parameters
    assert list(sig.parameters) == ["self", "record", "context"]


# ---------------------------------------------------------------------------
# §13 Warning vs error semantics
# ---------------------------------------------------------------------------


async def test_warnings_never_block_validated(client: AsyncClient, seeded_users):
    adapter = FakeAdapter(
        rows=2, field_errors_by_row={1: [FieldError(field="x", error_code="W1", message="warn", severity="warning")]}
    )
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "validated"
        assert body["invalid_rows"] == 0
        assert body["warning_rows"] == 1
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_errors_always_block_validated(client: AsyncClient, seeded_users):
    adapter = FakeAdapter(
        rows=2, field_errors_by_row={1: [FieldError(field="x", error_code="E1", message="bad", severity="error")]}
    )
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "validation_failed"
        assert body["invalid_rows"] == 1
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_mixed_error_and_warning_blocks_only_because_of_error(client: AsyncClient, seeded_users):
    adapter = FakeAdapter(
        rows=2,
        field_errors_by_row={
            1: [FieldError(field="x", error_code="E1", message="bad", severity="error")],
            2: [FieldError(field="y", error_code="W1", message="warn", severity="warning")],
        },
    )
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        body = r.json()
        assert body["status"] == "validation_failed"
        assert body["invalid_rows"] == 1
        assert body["warning_rows"] == 1
        assert body["valid_rows"] == 1
    finally:
        unregister_adapter(DATASET_TYPE)


# ---------------------------------------------------------------------------
# §12 Validation snapshot atomicity
# ---------------------------------------------------------------------------


async def test_counters_and_findings_share_one_attempt(client: AsyncClient, seeded_users, db_session):
    adapter = FakeAdapter(
        rows=2, field_errors_by_row={1: [FieldError(field="x", error_code="E1", message="bad", severity="error")]}
    )
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)

        summary = await client.get(f"/api/v1/import-sessions/{session['id']}", headers=headers)
        attempt_id = summary.json()["validation_attempt_id"]
        assert attempt_id is not None

        errors = await client.get(f"/api/v1/import-sessions/{session['id']}/errors", headers=headers)
        assert errors.status_code == 200
        assert errors.json()["total"] == 1
        assert all(item for item in errors.json()["items"])
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_superseded_attempt_not_exposed_as_current(client: AsyncClient, seeded_users, db_session):
    """1. Attempt A produces errors. 2. Attempt B (re-validate) succeeds.
    3. Current API shows only B's counters/findings. 4. Attempt A remains
    historical only, reachable via ?attempt_id=."""
    failing = FakeAdapter(
        rows=1, field_errors_by_row={1: [FieldError(field="x", error_code="E1", message="bad", severity="error")]}
    )
    register_adapter(failing)
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    unregister_adapter(DATASET_TYPE)

    summary_a = (await client.get(f"/api/v1/import-sessions/{session['id']}", headers=headers)).json()
    attempt_a_id = summary_a["validation_attempt_id"]
    assert attempt_a_id is not None

    succeeding = FakeAdapter(rows=1)
    register_adapter(succeeding)
    try:
        r2 = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "validated"
    finally:
        unregister_adapter(DATASET_TYPE)

    summary_b = (await client.get(f"/api/v1/import-sessions/{session['id']}", headers=headers)).json()
    attempt_b_id = summary_b["validation_attempt_id"]
    assert attempt_b_id != attempt_a_id

    current_errors = (await client.get(f"/api/v1/import-sessions/{session['id']}/errors", headers=headers)).json()
    assert current_errors["total"] == 0

    historical_errors = (
        await client.get(f"/api/v1/import-sessions/{session['id']}/errors?attempt_id={attempt_a_id}", headers=headers)
    ).json()
    assert historical_errors["total"] == 1


async def test_errors_attempt_id_must_belong_to_this_session(client: AsyncClient, seeded_users):
    adapter = FakeAdapter(rows=1)
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session_a = await _create_and_register(client, headers)
        session_b = await _create_and_register(client, headers)
        await client.post(f"/api/v1/import-sessions/{session_a['id']}/validate", headers=headers)
        summary_a = (await client.get(f"/api/v1/import-sessions/{session_a['id']}", headers=headers)).json()

        r = await client.get(
            f"/api/v1/import-sessions/{session_b['id']}/errors?attempt_id={summary_a['validation_attempt_id']}",
            headers=headers,
        )
        assert r.status_code == 400
        assert r.json()["code"] == "INVALID_INPUT"
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_errors_with_no_validation_attempt_yet_is_empty(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    created = (await client.post("/api/v1/import-sessions", headers=headers, json={"dataset_type": DATASET_TYPE})).json()
    r = await client.get(f"/api/v1/import-sessions/{created['id']}/errors", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"items": [], "next_cursor": None, "total": 0}


async def test_errors_pagination_and_malformed_cursor(client: AsyncClient, seeded_users):
    many_errors = FakeAdapter(
        rows=3,
        field_errors_by_row={
            i: [FieldError(field="x", error_code="E1", message="bad", severity="error")] for i in (1, 2, 3)
        },
    )
    register_adapter(many_errors)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)

        page1 = await client.get(f"/api/v1/import-sessions/{session['id']}/errors?limit=2", headers=headers)
        assert page1.status_code == 200
        body1 = page1.json()
        assert len(body1["items"]) == 2
        assert body1["next_cursor"] is not None

        page2 = await client.get(
            f"/api/v1/import-sessions/{session['id']}/errors?limit=2&cursor={body1['next_cursor']}", headers=headers
        )
        body2 = page2.json()
        assert len(body2["items"]) == 1
        assert {i["id"] for i in body1["items"]} & {i["id"] for i in body2["items"]} == set()

        bad_cursor = await client.get(
            f"/api/v1/import-sessions/{session['id']}/errors?cursor=not-valid-base64!!", headers=headers
        )
        assert bad_cursor.status_code == 400
        assert bad_cursor.json()["code"] == "INVALID_INPUT"
    finally:
        unregister_adapter(DATASET_TYPE)


# ---------------------------------------------------------------------------
# §9.1/§9.2 Lease / heartbeat
# ---------------------------------------------------------------------------


async def test_heartbeat_renews_lease(monkeypatch):
    """§9.2's renewal loop, tested as a pure control-flow unit (its own
    session's DB interaction is already proven directly by
    `test_renew_lease_returns_false_once_lease_reassigned`): each tick
    calls `import_job_crud.renew_lease` using the loop's own session
    (`AsyncSessionLocal`, never the caller's), and keeps looping while
    renewal keeps succeeding. Exercises `app.services.import_lease`'s
    shared implementation -- the one `validate` itself calls (§25/H1: no
    private per-phase copy of this mechanism exists any more; see
    `tests/test_import_lease.py` for the shared-primitive-level suite)."""
    calls = []

    async def fake_renew_lease(db, *, job_id, lease_owner, lease_generation, lease_duration_seconds):
        calls.append((job_id, lease_owner, lease_generation))
        return len(calls) < 3  # renewed twice, then "lost" on the third tick

    class _NullSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(import_lease, "AsyncSessionLocal", lambda: _NullSession())
    monkeypatch.setattr(import_job_crud, "renew_lease", fake_renew_lease)

    job_id, owner = uuid.uuid4(), uuid.uuid4()
    await asyncio.wait_for(
        import_lease.renew_lease_loop(
            job_id=job_id, lease_owner=owner, lease_generation=1, lease_duration_seconds=300, heartbeat_interval_seconds=0
        ),
        timeout=2,
    )
    assert len(calls) == 3
    assert all(c == (job_id, owner, 1) for c in calls)


async def test_renew_lease_returns_false_once_lease_reassigned(db_session, seeded_users):
    """Direct crud-level proof of §9.2's "clean 0-row response = lease
    lost, stop immediately" contract."""
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    source = ImportSource(
        import_session_id=session.id,
        status="registered",
        checksum=VALID_CHECKSUM,
        byte_size=1,
        options_fingerprint="x",
        source_fingerprint="y",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.commit()

    owner_a = uuid.uuid4()
    _existed, _s, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session.id, expected_version=0, lease_owner=owner_a, lease_duration_seconds=300
    )
    assert job is not None

    renewed_correct_owner = await import_job_crud.renew_lease(
        db_session, job_id=job.id, lease_owner=owner_a, lease_generation=1, lease_duration_seconds=300
    )
    assert renewed_correct_owner is True

    renewed_wrong_owner = await import_job_crud.renew_lease(
        db_session, job_id=job.id, lease_owner=uuid.uuid4(), lease_generation=1, lease_duration_seconds=300
    )
    assert renewed_wrong_owner is False


async def test_expired_lease_becomes_recoverable(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])

    _existed, _s, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "validation_failed"


async def test_active_renewed_lease_is_not_recoverable(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])
    await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "IMPORT_SESSION_INVALID_STATE"


# ---------------------------------------------------------------------------
# §9.4 Fencing
# ---------------------------------------------------------------------------


async def test_success_fence_rejects_stale_owner(db_session, seeded_users):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ImportSource(
            import_session_id=session.id,
            status="registered",
            checksum=VALID_CHECKSUM,
            byte_size=1,
            options_fingerprint="x",
            source_fingerprint="y",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    owner_a = uuid.uuid4()
    _existed, session_row, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session.id, expected_version=0, lease_owner=owner_a, lease_duration_seconds=300
    )

    result = await import_job_crud.fenced_success(
        db_session,
        job_id=job.id,
        lease_owner=uuid.uuid4(),  # wrong owner -- a "late worker"
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        new_session_status="validated",
        total_rows=1,
        valid_rows=1,
        invalid_rows=0,
        warning_rows=0,
    )
    assert result is None


async def test_failure_fence_rejects_stale_owner(db_session, seeded_users):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ImportSource(
            import_session_id=session.id,
            status="registered",
            checksum=VALID_CHECKSUM,
            byte_size=1,
            options_fingerprint="x",
            source_fingerprint="y",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    owner_a = uuid.uuid4()
    _existed, session_row, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session.id, expected_version=0, lease_owner=owner_a, lease_duration_seconds=300
    )

    result = await import_job_crud.fenced_failure(
        db_session,
        job_id=job.id,
        lease_owner=uuid.uuid4(),
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        failure_status="validation_failed",
        bounded_error_message="x",
    )
    assert result is None


# ---------------------------------------------------------------------------
# PR19A3 review round 2 -- validation completion timestamp chronology.
#
# A prior shared-primitives refactor (H1) accidentally inverted PR19A2's
# original observable invariant by capturing the session's own
# `validated_at`/`updated_at` in `fenced_success`'s wrapper *before*
# calling into the shared `fenced_phase_success` primitive, which
# computes `job.finished_at` only afterward. The fix restores the
# original ordering (job fence -> job.finished_at -> session's own
# completion timestamp) by deriving the session timestamp from the
# `now` the shared primitive hands back post-fence, via a callback.
# ---------------------------------------------------------------------------


async def test_successful_validation_chronology(client: AsyncClient, seeded_users, db_session):
    """Test 1: `job.finished_at <= session.validated_at ==
    session.updated_at` for a genuine successful validation -- not merely
    that all three timestamps exist."""
    adapter = FakeAdapter(rows=1)
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "validated"
    finally:
        unregister_adapter(DATASET_TYPE)

    session_id = uuid.UUID(session["id"])
    session_row = (await db_session.execute(select(ImportSession).where(ImportSession.id == session_id))).scalar_one()
    job_row = (
        await db_session.execute(select(ImportJob).where(ImportJob.import_session_id == session_id))
    ).scalar_one()

    assert job_row.finished_at is not None
    assert session_row.validated_at is not None
    assert session_row.updated_at is not None
    assert job_row.finished_at <= session_row.validated_at, (
        f"job.finished_at ({job_row.finished_at}) must be <= session.validated_at "
        f"({session_row.validated_at}) -- the job fence must complete before the session's own "
        "completion timestamp is established"
    )
    assert session_row.validated_at == session_row.updated_at


async def test_successful_validation_chronology_via_api_summary(client: AsyncClient, seeded_users, db_session):
    """Test 2: the same chronology, verified through the public summary
    endpoint's serialized response -- not just the raw ORM rows."""
    adapter = FakeAdapter(rows=1)
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_and_register(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
        assert r.status_code == 200, r.text
    finally:
        unregister_adapter(DATASET_TYPE)

    summary = (await client.get(f"/api/v1/import-sessions/{session['id']}", headers=headers)).json()
    assert summary["validated_at"] is not None
    assert summary["updated_at"] is not None
    validate_job = next(j for j in summary["jobs"] if j["job_type"] == "validate")
    assert validate_job["finished_at"] is not None

    job_finished_at = datetime.fromisoformat(validate_job["finished_at"])
    session_validated_at = datetime.fromisoformat(summary["validated_at"])
    session_updated_at = datetime.fromisoformat(summary["updated_at"])
    assert job_finished_at <= session_validated_at
    assert session_validated_at == session_updated_at


async def test_stale_fence_never_publishes_validated_at(db_session, seeded_users):
    """Test 3: a stale/superseded worker must never publish
    `session.validated_at` -- the fenced-out publication attempt must
    leave the session's completion timestamp untouched (still `None`),
    not manufacture a chronology from a failed publication."""
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ImportSource(
            import_session_id=session.id,
            status="registered",
            checksum=VALID_CHECKSUM,
            byte_size=1,
            options_fingerprint="x",
            source_fingerprint="y",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    session_id = session.id
    owner_a = uuid.uuid4()
    _existed, session_row, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=owner_a, lease_duration_seconds=300
    )

    stale_result = await import_job_crud.fenced_success(
        db_session,
        job_id=job.id,
        lease_owner=uuid.uuid4(),  # wrong owner -- a "late"/superseded worker
        lease_generation=1,
        session_id=session_id,
        expected_version=session_row.version,
        new_session_status="validated",
        total_rows=1,
        valid_rows=1,
        invalid_rows=0,
        warning_rows=0,
    )
    assert stale_result is None
    await db_session.rollback()

    # `db_session.rollback()` expires every ORM object attached to the
    # session (`expire_on_commit=False` only protects against `commit()`)
    # -- `session_id` was captured above, before this point, precisely to
    # avoid a bare attribute access on the now-expired `session` instance.
    db_session.expire_all()
    fresh_session = (await db_session.execute(select(ImportSession).where(ImportSession.id == session_id))).scalar_one()
    assert fresh_session.validated_at is None, "a fenced-out worker must never publish session.validated_at"
    assert fresh_session.status == "validating", "the session must remain exactly where the real owner left it"


async def test_lost_session_fence_leaves_no_partial_committed_state(db_session, db_engine, seeded_users):
    """Test 4: if the job-level fence succeeds but the session-level fence
    is then lost (e.g. a concurrent recovery already bumped the session's
    version), the whole transaction must roll back -- there must be no
    committed state where the job is `succeeded` while the session was
    never actually moved to `validated`. Mirrors §9.4.1 step 6's own
    contract, exercised directly at the primitive level with a real,
    uncommitted transaction."""
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    session_id = session.id
    db_session.add(
        ImportSource(
            import_session_id=session_id,
            status="registered",
            checksum=VALID_CHECKSUM,
            byte_size=1,
            options_fingerprint="x",
            source_fingerprint="y",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    owner_a = uuid.uuid4()
    _existed, session_row, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=owner_a, lease_duration_seconds=300
    )
    job_id = job.id
    admitted_version = session_row.version

    # A concurrent recovery (or any other unrelated version bump) moves the
    # session on before this worker's own completion write reaches the
    # session-level fence -- using a *different* connection/session (bound
    # to the real `db_engine` fixture, not `db_session.get_bind()`, which
    # for an AsyncSession unwraps to the underlying sync Engine, not an
    # AsyncEngine), to genuinely simulate a concurrent actor rather than
    # mutating the same in-flight transaction.
    other_session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with other_session_maker() as other_db:
        await other_db.execute(
            ImportSession.__table__.update().where(ImportSession.id == session_id).values(version=ImportSession.version + 1)
        )
        await other_db.commit()

    result = await import_job_crud.fenced_success(
        db_session,
        job_id=job_id,
        lease_owner=owner_a,
        lease_generation=1,
        session_id=session_id,
        expected_version=admitted_version,  # stale -- the concurrent bump moved the real version on
        new_session_status="validated",
        total_rows=1,
        valid_rows=1,
        invalid_rows=0,
        warning_rows=0,
    )
    assert result is None, "the session-level fence must be lost once a concurrent actor bumped the version"

    # Exactly what run_validation does on a lost fence (§9.4.2): roll back
    # the whole transaction, including the job UPDATE that already
    # succeeded inside it.
    await db_session.rollback()

    async with other_session_maker() as verify_db:
        job_row = (await verify_db.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
        session_row_after = (await verify_db.execute(select(ImportSession).where(ImportSession.id == session_id))).scalar_one()

    assert job_row.status != "succeeded", "rollback must discard the job UPDATE too -- no partial committed state"
    assert job_row.status == "running"
    assert session_row_after.status != "validated"
    assert session_row_after.validated_at is None


async def test_late_worker_cannot_publish_after_recovery(client: AsyncClient, seeded_users, db_session):
    """§9.6 Diagram 2/7: recovery claims a stale-expired job, then the
    original (slow but alive) worker's own completion write must be
    rejected by the fencing check."""
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])

    owner_a = uuid.uuid4()
    _existed, session_row, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=owner_a, lease_duration_seconds=300
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    recover_resp = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert recover_resp.status_code == 200

    late_result = await import_job_crud.fenced_success(
        db_session,
        job_id=job.id,
        lease_owner=owner_a,
        lease_generation=1,
        session_id=session_id,
        expected_version=session_row.version,
        new_session_status="validated",
        total_rows=1,
        valid_rows=1,
        invalid_rows=0,
        warning_rows=0,
    )
    assert late_result is None, "a worker fenced out by recovery must never be able to publish its own completion"


# ---------------------------------------------------------------------------
# §9.3 Recovery
# ---------------------------------------------------------------------------


async def test_recovery_is_single_winner(db_session, seeded_users):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ImportSource(
            import_session_id=session.id,
            status="registered",
            checksum=VALID_CHECKSUM,
            byte_size=1,
            options_fingerprint="x",
            source_fingerprint="y",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    _existed, _s, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session.id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    first_claim = await import_job_crud.claim_stale_job(db_session, session_id=session.id)
    assert first_claim is not None
    phase = import_job_crud.PHASE_STATUS_MAP[first_claim.job_type]
    await import_job_crud.transition_session_for_recovery(
        db_session, session_id=session.id, running_status=phase["running_status"], failure_status=phase["failure_status"]
    )
    await db_session.commit()

    second_claim = await import_job_crud.claim_stale_job(db_session, session_id=session.id)
    assert second_claim is None, "recovery must be single-winner: nothing left to claim a second time"


async def test_no_duplicate_recovery_via_api(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])
    _existed, _s, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    r1 = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r1.status_code == 200
    r2 = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r2.status_code == 409
    assert r2.json()["code"] == "IMPORT_SESSION_INVALID_STATE"


async def test_recovery_preserves_frozen_source_identity(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])
    _existed, _s, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )
    source_before = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))
    ).scalar_one()

    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 200

    source_after = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))
    ).scalar_one()
    assert source_after.id == source_before.id
    assert source_after.source_fingerprint == source_before.source_fingerprint
    assert source_after.status == "frozen"


async def test_recovery_writes_audit_event(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])
    _existed, _s, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 200

    logs = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == AUDIT_ACTION_IMPORT_RECOVERY, AuditLog.entity_id == session_id)
        )
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].entity_type == AUDIT_ENTITY_IMPORT_SESSION


async def test_recover_nothing_to_recover_returns_409(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_SESSION_INVALID_STATE"


# ---------------------------------------------------------------------------
# API / RBAC
# ---------------------------------------------------------------------------


async def test_validate_requires_administrator(client: AsyncClient, seeded_users, fake_adapter):
    headers = await auth_headers(client, role="equipment_pool_staff")
    admin_headers = await auth_headers(client)
    session = await _create_and_register(client, admin_headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 403


async def test_recover_requires_administrator(client: AsyncClient, seeded_users):
    headers = await auth_headers(client, role="equipment_pool_staff")
    admin_headers = await auth_headers(client)
    session = await _create_and_register(client, admin_headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 403


async def test_errors_requires_administrator(client: AsyncClient, seeded_users):
    headers = await auth_headers(client, role="read_only")
    admin_headers = await auth_headers(client)
    session = await _create_and_register(client, admin_headers)
    r = await client.get(f"/api/v1/import-sessions/{session['id']}/errors", headers=headers)
    assert r.status_code == 403


async def test_validate_404_for_unknown_session(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{uuid.uuid4()}/validate", headers=headers)
    assert r.status_code == 404
    assert r.json()["code"] == "IMPORT_SESSION_NOT_FOUND"


async def test_dry_run_and_execute_reachable_but_reject_a_freshly_created_session(client: AsyncClient, seeded_users):
    """§25: PR19A2 itself registers exactly #7-#9 (recover, validate,
    errors). Dry-run/execute are PR19A3's own endpoints -- reachable now
    that PR19A3 has shipped, but a freshly-created (never validated)
    session is not in either endpoint's admittable state set, so both
    correctly reject it as a 409 state conflict rather than a 404 route
    miss (proving they exist and enforce their own precondition, not that
    they are absent)."""
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    for path in ("dry-run", "execute"):
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/{path}", headers=headers)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "IMPORT_SESSION_INVALID_STATE"


async def test_concurrent_validate_returns_attempt_in_progress(client: AsyncClient, seeded_users, db_session):
    """§7/§17: a second validate call while one is already running (lease
    not expired) must not be admitted a second time."""
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])
    await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_ATTEMPT_IN_PROGRESS"


async def test_validate_with_expired_lease_returns_recovery_required(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)
    session_id = uuid.UUID(session["id"])
    _existed, _s, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session_id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_RECOVERY_REQUIRED"
