"""Roadmap PR19A (Legacy Import Foundation) tests.

Deliberately does NOT test any real file format (Excel/CSV) -- no parser
ships in this slice (see app.services.import_foundation's module
docstring). `_StubAdapter` below is an in-memory test double implementing
the `ImportAdapter` contract, used only to exercise the pipeline mechanics
(state machine, structural validation, duplicate detection, business-rule
hook, transaction/rollback safety, audit integration) that every future
real adapter will inherit for free. It is registered into
`app.services.import_foundation.registry` only for the lifetime of each
test via the `stub_adapter` fixture, and unregistered afterward -- the
production registry ships empty (see that module's docstring), and nothing
here changes that.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    ImportAdapterNotImplementedError,
    ImportAdapterNotRegisteredError,
    ImportExecutionFailedError,
    ImportSessionStateError,
    InvalidInputError,
)
from app.models.audit import AuditLog
from app.models.import_session import (
    ImportJob,
    ImportJobStatus,
    ImportJobType,
    ImportRowError,
    ImportSession,
    ImportSessionStatus,
)
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.services import import_foundation as svc
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio

DATASET_TYPE = "test_legacy_dataset"
UNREGISTERED_DATASET_TYPE = "test_dataset_with_no_adapter"


class _StubAdapter(svc.ImportAdapter):
    """Test double proving the pipeline contract -- not a parser for any
    real file format. `parse(None)` (what every API-level call sends,
    since no upload endpoint exists yet) returns an empty batch; direct
    service-layer tests pass a real `list[RawImportRecord]` instead to
    exercise validation."""

    dataset_type = DATASET_TYPE
    required_fields = ("code", "name")
    field_max_lengths = {"name": 20}
    duplicate_key_fields = ("code",)

    def __init__(self):
        self.dry_run_plan: svc.DryRunPlan | None = None
        self.dry_run_error: Exception | None = None
        self.execution_outcome: svc.ExecutionOutcome | None = None
        self.execution_error: Exception | None = None
        self.business_invalid_codes: set[str] = set()

    def parse(self, raw_input):
        if raw_input is None:
            return []
        return raw_input

    async def validate_business_rules(self, db, record):
        if record.fields.get("code") in self.business_invalid_codes:
            return [
                svc.FieldError(
                    record.row_number, "code", "BUSINESS_RULE_FAILED", "This code fails a business rule."
                )
            ]
        return []

    async def plan_dry_run(self, db, session):
        if self.dry_run_error is not None:
            raise self.dry_run_error
        return self.dry_run_plan or svc.DryRunPlan()

    async def execute(self, db, session):
        if self.execution_error is not None:
            raise self.execution_error
        return self.execution_outcome or svc.ExecutionOutcome()


@pytest.fixture
def stub_adapter():
    adapter = _StubAdapter()
    svc.registry.register(adapter)
    try:
        yield adapter
    finally:
        svc.registry.unregister(DATASET_TYPE)


def _record(row_number: int, **fields) -> svc.RawImportRecord:
    return svc.RawImportRecord(row_number=row_number, fields=fields)


async def _create_session(db_session, *, actor, dataset_type: str = DATASET_TYPE, idempotency_key=None) -> ImportSession:
    session, _created = await svc.get_or_create_session(
        db_session,
        dataset_type=dataset_type,
        created_by_user_id=actor.id,
        idempotency_key=idempotency_key,
        source_checksum=None,
        source_filename=None,
        notes=None,
    )
    return session


# ---------------------------------------------------------------------------
# Session lifecycle / state machine
# ---------------------------------------------------------------------------


async def test_create_session_defaults_to_created(db_session, seeded_users, stub_adapter):
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    assert session.status == ImportSessionStatus.CREATED
    assert session.total_rows is None


async def test_get_or_create_session_is_idempotent(db_session, seeded_users, stub_adapter):
    actor = seeded_users[ROLE_ADMINISTRATOR]
    first, created_first = await svc.get_or_create_session(
        db_session,
        dataset_type=DATASET_TYPE,
        created_by_user_id=actor.id,
        idempotency_key="batch-2026-08",
        source_checksum=None,
        source_filename=None,
        notes=None,
    )
    second, created_second = await svc.get_or_create_session(
        db_session,
        dataset_type=DATASET_TYPE,
        created_by_user_id=actor.id,
        idempotency_key="batch-2026-08",
        source_checksum=None,
        source_filename=None,
        notes=None,
    )
    assert created_first is True
    assert created_second is False
    assert first.id == second.id


async def test_idempotency_key_scoped_per_dataset_type(db_session, seeded_users, stub_adapter):
    """Same idempotency_key, different dataset_type -> two distinct
    sessions, never silently merged."""
    actor = seeded_users[ROLE_ADMINISTRATOR]
    first, _ = await svc.get_or_create_session(
        db_session,
        dataset_type=DATASET_TYPE,
        created_by_user_id=actor.id,
        idempotency_key="shared-key",
        source_checksum=None,
        source_filename=None,
        notes=None,
    )
    second, _ = await svc.get_or_create_session(
        db_session,
        dataset_type=UNREGISTERED_DATASET_TYPE,
        created_by_user_id=actor.id,
        idempotency_key="shared-key",
        source_checksum=None,
        source_filename=None,
        notes=None,
    )
    assert first.id != second.id


async def test_validate_fails_fast_when_no_adapter_registered(db_session, seeded_users):
    actor = seeded_users[ROLE_ADMINISTRATOR]
    session = await _create_session(db_session, actor=actor, dataset_type=UNREGISTERED_DATASET_TYPE)
    with pytest.raises(ImportAdapterNotRegisteredError):
        await svc.run_validation(db_session, session, raw_input=None)
    # No state mutation and no job created -- the check happens before any
    # phase transition. Queried directly (not via `session.jobs`) since a
    # bare relationship access here would trigger an async-unsafe lazy load.
    await db_session.refresh(session)
    assert session.status == ImportSessionStatus.CREATED
    jobs = (
        await db_session.execute(select(ImportJob).where(ImportJob.import_session_id == session.id))
    ).scalars().all()
    assert jobs == []


async def test_dry_run_rejected_before_validation(db_session, seeded_users, stub_adapter):
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    with pytest.raises(ImportSessionStateError):
        await svc.run_dry_run(db_session, session)


async def test_execute_rejected_before_dry_run(db_session, seeded_users, stub_adapter):
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    await svc.run_validation(
        db_session, session, raw_input=[_record(2, code="A1", name="Widget")]
    )
    assert session.status == ImportSessionStatus.VALIDATED
    with pytest.raises(ImportSessionStateError):
        await svc.run_execute(db_session, session, actor_user_id=seeded_users[ROLE_ADMINISTRATOR].id)


async def test_full_happy_path_reaches_completed(db_session, seeded_users, stub_adapter):
    actor = seeded_users[ROLE_ADMINISTRATOR]
    session = await _create_session(db_session, actor=actor)

    await svc.run_validation(db_session, session, raw_input=[_record(2, code="A1", name="Widget")])
    assert session.status == ImportSessionStatus.VALIDATED
    assert session.total_rows == 1
    assert session.valid_rows == 1
    assert session.invalid_rows == 0

    stub_adapter.dry_run_plan = svc.DryRunPlan(would_create=1)
    await svc.run_dry_run(db_session, session)
    assert session.status == ImportSessionStatus.DRY_RUN_COMPLETED
    assert session.dry_run_completed_at is not None

    stub_adapter.execution_outcome = svc.ExecutionOutcome(created=1)
    await svc.run_execute(db_session, session, actor_user_id=actor.id)
    assert session.status == ImportSessionStatus.COMPLETED
    assert session.imported_rows == 1
    assert session.executed_at is not None


async def test_cancel_allowed_from_created(db_session, seeded_users, stub_adapter):
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    await svc.cancel_session(db_session, session)
    assert session.status == ImportSessionStatus.CANCELLED


async def test_cancel_rejected_once_executing_or_terminal(db_session, seeded_users, stub_adapter):
    actor = seeded_users[ROLE_ADMINISTRATOR]
    session = await _create_session(db_session, actor=actor)
    await svc.run_validation(db_session, session, raw_input=[_record(2, code="A1", name="Widget")])
    await svc.run_dry_run(db_session, session)
    await svc.run_execute(db_session, session, actor_user_id=actor.id)
    assert session.status == ImportSessionStatus.COMPLETED
    with pytest.raises(ImportSessionStateError):
        await svc.cancel_session(db_session, session)


# ---------------------------------------------------------------------------
# Validation pipeline: structural, duplicate detection, business rules
# ---------------------------------------------------------------------------


async def test_structural_validation_missing_required_field(db_session, seeded_users, stub_adapter):
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    await svc.run_validation(
        db_session, session, raw_input=[_record(2, code="A1"), _record(3, code="A2", name="Widget")]
    )
    assert session.status == ImportSessionStatus.VALIDATION_FAILED
    assert session.invalid_rows == 1
    assert session.valid_rows == 1
    errors = (await db_session.execute(select(ImportRowError).where(ImportRowError.import_session_id == session.id))).scalars().all()
    assert any(e.error_code == "MISSING_REQUIRED_FIELD" and e.row_number == 2 for e in errors)


async def test_structural_validation_field_too_long(db_session, seeded_users, stub_adapter):
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    await svc.run_validation(
        db_session, session, raw_input=[_record(2, code="A1", name="X" * 25)]
    )
    assert session.status == ImportSessionStatus.VALIDATION_FAILED
    errors = (
        (await db_session.execute(select(ImportRowError).where(ImportRowError.import_session_id == session.id)))
        .scalars()
        .all()
    )
    assert any(e.error_code == "FIELD_TOO_LONG" for e in errors)


async def test_duplicate_detection_flags_every_occurrence(db_session, seeded_users, stub_adapter):
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    await svc.run_validation(
        db_session,
        session,
        raw_input=[
            _record(2, code="DUP", name="First"),
            _record(3, code="DUP", name="Second"),
            _record(4, code="UNIQUE", name="Third"),
        ],
    )
    assert session.status == ImportSessionStatus.VALIDATION_FAILED
    assert session.invalid_rows == 2
    assert session.valid_rows == 1
    errors = (
        (await db_session.execute(select(ImportRowError).where(ImportRowError.import_session_id == session.id)))
        .scalars()
        .all()
    )
    duplicate_rows = {e.row_number for e in errors if e.error_code == "DUPLICATE_WITHIN_BATCH"}
    assert duplicate_rows == {2, 3}


async def test_business_rule_hook_invoked(db_session, seeded_users, stub_adapter):
    stub_adapter.business_invalid_codes = {"BAD"}
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    await svc.run_validation(
        db_session,
        session,
        raw_input=[_record(2, code="BAD", name="Widget"), _record(3, code="GOOD", name="Widget")],
    )
    assert session.status == ImportSessionStatus.VALIDATION_FAILED
    assert session.valid_rows == 1
    assert session.invalid_rows == 1
    errors = (
        (await db_session.execute(select(ImportRowError).where(ImportRowError.import_session_id == session.id)))
        .scalars()
        .all()
    )
    assert any(e.error_code == "BUSINESS_RULE_FAILED" and e.row_number == 2 for e in errors)


async def test_deterministic_validation_order_structural_before_business(db_session, seeded_users, stub_adapter):
    """A row failing structural validation (missing field) must never also
    reach the business-rule hook -- structural failures short-circuit
    before business validation runs for that row."""
    stub_adapter.business_invalid_codes = {""}  # would match a blank/missing code if reached
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    await svc.run_validation(db_session, session, raw_input=[_record(2, name="Widget")])
    errors = (
        (await db_session.execute(select(ImportRowError).where(ImportRowError.import_session_id == session.id)))
        .scalars()
        .all()
    )
    # Only the structural failure is recorded -- not also a business-rule
    # failure for the same row.
    assert len(errors) == 1
    assert errors[0].error_code == "MISSING_REQUIRED_FIELD"


async def test_row_count_exceeding_bound_rejected(db_session, seeded_users, stub_adapter, monkeypatch):
    monkeypatch.setattr(svc, "MAX_IMPORT_ROWS", 2)
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    records = [_record(i, code=f"C{i}", name="Widget") for i in range(2, 6)]
    with pytest.raises(InvalidInputError):
        await svc.run_validation(db_session, session, raw_input=records)
    await db_session.refresh(session)
    assert session.status == ImportSessionStatus.VALIDATION_FAILED
    assert session.failure_reason is not None


async def test_revalidation_replaces_previous_error_set(db_session, seeded_users, stub_adapter):
    session = await _create_session(db_session, actor=seeded_users[ROLE_ADMINISTRATOR])
    await svc.run_validation(db_session, session, raw_input=[_record(2, code="A1")])
    assert session.status == ImportSessionStatus.VALIDATION_FAILED

    await svc.run_validation(db_session, session, raw_input=[_record(2, code="A1", name="Widget")])
    assert session.status == ImportSessionStatus.VALIDATED
    assert session.invalid_rows == 0


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


async def test_dry_run_base_adapter_not_implemented_marks_session_failed(db_session, seeded_users, stub_adapter):
    stub_adapter.dry_run_error = ImportAdapterNotImplementedError("no plan for this dataset type yet")
    actor = seeded_users[ROLE_ADMINISTRATOR]
    session = await _create_session(db_session, actor=actor)
    await svc.run_validation(db_session, session, raw_input=[_record(2, code="A1", name="Widget")])

    with pytest.raises(ImportAdapterNotImplementedError):
        await svc.run_dry_run(db_session, session)

    await db_session.refresh(session)
    assert session.status == ImportSessionStatus.DRY_RUN_FAILED
    assert session.failure_reason is not None
    jobs = (
        (await db_session.execute(select(ImportJob).where(ImportJob.import_session_id == session.id, ImportJob.job_type == ImportJobType.DRY_RUN)))
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].status == ImportJobStatus.FAILED


async def test_dry_run_can_be_retried_after_failure(db_session, seeded_users, stub_adapter):
    actor = seeded_users[ROLE_ADMINISTRATOR]
    session = await _create_session(db_session, actor=actor)
    await svc.run_validation(db_session, session, raw_input=[_record(2, code="A1", name="Widget")])

    stub_adapter.dry_run_error = RuntimeError("transient failure")
    with pytest.raises(RuntimeError):
        await svc.run_dry_run(db_session, session)
    await db_session.refresh(session)
    assert session.status == ImportSessionStatus.DRY_RUN_FAILED

    stub_adapter.dry_run_error = None
    stub_adapter.dry_run_plan = svc.DryRunPlan(would_create=1)
    await svc.run_dry_run(db_session, session)
    assert session.status == ImportSessionStatus.DRY_RUN_COMPLETED


# ---------------------------------------------------------------------------
# Execute: transaction safety / rollback
# ---------------------------------------------------------------------------


async def test_execute_success_writes_exactly_one_audit_row(db_session, seeded_users, stub_adapter):
    actor = seeded_users[ROLE_ADMINISTRATOR]
    session = await _create_session(db_session, actor=actor)
    await svc.run_validation(db_session, session, raw_input=[_record(2, code="A1", name="Widget")])
    await svc.run_dry_run(db_session, session)

    stub_adapter.execution_outcome = svc.ExecutionOutcome(created=1)
    await svc.run_execute(db_session, session, actor_user_id=actor.id)

    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.entity_id == session.id))).scalars().all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].action == "import"
    assert audit_rows[0].entity_type == "import_session"


async def test_execute_failure_rolls_back_and_marks_session_failed(db_session, seeded_users, stub_adapter):
    actor = seeded_users[ROLE_ADMINISTRATOR]
    session = await _create_session(db_session, actor=actor)
    await svc.run_validation(db_session, session, raw_input=[_record(2, code="A1", name="Widget")])
    await svc.run_dry_run(db_session, session)

    stub_adapter.execution_error = RuntimeError("simulated adapter crash mid-write")
    with pytest.raises(ImportExecutionFailedError):
        await svc.run_execute(db_session, session, actor_user_id=actor.id)

    await db_session.refresh(session)
    assert session.status == ImportSessionStatus.FAILED
    assert session.imported_rows is None  # never set -- the failed work() never reached that line
    assert session.executed_at is None

    # No partial audit trail: the audit event is written inside the same
    # work() that raised, so it must never have been committed.
    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.entity_id == session.id))).scalars().all()
    )
    assert audit_rows == []

    execute_jobs = (
        (
            await db_session.execute(
                select(ImportJob).where(
                    ImportJob.import_session_id == session.id, ImportJob.job_type == ImportJobType.EXECUTE
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(execute_jobs) == 1
    assert execute_jobs[0].status == ImportJobStatus.FAILED


async def test_execute_adapter_not_implemented_is_not_wrapped(db_session, seeded_users, stub_adapter):
    """ImportAdapterNotImplementedError is a safe, expected message and
    must reach the caller unwrapped -- only genuinely unexpected adapter
    exceptions are translated to the generic ImportExecutionFailedError."""
    actor = seeded_users[ROLE_ADMINISTRATOR]
    session = await _create_session(db_session, actor=actor)
    await svc.run_validation(db_session, session, raw_input=[_record(2, code="A1", name="Widget")])
    await svc.run_dry_run(db_session, session)

    stub_adapter.execution_error = ImportAdapterNotImplementedError("no execute for this dataset type")
    with pytest.raises(ImportAdapterNotImplementedError):
        await svc.run_execute(db_session, session, actor_user_id=actor.id)


# ---------------------------------------------------------------------------
# API contract: permissions, not-found, and the full HTTP round trip
# ---------------------------------------------------------------------------


async def test_create_session_requires_administrator(client, seeded_users, stub_adapter):
    for role in (ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        resp = await client.post("/api/v1/import-sessions", headers=headers, json={"dataset_type": DATASET_TYPE})
        assert resp.status_code == 403, resp.text


async def test_create_session_unauthenticated_401(client):
    resp = await client.post("/api/v1/import-sessions", json={"dataset_type": DATASET_TYPE})
    assert resp.status_code == 401


async def test_session_not_found_404(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    random_id = uuid.uuid4()
    for path, method in [
        (f"/api/v1/import-sessions/{random_id}", "get"),
        (f"/api/v1/import-sessions/{random_id}/status", "get"),
        (f"/api/v1/import-sessions/{random_id}/errors", "get"),
        (f"/api/v1/import-sessions/{random_id}/validate", "post"),
        (f"/api/v1/import-sessions/{random_id}/dry-run", "post"),
        (f"/api/v1/import-sessions/{random_id}/execute", "post"),
        (f"/api/v1/import-sessions/{random_id}/cancel", "post"),
    ]:
        resp = await getattr(client, method)(path, headers=headers)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}: {resp.text}"
        assert resp.json()["code"] == "IMPORT_SESSION_NOT_FOUND"


async def test_full_http_round_trip(client, seeded_users, stub_adapter):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)

    create_resp = await client.post(
        "/api/v1/import-sessions", headers=headers, json={"dataset_type": DATASET_TYPE}
    )
    assert create_resp.status_code == 200, create_resp.text
    session_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "created"

    # No real adapter can be reached via HTTP in this slice (validate takes
    # no body), so the stub's parse(None) yields an empty, trivially valid
    # batch -- proving the endpoint/state-machine wiring without a real file.
    validate_resp = await client.post(f"/api/v1/import-sessions/{session_id}/validate", headers=headers)
    assert validate_resp.status_code == 200, validate_resp.text
    assert validate_resp.json()["status"] == "validated"
    assert validate_resp.json()["total_rows"] == 0

    status_resp = await client.get(f"/api/v1/import-sessions/{session_id}/status", headers=headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "validated"

    dry_run_resp = await client.post(f"/api/v1/import-sessions/{session_id}/dry-run", headers=headers)
    assert dry_run_resp.status_code == 200, dry_run_resp.text
    assert dry_run_resp.json()["status"] == "dry_run_completed"

    execute_resp = await client.post(f"/api/v1/import-sessions/{session_id}/execute", headers=headers)
    assert execute_resp.status_code == 200, execute_resp.text
    assert execute_resp.json()["status"] == "completed"

    summary_resp = await client.get(f"/api/v1/import-sessions/{session_id}", headers=headers)
    assert summary_resp.status_code == 200
    body = summary_resp.json()
    assert body["session"]["status"] == "completed"
    assert len(body["jobs"]) == 3
    assert {j["job_type"] for j in body["jobs"]} == {"validate", "dry_run", "execute"}

    list_resp = await client.get(f"/api/v1/import-sessions?dataset_type={DATASET_TYPE}", headers=headers)
    assert list_resp.status_code == 200
    assert any(item["id"] == session_id for item in list_resp.json()["items"])


async def test_http_validate_with_unregistered_dataset_type_returns_422(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/import-sessions", headers=headers, json={"dataset_type": UNREGISTERED_DATASET_TYPE}
    )
    session_id = create_resp.json()["id"]
    resp = await client.post(f"/api/v1/import-sessions/{session_id}/validate", headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "IMPORT_ADAPTER_NOT_REGISTERED"


async def test_http_dry_run_before_validate_returns_409(client, seeded_users, stub_adapter):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/import-sessions", headers=headers, json={"dataset_type": DATASET_TYPE}
    )
    session_id = create_resp.json()["id"]
    resp = await client.post(f"/api/v1/import-sessions/{session_id}/dry-run", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "IMPORT_SESSION_INVALID_STATE"


async def test_http_cancel_session(client, seeded_users, stub_adapter):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/import-sessions", headers=headers, json={"dataset_type": DATASET_TYPE}
    )
    session_id = create_resp.json()["id"]
    resp = await client.post(f"/api/v1/import-sessions/{session_id}/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_http_errors_endpoint_empty_for_unvalidated_session(client, seeded_users, stub_adapter):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/import-sessions", headers=headers, json={"dataset_type": DATASET_TYPE}
    )
    session_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/import-sessions/{session_id}/errors", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


async def test_errors_endpoint_lists_and_paginates_real_errors(db_session, client, seeded_users, stub_adapter):
    """Drives validation through the service layer directly (the HTTP
    validate endpoint always sends raw_input=None, since no parser exists
    yet) with real in-memory records, then confirms the HTTP errors
    endpoint paginates the resulting rows in row-number order."""
    actor = seeded_users[ROLE_ADMINISTRATOR]
    session = await _create_session(db_session, actor=actor)
    await svc.run_validation(
        db_session,
        session,
        raw_input=[_record(2, code="A1"), _record(3, code="A2"), _record(4, code="A3")],
    )
    assert session.invalid_rows == 3
    await db_session.commit()

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    first_page = await client.get(
        f"/api/v1/import-sessions/{session.id}/errors?limit=2", headers=headers
    )
    assert first_page.status_code == 200
    body = first_page.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["items"][0]["row_number"] == 2
    assert body["items"][1]["row_number"] == 3
    assert body["next_cursor"] is not None

    second_page = await client.get(
        f"/api/v1/import-sessions/{session.id}/errors?limit=2&cursor={body['next_cursor']}",
        headers=headers,
    )
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 1
    assert second_body["items"][0]["row_number"] == 4
    assert second_body["next_cursor"] is None
