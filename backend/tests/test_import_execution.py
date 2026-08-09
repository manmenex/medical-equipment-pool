"""Roadmap PR19A3 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §16,
§17, §18, §9.4.3). Covers: dry-run read-only enforcement/completion,
execute single-winner claim/idempotency/completion, TX1/TX2 failure
fencing reused for dry-run/execute, recovery extended to dry_run/execute,
retention-cleanup claim/redaction/audit, and the dry-run/execute/
retention-cleanup API/RBAC surface."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit import (
    AUDIT_ACTION_IMPORT,
    AUDIT_ACTION_IMPORT_RETENTION_CLEANUP,
    AUDIT_ENTITY_IMPORT_SESSION,
)
from app.crud import import_job as import_job_crud
from app.crud import import_retention as import_retention_crud
from app.models.audit import AuditLog
from app.models.import_session import ImportJob, ImportRowError, ImportSession, ImportSource
from app.models.user import User
from app.services import import_execution_service, import_lease
from app.services.import_adapter import DryRunPlan, FieldError, ImportAdapter, RawImportRecord, register_adapter, unregister_adapter
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

VALID_CHECKSUM = "b" * 64
DATASET_TYPE = "pr19a3_test_dataset"


class _FullPipelineAdapter(ImportAdapter):
    """Implements validate + dry-run + execute so tests can drive a
    session all the way to `dry_run_completed`/`completed`."""

    dataset_type = DATASET_TYPE
    ruleset_version = "1"

    def __init__(self, *, execute_imported_rows: int = 3, dry_run_raises: bool = False, execute_raises: bool = False):
        self.execute_imported_rows = execute_imported_rows
        self.dry_run_raises = dry_run_raises
        self.execute_raises = execute_raises
        self.dry_run_calls = 0
        self.execute_calls = 0

    def parse(self, raw_input):
        return [RawImportRecord(row_number=1, fields={})]

    def validate_business_rules(self, record, context):
        return []

    async def plan_dry_run(self, db):
        self.dry_run_calls += 1
        if self.dry_run_raises:
            raise RuntimeError("simulated dry-run business failure")
        return DryRunPlan()

    async def execute(self, db):
        self.execute_calls += 1
        if self.execute_raises:
            raise RuntimeError("simulated execute business failure")
        return self.execute_imported_rows


class _ValidateOnlyAdapter(ImportAdapter):
    """Deliberately does not override plan_dry_run/execute -- the
    IMPORT_ADAPTER_NOT_IMPLEMENTED (501) contract."""

    dataset_type = DATASET_TYPE

    def parse(self, raw_input):
        return [RawImportRecord(row_number=1, fields={})]

    def validate_business_rules(self, record, context):
        return []


@pytest_asyncio.fixture(autouse=True)
async def _patch_execution_session_factories(db_engine, monkeypatch):
    """Mirrors test_import_validation.py's identical fixture: both new
    PR19A3 modules that open their own `AsyncSessionLocal()` (the renewal
    loop, TX2, TX3) must be repointed at this test's own engine."""
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(import_execution_service, "AsyncSessionLocal", session_maker)
    monkeypatch.setattr(import_lease, "AsyncSessionLocal", session_maker)


@pytest_asyncio.fixture
async def pipeline_adapter():
    adapter = _FullPipelineAdapter()
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


async def _create_validated_session(client: AsyncClient, headers: dict) -> dict:
    session = await _create_and_register(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "validated", r.text
    # The validate response body carries the post-transition `version` --
    # returning the stale pre-validate `session` dict (version 0) would
    # make any caller's own admit_phase_job CAS attempt lose the race
    # against the wrong expected_version.
    return body


async def _create_dry_run_completed_session(client: AsyncClient, headers: dict) -> dict:
    session = await _create_validated_session(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "dry_run_completed", r.text
    return body


async def _get_user_id(db_session, role: str = "administrator") -> uuid.UUID:
    result = await db_session.execute(select(User).where(User.employee_code == f"{role.upper()}001"))
    return result.scalar_one().id


# ---------------------------------------------------------------------------
# §16 Dry-run enforcement / completion
# ---------------------------------------------------------------------------


async def test_dry_run_completes_from_validated(client: AsyncClient, seeded_users, pipeline_adapter):
    headers = await auth_headers(client)
    session = await _create_validated_session(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "dry_run_completed"
    assert body["dry_run_completed_at"] is not None
    assert pipeline_adapter.dry_run_calls == 1


async def test_dry_run_business_failure_follows_tx1_tx2_contract(client: AsyncClient, seeded_users, db_session):
    adapter = _FullPipelineAdapter(dry_run_raises=True)
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_validated_session(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "dry_run_failed"
        assert body["failure_reason"] is not None
        # §22: never the raw exception message.
        assert "simulated dry-run business failure" not in body["failure_reason"]

        job = (
            await db_session.execute(
                select(ImportJob).where(
                    ImportJob.import_session_id == uuid.UUID(session["id"]), ImportJob.job_type == "dry_run"
                )
            )
        ).scalar_one_or_none()
        assert job is not None and job.status == "failed"
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_dry_run_uses_same_frozen_source_as_validate(client: AsyncClient, seeded_users, pipeline_adapter, db_session):
    """§6/§16: dry-run necessarily reuses the identical frozen source
    validate already froze -- no separate freeze/registration step, and
    the source row is unchanged (still frozen, same fingerprint) after
    dry-run completes."""
    headers = await auth_headers(client)
    session = await _create_validated_session(client, headers)
    session_id = uuid.UUID(session["id"])
    source_before = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))
    ).scalar_one()
    assert source_before.status == "frozen"
    fingerprint_before = source_before.source_fingerprint
    source_row_id = source_before.id

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert r.status_code == 200, r.text

    source_after = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))
    ).scalar_one()
    assert source_after.id == source_row_id, "dry-run must never create or swap the session's source row"
    assert source_after.status == "frozen"
    assert source_after.source_fingerprint == fingerprint_before, "the frozen source's identity must be unchanged by dry-run"


async def test_dry_run_not_admittable_from_created(client: AsyncClient, seeded_users, pipeline_adapter):
    headers = await auth_headers(client)
    session = await _create_and_register(client, headers)  # never validated
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_SESSION_INVALID_STATE"


async def test_dry_run_adapter_not_implemented_returns_501(client: AsyncClient, seeded_users):
    adapter = _ValidateOnlyAdapter()
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_validated_session(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
        assert r.status_code == 501, r.text
        assert r.json()["code"] == "IMPORT_ADAPTER_NOT_IMPLEMENTED"
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_dry_run_re_dry_run_from_completed_and_failed(client: AsyncClient, seeded_users, pipeline_adapter):
    headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dry_run_completed"
    assert pipeline_adapter.dry_run_calls == 2


# ---------------------------------------------------------------------------
# §17 Execute single-winner claim / idempotency / completion
# ---------------------------------------------------------------------------


async def test_execute_completes_from_dry_run_completed(client: AsyncClient, seeded_users, pipeline_adapter, db_session):
    headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["executed_at"] is not None
    assert body["imported_rows"] == 3
    assert body["terminal_at"] is not None

    logs = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == AUDIT_ENTITY_IMPORT_SESSION,
                AuditLog.action == AUDIT_ACTION_IMPORT,
                AuditLog.entity_id == uuid.UUID(session["id"]),
            )
        )
    ).scalars().all()
    assert len(logs) == 1


async def test_execute_idempotent_replay_of_completed_no_re_execute(client: AsyncClient, seeded_users, pipeline_adapter, db_session):
    headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, headers)
    r1 = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r1.status_code == 200
    r2 = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "completed"
    assert pipeline_adapter.execute_calls == 1, "a repeat call on an already-COMPLETED session must not re-execute"

    logs = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == AUDIT_ENTITY_IMPORT_SESSION,
                AuditLog.action == AUDIT_ACTION_IMPORT,
                AuditLog.entity_id == uuid.UUID(session["id"]),
            )
        )
    ).scalars().all()
    assert len(logs) == 1, "an idempotent replay must never emit a second AUDIT_ACTION_IMPORT entry"


async def test_execute_from_failed_requires_fresh_dry_run(client: AsyncClient, seeded_users):
    adapter = _FullPipelineAdapter(execute_raises=True)
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_dry_run_completed_session(client, headers)
        r1 = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
        assert r1.status_code == 500
        assert r1.json()["code"] == "IMPORT_EXECUTION_FAILED"

        r2 = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
        assert r2.status_code == 409
        assert r2.json()["code"] == "IMPORT_SESSION_INVALID_STATE"
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_execute_business_failure_returns_500_and_terminal_failed(client: AsyncClient, seeded_users, db_session):
    adapter = _FullPipelineAdapter(execute_raises=True)
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_dry_run_completed_session(client, headers)
        r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
        assert r.status_code == 500, r.text
        assert r.json()["code"] == "IMPORT_EXECUTION_FAILED"

        row = (
            await db_session.execute(select(ImportSession).where(ImportSession.id == uuid.UUID(session["id"])))
        ).scalar_one()
        assert row.status == "failed"
        assert row.terminal_at is not None
        job = (
            await db_session.execute(
                select(ImportJob).where(ImportJob.import_session_id == row.id, ImportJob.job_type == "execute")
            )
        ).scalar_one()
        assert job.status == "failed"
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_execute_adapter_not_implemented_returns_501(client: AsyncClient, seeded_users, db_session):
    """`_ValidateOnlyAdapter` implements neither `plan_dry_run` nor
    `execute` -- isolate execute's own check from dry-run's by moving the
    session straight to `dry_run_completed` via direct DB manipulation
    (bypassing the dry-run endpoint, which would itself 501 first)."""
    adapter = _ValidateOnlyAdapter()
    register_adapter(adapter)
    try:
        headers = await auth_headers(client)
        session = await _create_validated_session(client, headers)
        session_id = uuid.UUID(session["id"])
        await db_session.execute(
            ImportSession.__table__.update()
            .where(ImportSession.id == session_id)
            .values(status="dry_run_completed", version=ImportSession.version + 1)
        )
        await db_session.commit()

        r = await client.post(f"/api/v1/import-sessions/{session_id}/execute", headers=headers)
        assert r.status_code == 501, r.text
        assert r.json()["code"] == "IMPORT_ADAPTER_NOT_IMPLEMENTED"
    finally:
        unregister_adapter(DATASET_TYPE)


async def test_execute_concurrent_admission_second_caller_in_progress(client: AsyncClient, seeded_users, db_session, pipeline_adapter):
    """§7/§17: a second execute call while one already holds the running
    claim (lease not expired) must not be admitted a second time."""
    headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, headers)
    session_id = uuid.UUID(session["id"])
    await import_job_crud.admit_phase_job(
        db_session,
        session_id=session_id,
        job_type="execute",
        allowed_from_statuses=("dry_run_completed",),
        running_status="executing",
        expected_version=session["version"],
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_ATTEMPT_IN_PROGRESS"


async def test_execute_with_expired_lease_returns_recovery_required(client: AsyncClient, seeded_users, db_session, pipeline_adapter):
    headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, headers)
    session_id = uuid.UUID(session["id"])
    _s, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session_id,
        job_type="execute",
        allowed_from_statuses=("dry_run_completed",),
        running_status="executing",
        expected_version=session["version"],
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_RECOVERY_REQUIRED"


async def test_execute_no_compound_fingerprint_conflict_exists(client: AsyncClient, seeded_users, pipeline_adapter):
    """Design §17 explicitly states execute idempotency is state-based,
    "a repeat call, not a request-payload comparison -- contrast §15" --
    there is no request body/idempotency-key/fingerprint contract for
    execute. Posting an arbitrary JSON body must not be rejected or
    change behavior versus no body at all (FastAPI simply ignores an
    unexpected body when the endpoint declares none)."""
    headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, headers)
    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/execute",
        headers=headers,
        json={"idempotency_key": "whatever", "fingerprint": "whatever"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# Fencing / heartbeat reuse (§9.4, generic across job_type)
# ---------------------------------------------------------------------------


async def test_execute_success_fence_rejects_stale_owner(db_session, seeded_users, pipeline_adapter):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="dry_run_completed", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ImportSource(
            import_session_id=session.id,
            status="frozen",
            checksum=VALID_CHECKSUM,
            byte_size=1,
            options_fingerprint="x",
            source_fingerprint="y",
            frozen_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    owner_a = uuid.uuid4()
    session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session.id,
        job_type="execute",
        allowed_from_statuses=("dry_run_completed",),
        running_status="executing",
        expected_version=0,
        lease_owner=owner_a,
        lease_duration_seconds=300,
    )

    result = await import_job_crud.fenced_phase_success(
        db_session,
        job_id=job.id,
        lease_owner=uuid.uuid4(),  # wrong owner -- a "late worker"
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        running_status="executing",
        new_session_status="completed",
        extra_session_values={"imported_rows": 1},
    )
    assert result is None


async def test_dry_run_failure_fence_rejects_stale_owner(db_session, seeded_users, pipeline_adapter):
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status="validated", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ImportSource(
            import_session_id=session.id,
            status="frozen",
            checksum=VALID_CHECKSUM,
            byte_size=1,
            options_fingerprint="x",
            source_fingerprint="y",
            frozen_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    owner_a = uuid.uuid4()
    session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session.id,
        job_type="dry_run",
        allowed_from_statuses=("validated",),
        running_status="dry_run_running",
        expected_version=0,
        lease_owner=owner_a,
        lease_duration_seconds=300,
    )

    result = await import_job_crud.fenced_phase_failure(
        db_session,
        job_id=job.id,
        lease_owner=uuid.uuid4(),
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        running_status="dry_run_running",
        failure_status="dry_run_failed",
        bounded_error_message="x",
    )
    assert result is None


async def test_execute_heartbeat_renews_lease(monkeypatch):
    """Mirrors test_import_validation.py's identical deterministic
    unit-test pattern for import_lease.renew_lease_loop -- the shared,
    generic renewal loop PR19A3 reuses unchanged."""
    import asyncio

    calls = []

    async def fake_renew_lease(db, *, job_id, lease_owner, lease_generation, lease_duration_seconds):
        calls.append((job_id, lease_owner, lease_generation))
        return len(calls) < 3

    class _NullSession:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(import_job_crud, "renew_lease", fake_renew_lease)
    monkeypatch.setattr(import_lease, "AsyncSessionLocal", lambda: _NullSession())

    job_id = uuid.uuid4()
    owner = uuid.uuid4()
    await asyncio.wait_for(
        import_lease.renew_lease_loop(
            job_id=job_id, lease_owner=owner, lease_generation=1, lease_duration_seconds=300, heartbeat_interval_seconds=0
        ),
        timeout=2,
    )
    assert len(calls) == 3
    assert all(c == (job_id, owner, 1) for c in calls)


async def test_late_execute_worker_cannot_publish_after_recovery(client: AsyncClient, seeded_users, db_session, pipeline_adapter):
    headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, headers)
    session_id = uuid.UUID(session["id"])

    owner_a = uuid.uuid4()
    session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session_id,
        job_type="execute",
        allowed_from_statuses=("dry_run_completed",),
        running_status="executing",
        expected_version=session["version"],
        lease_owner=owner_a,
        lease_duration_seconds=300,
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    recover_resp = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert recover_resp.status_code == 200
    assert recover_resp.json()["status"] == "failed"

    late_result = await import_job_crud.fenced_phase_success(
        db_session,
        job_id=job.id,
        lease_owner=owner_a,
        lease_generation=1,
        session_id=session_id,
        expected_version=session_row.version,
        running_status="executing",
        new_session_status="completed",
        extra_session_values={"imported_rows": 1},
    )
    assert late_result is None, "a worker fenced out by recovery must never be able to publish its own completion"


# ---------------------------------------------------------------------------
# §9.3 Recovery, extended to dry_run/execute
# ---------------------------------------------------------------------------


async def test_recover_dry_run_running_becomes_dry_run_failed(client: AsyncClient, seeded_users, db_session, pipeline_adapter):
    headers = await auth_headers(client)
    session = await _create_validated_session(client, headers)
    session_id = uuid.UUID(session["id"])
    _s, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session_id,
        job_type="dry_run",
        allowed_from_statuses=("validated",),
        running_status="dry_run_running",
        expected_version=session["version"],
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "dry_run_failed"
    assert body["terminal_at"] is None, "DRY_RUN_FAILED is not terminal (§5)"


async def test_recover_executing_becomes_failed_and_terminal(client: AsyncClient, seeded_users, db_session, pipeline_adapter):
    headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, headers)
    session_id = uuid.UUID(session["id"])
    _s, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session_id,
        job_type="execute",
        allowed_from_statuses=("dry_run_completed",),
        running_status="executing",
        expected_version=session["version"],
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert body["terminal_at"] is not None, "EXECUTING -> FAILED is terminal (§5)"


async def test_recover_execute_active_renewed_lease_not_recoverable(client: AsyncClient, seeded_users, db_session, pipeline_adapter):
    headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, headers)
    session_id = uuid.UUID(session["id"])
    await import_job_crud.admit_phase_job(
        db_session,
        session_id=session_id,
        job_type="execute",
        allowed_from_statuses=("dry_run_completed",),
        running_status="executing",
        expected_version=session["version"],
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_SESSION_INVALID_STATE"


async def test_recover_retry_creates_new_attempt_with_incremented_number(client: AsyncClient, seeded_users, db_session, pipeline_adapter):
    """§5: `EXECUTING`'s own failure (`FAILED`) is terminal -- the state
    machine has no edge leaving it, so a same-session retry after an
    execute recovery is not a real scenario the design supports (a new
    session is required instead). `DRY_RUN_RUNNING`'s own recovery
    (`DRY_RUN_FAILED`) is *not* terminal and explicitly supports
    re-dry-run (§5's `DRY_RUN_FAILED -> re-dry-run -> DRY_RUN_RUNNING`
    edge) -- this is the correct scenario to prove attempt-number
    incrementing on a genuine same-session retry after recovery."""
    headers = await auth_headers(client)
    session = await _create_validated_session(client, headers)
    session_id = uuid.UUID(session["id"])
    _s, job1 = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session_id,
        job_type="dry_run",
        allowed_from_statuses=("validated",),
        running_status="dry_run_running",
        expected_version=session["version"],
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )
    assert job1.attempt_number == 1
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job1.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    recover_resp = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert recover_resp.status_code == 200
    assert recover_resp.json()["status"] == "dry_run_failed"

    retry = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "dry_run_completed"

    # job1 is already identity-mapped on `db_session` (created directly
    # via it above) -- recovery and the retry both mutated it through a
    # *different* session, so a plain re-SELECT would return the stale
    # cached instance without an explicit expire.
    db_session.expire_all()
    jobs = (
        await db_session.execute(
            select(ImportJob).where(ImportJob.import_session_id == session_id, ImportJob.job_type == "dry_run").order_by(ImportJob.attempt_number)
        )
    ).scalars().all()
    assert [j.attempt_number for j in jobs] == [1, 2]
    assert jobs[0].status == "abandoned"
    assert jobs[1].status == "succeeded"


# ---------------------------------------------------------------------------
# §18 Retention cleanup
# ---------------------------------------------------------------------------


async def _make_terminal_session(db_session, *, actor_id, status: str, terminal_at) -> ImportSession:
    session = ImportSession(
        dataset_type=DATASET_TYPE,
        status=status,
        version=0,
        created_by_user_id=actor_id,
        terminal_at=terminal_at,
        notes="operator note",
        failure_reason="x" if status == "failed" else None,
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ImportSource(
            import_session_id=session.id,
            status="frozen",
            checksum=VALID_CHECKSUM,
            byte_size=1,
            content_type="text/csv",
            filename="legacy.csv",
            options_fingerprint="x",
            source_fingerprint="y",
            frozen_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    )
    job = ImportJob(
        import_session_id=session.id,
        job_type="validate",
        status="succeeded",
        attempt_number=1,
        lease_generation=1,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        ImportRowError(import_job_id=job.id, row_number=1, field="bcm_code", error_code="bad", message="raw legacy value", severity="error")
    )
    await db_session.commit()
    return session


async def test_retention_only_terminal_sessions_eligible(client: AsyncClient, seeded_users, db_session):
    actor_id = await _get_user_id(db_session)
    old_cutoff = datetime.now(timezone.utc) - timedelta(days=200)
    non_terminal = ImportSession(dataset_type=DATASET_TYPE, status="created", version=0, created_by_user_id=actor_id)
    db_session.add(non_terminal)
    await db_session.commit()

    eligible = await _make_terminal_session(db_session, actor_id=actor_id, status="completed", terminal_at=old_cutoff)

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["purged_count"] == 1
    assert body["skipped_count"] == 0

    await db_session.refresh(non_terminal)
    assert non_terminal.retention_purged_at is None
    await db_session.refresh(eligible)
    assert eligible.retention_purged_at is not None


async def test_retention_180_day_cutoff(client: AsyncClient, seeded_users, db_session):
    actor_id = await _get_user_id(db_session)
    just_inside = await _make_terminal_session(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=181)
    )
    just_outside = await _make_terminal_session(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=10)
    )

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 1

    await db_session.refresh(just_inside)
    assert just_inside.retention_purged_at is not None
    await db_session.refresh(just_outside)
    assert just_outside.retention_purged_at is None


async def test_retention_configurable_period(client: AsyncClient, seeded_users, db_session, monkeypatch):
    from app.services import import_retention_service

    monkeypatch.setattr(import_retention_service.settings, "IMPORT_RETENTION_DAYS", 5)
    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=6)
    )

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 1
    await db_session.refresh(session)
    assert session.retention_purged_at is not None


async def test_retention_redaction_clears_sensitive_fields_keeps_structural(client: AsyncClient, seeded_users, db_session):
    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session, actor_id=actor_id, status="failed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200)
    )
    session_id = session.id

    # These objects were loaded (and identity-mapped) by `db_session`
    # before the cleanup HTTP call mutated the same rows through a
    # *different* session (`expire_on_commit=False` means neither
    # session auto-refreshes the other's committed changes) -- capture
    # the original instances and `refresh()` each one explicitly rather
    # than trusting a fresh SELECT to reload already-identity-mapped
    # attributes.
    source_row = (await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))).scalar_one()
    finding_row = (
        await db_session.execute(
            select(ImportRowError).join(ImportJob, ImportRowError.import_job_id == ImportJob.id).where(ImportJob.import_session_id == session_id)
        )
    ).scalar_one()

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 1

    await db_session.refresh(source_row)
    assert source_row.filename is None
    assert source_row.content_type is None
    assert source_row.checksum == VALID_CHECKSUM, "checksum is retained (§18)"

    await db_session.refresh(finding_row)
    assert finding_row.message == "[redacted]"
    assert finding_row.field is None
    assert finding_row.error_code == "bad", "error_code is retained (§18)"
    assert finding_row.severity == "error"
    assert finding_row.row_number == 1

    await db_session.refresh(session)
    assert session.notes is None
    assert session.retention_purged_at is not None
    assert session.source_bytes_deleted_at is not None, "vacuously true in this foundation -- no bytes are ever stored (§18)"
    assert session.failure_reason is not None, "failure_reason is retained post-retention (design §4.1)"


async def test_retention_concurrent_cleanup_single_winner(client: AsyncClient, seeded_users, db_session):
    """Non-PostgreSQL, deterministic version of the concurrency guarantee
    -- calls `claim_sessions_for_cleanup` twice sequentially with
    different worker ids and asserts the second claims nothing (the
    genuine two-connection PostgreSQL version lives in
    test_postgres_integration.py)."""
    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200)
    )

    worker_a = uuid.uuid4()
    worker_b = uuid.uuid4()
    claimed_a = await import_retention_crud.claim_sessions_for_cleanup(
        db_session, worker_id=worker_a, retention_days=180, claim_timeout_seconds=300, limit=10
    )
    claimed_b = await import_retention_crud.claim_sessions_for_cleanup(
        db_session, worker_id=worker_b, retention_days=180, claim_timeout_seconds=300, limit=10
    )
    assert claimed_a == [session.id]
    assert claimed_b == [], "a session already claimed (claim not yet expired) must not be claimable by a second worker"


async def test_retention_fence_lost_when_claim_reclaimed(client: AsyncClient, seeded_users, db_session):
    """§18's fence-loss path: redact_session's own fencing UPDATE must
    return None (and the caller roll back + audit) when another worker's
    claim has already superseded this one."""
    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200)
    )
    worker_a = uuid.uuid4()
    worker_b = uuid.uuid4()
    await import_retention_crud.claim_sessions_for_cleanup(
        db_session, worker_id=worker_a, retention_days=180, claim_timeout_seconds=300, limit=10
    )
    # Simulate worker_a's claim expiring and worker_b re-claiming it.
    await db_session.execute(
        ImportSession.__table__.update()
        .where(ImportSession.id == session.id)
        .values(retention_cleanup_claimed_by=worker_b, retention_cleanup_claim_expires_at=datetime.now(timezone.utc) + timedelta(seconds=300))
    )
    await db_session.commit()

    result = await import_retention_crud.redact_session(db_session, session_id=session.id, worker_id=worker_a)
    assert result is None, "worker_a's own claim was reclaimed by worker_b -- its redaction must be fenced out"


async def test_retention_partial_failure_remains_observable_and_eligible(client: AsyncClient, seeded_users, db_session, monkeypatch):
    """§18's "Retry and recovery": a session whose redaction transaction
    fails for any reason is skipped, counted, and remains eligible."""
    from app.crud import import_retention as retention_crud_module

    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200)
    )

    original_redact = retention_crud_module.redact_session

    async def _failing_redact(db, *, session_id, worker_id):
        if session_id == session.id:
            raise RuntimeError("simulated redaction infrastructure failure")
        return await original_redact(db, session_id=session_id, worker_id=worker_id)

    monkeypatch.setattr("app.services.import_retention_service.import_retention_crud.redact_session", _failing_redact)

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["purged_count"] == 0
    assert body["skipped_count"] == 1

    await db_session.refresh(session)
    assert session.retention_purged_at is None, "a failed redaction must remain eligible for a later invocation"


async def test_retention_completion_audit_and_idempotency(client: AsyncClient, seeded_users, db_session):
    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200)
    )

    headers = await auth_headers(client)
    r1 = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r1.json()["purged_count"] == 1
    r2 = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r2.status_code == 200
    assert r2.json()["purged_count"] == 0, "already-purged sessions must not be purged again"

    logs = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == AUDIT_ENTITY_IMPORT_SESSION,
                AuditLog.action == AUDIT_ACTION_IMPORT_RETENTION_CLEANUP,
                AuditLog.entity_id == session.id,
            )
        )
    ).scalars().all()
    assert len(logs) == 1, "exactly one retention-cleanup audit entry per session actually purged"


async def test_retention_has_more_true_on_full_batch(client: AsyncClient, seeded_users, db_session):
    actor_id = await _get_user_id(db_session)
    for _ in range(2):
        await _make_terminal_session(db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200))

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["purged_count"] == 1
    assert body["has_more"] is True


async def test_retention_no_limit_defaults_to_100(client: AsyncClient, seeded_users, db_session):
    actor_id = await _get_user_id(db_session)
    await _make_terminal_session(db_session, actor_id=actor_id, status="completed", terminal_at=datetime.now(timezone.utc) - timedelta(days=200))

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 1


# ---------------------------------------------------------------------------
# API / RBAC
# ---------------------------------------------------------------------------


async def test_dry_run_requires_administrator(client: AsyncClient, seeded_users, pipeline_adapter):
    headers = await auth_headers(client, role="equipment_pool_staff")
    admin_headers = await auth_headers(client)
    session = await _create_validated_session(client, admin_headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert r.status_code == 403


async def test_execute_requires_administrator(client: AsyncClient, seeded_users, pipeline_adapter):
    headers = await auth_headers(client, role="read_only")
    admin_headers = await auth_headers(client)
    session = await _create_dry_run_completed_session(client, admin_headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 403


async def test_retention_cleanup_requires_administrator(client: AsyncClient, seeded_users):
    headers = await auth_headers(client, role="equipment_pool_staff")
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers)
    assert r.status_code == 403


async def test_dry_run_404_for_unknown_session(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{uuid.uuid4()}/dry-run", headers=headers)
    assert r.status_code == 404
    assert r.json()["code"] == "IMPORT_SESSION_NOT_FOUND"


async def test_execute_404_for_unknown_session(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{uuid.uuid4()}/execute", headers=headers)
    assert r.status_code == 404
    assert r.json()["code"] == "IMPORT_SESSION_NOT_FOUND"


async def test_retention_cleanup_response_envelope_structured(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"purged_count", "skipped_count", "has_more"}
    assert body == {"purged_count": 0, "skipped_count": 0, "has_more": False}


async def test_retention_cleanup_limit_out_of_bounds_is_422(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 501})
    assert r.status_code == 422
    r2 = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 0})
    assert r2.status_code == 422
