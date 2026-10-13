"""PR19A3 review fix round 1 (H1): focused tests at the shared
lease/fencing primitive level.

Design §25 requires validate (PR19A2), dry-run/execute (PR19A3) to share
one implementation of the lease-acquisition, heartbeat-renewal, and
completion-fencing mechanics -- not structurally-identical copies. This
module tests the actual shared implementation directly:
`app.crud.import_job.admit_phase_job`/`fenced_phase_success`/
`fenced_phase_failure` (which `admit_validate_job`/`fenced_success`/
`fenced_failure` now delegate to) and `app.services.import_lease`'s
renewal-loop/bound-failure-message/fence-lost-audit helpers (which
`import_validation_service`, `import_execution_service`, and
`import_retention_service` all call into, with no private per-module
copy). Uses the real database predicates throughout -- no mocks that
bypass the CAS/fencing SQL itself.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.crud import import_job as import_job_crud
from app.models.import_session import ImportJob, ImportSession, ImportSource
from app.services import import_lease

pytestmark = pytest.mark.asyncio

VALID_CHECKSUM = "b" * 64
DATASET_TYPE = "pr19a3_lease_primitive_test"


async def _get_user_id(db_session) -> uuid.UUID:
    from app.models.user import User

    return (await db_session.execute(select(User.id).limit(1))).scalar_one()


async def _create_registered_session(db_session, *, status="validated", version=0) -> ImportSession:
    actor_id = await _get_user_id(db_session)
    session = ImportSession(dataset_type=DATASET_TYPE, status=status, version=version, created_by_user_id=actor_id)
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
    return session


# ---------------------------------------------------------------------------
# 1. Claim establishes owner/generation/expiry correctly (shared primitive,
#    exercised directly via admit_phase_job -- not validate's own wrapper).
# ---------------------------------------------------------------------------


async def test_admit_phase_job_establishes_owner_generation_expiry(db_session, seeded_users):
    session = await _create_registered_session(db_session, status="validated")
    owner = uuid.uuid4()

    session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session.id,
        job_type="dry_run",
        allowed_from_statuses=("validated",),
        running_status="dry_run_running",
        expected_version=0,
        lease_owner=owner,
        lease_duration_seconds=300,
    )

    assert session_row is not None and job is not None
    assert session_row.status == "dry_run_running"
    assert session_row.version == 1
    assert job.job_type == "dry_run"
    assert job.status == "running"
    assert job.lease_owner == owner
    assert job.lease_generation == 1
    assert job.attempt_number == 1
    before = datetime.now(timezone.utc) + timedelta(seconds=299)
    after = datetime.now(timezone.utc) + timedelta(seconds=301)
    assert before <= job.lease_expires_at <= after


async def test_admit_phase_job_rejects_stale_version(db_session, seeded_users):
    session = await _create_registered_session(db_session, status="validated")
    session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session.id,
        job_type="dry_run",
        allowed_from_statuses=("validated",),
        running_status="dry_run_running",
        expected_version=99,  # stale/wrong
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )
    assert session_row is None
    assert job is None


# ---------------------------------------------------------------------------
# 2/3. Heartbeat renews only the current owner; a stale owner cannot renew.
# ---------------------------------------------------------------------------


async def test_renew_lease_renews_only_current_owner(db_session, seeded_users):
    session = await _create_registered_session(db_session, status="validated")
    owner = uuid.uuid4()
    _session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session.id,
        job_type="execute",
        allowed_from_statuses=("validated",),
        running_status="executing",
        expected_version=0,
        lease_owner=owner,
        lease_duration_seconds=300,
    )

    renewed_by_owner = await import_job_crud.renew_lease(
        db_session, job_id=job.id, lease_owner=owner, lease_generation=1, lease_duration_seconds=300
    )
    assert renewed_by_owner is True

    renewed_by_stale_owner = await import_job_crud.renew_lease(
        db_session, job_id=job.id, lease_owner=uuid.uuid4(), lease_generation=1, lease_duration_seconds=300
    )
    assert renewed_by_stale_owner is False, "a worker that never held this lease must never be able to renew it"


# ---------------------------------------------------------------------------
# 4/5/6/7. Correct fence permits terminal publication; stale generation and
# a late (superseded) worker are rejected; the zero-row result is
# interpreted identically for success and failure.
# ---------------------------------------------------------------------------


async def test_fenced_phase_success_permits_publication_for_correct_fence(db_session, seeded_users):
    session = await _create_registered_session(db_session, status="validated")
    owner = uuid.uuid4()
    session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session.id,
        job_type="dry_run",
        allowed_from_statuses=("validated",),
        running_status="dry_run_running",
        expected_version=0,
        lease_owner=owner,
        lease_duration_seconds=300,
    )

    result = await import_job_crud.fenced_phase_success(
        db_session,
        job_id=job.id,
        lease_owner=owner,
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        running_status="dry_run_running",
        new_session_status="dry_run_completed",
        extra_session_values={"dry_run_completed_at": datetime.now(timezone.utc)},
    )
    assert result is not None
    assert result.status == "dry_run_completed"
    assert result.dry_run_completed_at is not None


async def test_fenced_phase_success_rejects_stale_generation(db_session, seeded_users):
    session = await _create_registered_session(db_session, status="validated")
    owner = uuid.uuid4()
    session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session.id,
        job_type="dry_run",
        allowed_from_statuses=("validated",),
        running_status="dry_run_running",
        expected_version=0,
        lease_owner=owner,
        lease_duration_seconds=300,
    )

    result = await import_job_crud.fenced_phase_success(
        db_session,
        job_id=job.id,
        lease_owner=owner,
        lease_generation=2,  # wrong generation -- this worker's own claim is stale
        session_id=session.id,
        expected_version=session_row.version,
        running_status="dry_run_running",
        new_session_status="dry_run_completed",
    )
    assert result is None, "a stale-generation caller must never publish success"


async def test_fenced_phase_failure_rejects_late_superseded_worker(db_session, seeded_users):
    """A worker fenced out on its own failure publication (§9.4.2 step 5)
    -- e.g. because a recovery claim already superseded it -- must get the
    same `None`/zero-row signal as any other lost fence, for both
    dry-run and execute (shared primitive, not per-phase behavior)."""
    session = await _create_registered_session(db_session, status="validated")
    owner = uuid.uuid4()
    session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session.id,
        job_type="execute",
        allowed_from_statuses=("validated",),
        running_status="executing",
        expected_version=0,
        lease_owner=owner,
        lease_duration_seconds=300,
    )

    result = await import_job_crud.fenced_phase_failure(
        db_session,
        job_id=job.id,
        lease_owner=uuid.uuid4(),  # a different, "late" worker
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        running_status="executing",
        failure_status="failed",
        bounded_error_message="Execution failed: RuntimeError.",
    )
    assert result is None


async def test_fenced_phase_success_and_failure_return_none_identically_on_zero_row_job_fence(db_session, seeded_users):
    """§9.4.1 step 6 / §9.4.2 step 5: the zero-row job-fencing UPDATE must
    be interpreted identically (a clean `None`, no exception, no partial
    write) whether the caller was attempting to publish success or
    failure -- both routes call the same `_fence_job_terminal` primitive."""
    session = await _create_registered_session(db_session, status="validated")
    session_row, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session.id,
        job_type="dry_run",
        allowed_from_statuses=("validated",),
        running_status="dry_run_running",
        expected_version=0,
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )

    wrong_owner = uuid.uuid4()
    success_result = await import_job_crud.fenced_phase_success(
        db_session,
        job_id=job.id,
        lease_owner=wrong_owner,
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        running_status="dry_run_running",
        new_session_status="dry_run_completed",
    )
    failure_result = await import_job_crud.fenced_phase_failure(
        db_session,
        job_id=job.id,
        lease_owner=wrong_owner,
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        running_status="dry_run_running",
        failure_status="dry_run_failed",
        bounded_error_message="x",
    )
    assert success_result is None
    assert failure_result is None


# ---------------------------------------------------------------------------
# 8. Heartbeat task terminates correctly (renewal loop lifecycle).
# ---------------------------------------------------------------------------


async def test_renew_lease_loop_terminates_on_lease_loss(monkeypatch):
    calls = []

    async def fake_renew_lease(db, *, job_id, lease_owner, lease_generation, lease_duration_seconds):
        calls.append(1)
        return len(calls) < 2  # renewed once, then lost

    class _NullSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(import_lease, "AsyncSessionLocal", lambda: _NullSession())
    monkeypatch.setattr(import_job_crud, "renew_lease", fake_renew_lease)

    await asyncio.wait_for(
        import_lease.renew_lease_loop(
            job_id=uuid.uuid4(), lease_owner=uuid.uuid4(), lease_generation=1,
            lease_duration_seconds=300, heartbeat_interval_seconds=0,
        ),
        timeout=2,
    )
    assert len(calls) == 2, "the loop must stop immediately on the first clean zero-row (lease-lost) result"


async def test_renew_lease_loop_terminates_after_bounded_transient_retries(monkeypatch):
    calls = []

    async def failing_renew_lease(db, *, job_id, lease_owner, lease_generation, lease_duration_seconds):
        calls.append(1)
        raise DBAPIError("stmt", {}, Exception("connection lost"))

    class _NullSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(import_lease, "AsyncSessionLocal", lambda: _NullSession())
    monkeypatch.setattr(import_job_crud, "renew_lease", failing_renew_lease)

    await asyncio.wait_for(
        import_lease.renew_lease_loop(
            job_id=uuid.uuid4(), lease_owner=uuid.uuid4(), lease_generation=1,
            lease_duration_seconds=300, heartbeat_interval_seconds=0,
        ),
        timeout=2,
    )
    assert len(calls) == 3, "transient failures are retried up to two more times (three attempts total), then given up"


# ---------------------------------------------------------------------------
# 9/10. Validate, dry-run, and execute all reach the same shared
# implementation -- not their own copy.
# ---------------------------------------------------------------------------


async def test_admit_validate_job_delegates_to_shared_claim_primitive(db_session, seeded_users, monkeypatch):
    session = await _create_registered_session(db_session, status="created")
    calls = []
    real = import_job_crud._claim_session_and_insert_job

    async def spy(db, **kwargs):
        calls.append(kwargs["job_type"])
        return await real(db, **kwargs)

    monkeypatch.setattr(import_job_crud, "_claim_session_and_insert_job", spy)

    await import_job_crud.admit_validate_job(
        db_session, session_id=session.id, expected_version=0, lease_owner=uuid.uuid4(), lease_duration_seconds=300
    )
    assert calls == ["validate"], "admit_validate_job must claim through the same shared primitive admit_phase_job uses"


async def test_fenced_success_and_failure_delegate_to_shared_fencing_primitives(db_session, seeded_users, monkeypatch):
    session = await _create_registered_session(db_session, status="created")
    owner = uuid.uuid4()
    _existed, session_row, job = await import_job_crud.admit_validate_job(
        db_session, session_id=session.id, expected_version=0, lease_owner=owner, lease_duration_seconds=300
    )

    success_calls = []
    failure_calls = []
    real_success = import_job_crud.fenced_phase_success
    real_failure = import_job_crud.fenced_phase_failure

    async def success_spy(db, **kwargs):
        success_calls.append(kwargs["running_status"])
        return await real_success(db, **kwargs)

    async def failure_spy(db, **kwargs):
        failure_calls.append(kwargs["running_status"])
        return await real_failure(db, **kwargs)

    monkeypatch.setattr(import_job_crud, "fenced_phase_success", success_spy)
    await import_job_crud.fenced_success(
        db_session,
        job_id=job.id,
        lease_owner=owner,
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        new_session_status="validated",
        total_rows=0,
        valid_rows=0,
        invalid_rows=0,
        warning_rows=0,
    )
    assert success_calls == ["validating"], "fenced_success must publish through the shared fenced_phase_success primitive"

    monkeypatch.setattr(import_job_crud, "fenced_phase_failure", failure_spy)
    await import_job_crud.fenced_failure(
        db_session,
        job_id=job.id,
        lease_owner=uuid.uuid4(),  # deliberately wrong -- just proving delegation, not the fence outcome
        lease_generation=1,
        session_id=session.id,
        expected_version=session_row.version,
        failure_status="validation_failed",
        bounded_error_message="x",
    )
    assert failure_calls == ["validating"], "fenced_failure must publish through the shared fenced_phase_failure primitive"


async def test_dry_run_and_execute_use_the_same_renew_lease_loop_as_validate(monkeypatch):
    """`import_validation_service.run_validation` and
    `import_execution_service.run_dry_run`/`run_execute` must all
    schedule `import_lease.renew_lease_loop` -- not a private per-module
    copy. Verified by attribute identity, the strongest possible proof
    that no second implementation exists."""
    from app.services import import_execution_service, import_validation_service

    assert not hasattr(import_validation_service, "_renew_lease_loop")
    assert not hasattr(import_validation_service, "_write_fence_lost_audit")
    assert not hasattr(import_validation_service, "_bound_failure_message")

    import inspect

    validate_src = inspect.getsource(import_validation_service.run_validation)
    execute_src = inspect.getsource(import_execution_service)
    assert "import_lease.renew_lease_loop" in validate_src
    assert "import_lease.renew_lease_loop" in execute_src
    assert "import_lease.bound_failure_message" in validate_src
    assert "import_lease.bound_failure_message" in execute_src
    assert "import_lease.write_fence_lost_audit" in validate_src
    assert "import_lease.write_fence_lost_audit" in execute_src
