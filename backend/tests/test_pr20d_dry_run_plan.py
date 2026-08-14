"""Roadmap PR20D (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §14,
§14.2-§14.9, §15.1). Covers: `plan_dry_run` row classification (CREATE/
UPDATE/SKIP, OD-4 CREATE gate, summary invariants), `persist_dry_run_plan`
persistence/immutability/supersession, the UPDATE-row concurrency-token
capture discipline, read-only-domain enforcement (no Equipment mutation),
the `GET .../dry-run-plan` / `POST .../dry-run-plan/{id}/confirm` API
surface (RBAC, pagination, staleness), retention redaction of plan-row
content, and audit-event emission. Does not re-test PR19A's own lease/
fencing/recovery mechanics (see test_import_execution.py) or PR20C's own
parse/validate contract (see test_import_adapter_equipment_master.py) --
both are reused unchanged here."""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit import AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED, AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CREATED
from app.crud import import_dry_run_plan as import_dry_run_plan_crud
from app.crud import import_retention as import_retention_crud
from app.models.audit import AuditLog
from app.models.equipment import Equipment, EquipmentStatus
from app.models.import_session import (
    EquipmentMasterDryRunPlan,
    EquipmentMasterDryRunPlanRow,
    ImportJob,
    ImportSession,
)
from app.services import import_execution_service, import_lease
from app.services.import_adapter_context import AdapterInvocationContext, adapter_invocation_context
from app.services.import_adapters.equipment_master import (
    CODE_ASSET_NUMBER_REQUIRED_FOR_CREATE,
    CODE_BCM_MISSING,
    CODE_IDENTITY_CONFLICT,
    DATASET_TYPE,
    EquipmentMasterAdapter,
)
from app.services.import_source_reader import SourceDescriptor, VerifiedSourceContent
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

_HEADERS_ORDER = ["ID CODE", "Item No.", "ชื่อไทย", "สถานะเครื่องมือ"]


@pytest_asyncio.fixture(autouse=True)
async def _patch_execution_session_factories(db_engine, monkeypatch):
    """Mirrors test_import_execution.py's identical fixture -- both
    modules that open their own `AsyncSessionLocal()` must be repointed
    at this test's own engine."""
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(import_execution_service, "AsyncSessionLocal", session_maker)
    monkeypatch.setattr(import_lease, "AsyncSessionLocal", session_maker)


def _build_workbook_bytes(rows: list[dict[str, object]]) -> bytes:
    import io

    import openpyxl

    from app.services.import_adapters.equipment_master import WORKSHEET_NAME, _GOVERNED_HEADERS

    headers = list(_GOVERNED_HEADERS)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = WORKSHEET_NAME
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _valid_row(**overrides: object) -> dict[str, object]:
    row = {
        "ID CODE": overrides.pop("bcm", "BCM_PR20D_1"),
        "Item No.": overrides.pop("item_no", "ITEM_PR20D_1"),
        "ชื่อไทย": overrides.pop("equipment_name", "เครื่องมือทดสอบ PR20D"),
        "สถานะเครื่องมือ": overrides.pop("status", "active"),
    }
    row.update(overrides)
    return row


async def _seed_equipment(db_session, **kwargs) -> Equipment:
    defaults = dict(
        asset_number=f"AN-{uuid.uuid4().hex[:10]}",
        equipment_name="Existing Equipment",
        status=EquipmentStatus.AVAILABLE_AT_POOL,
    )
    defaults.update(kwargs)
    eq = Equipment(**defaults)
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    return eq


async def _create_session(client: AsyncClient, headers: dict) -> dict:
    r = await client.post("/api/v1/import-sessions", headers=headers, json={"dataset_type": DATASET_TYPE})
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _upload(client: AsyncClient, headers: dict, session_id: str, content: bytes):
    files = {"file": ("equipment_master.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    return await client.post(f"/api/v1/import-sessions/{session_id}/source/upload", headers=headers, files=files)


async def _validated_session_with_update_rows(client, headers, db_session, rows: list[dict]) -> dict:
    session = await _create_session(client, headers)
    content = _build_workbook_bytes(rows)
    up = await _upload(client, headers, session["id"], content)
    assert up.status_code == 201, up.text
    v = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert v.status_code == 200, v.text
    assert v.json()["status"] == "validated", v.json()
    return session


# ---------------------------------------------------------------------------
# §14/§15.1: plan_dry_run row classification, direct adapter invocation.
# ---------------------------------------------------------------------------


def _verified_content(content: bytes, *, source_id: uuid.UUID, session_id: uuid.UUID) -> VerifiedSourceContent:
    return VerifiedSourceContent(
        content=content,
        source_descriptor=SourceDescriptor(
            import_source_id=source_id,
            import_session_id=session_id,
            dataset_type=DATASET_TYPE,
            expected_checksum="c" * 64,
            expected_byte_size=len(content),
            content_type=None,
            original_filename=None,
            registration_status="frozen",
        ),
    )


def _invocation_context(*, session_id, source_id, checksum, dry_run_job_id, accepted_job_id, content: bytes) -> AdapterInvocationContext:
    return AdapterInvocationContext(
        import_session_id=session_id,
        import_source_id=source_id,
        dataset_type=DATASET_TYPE,
        source_checksum=checksum,
        source_fingerprint="fp",
        ruleset_version="1",
        verified_source_content=_verified_content(content, source_id=source_id, session_id=session_id),
        dry_run_job_id=dry_run_job_id,
        accepted_validation_job_id=accepted_job_id,
        actor_user_id=None,
    )


async def test_plan_dry_run_update_candidate_captures_expected_equipment_version(db_session, seeded_users):
    existing = await _seed_equipment(
        db_session, bcm_code="BCM_CAP1", item_no="ITEM_CAP1", equipment_name="Old Name"
    )
    original_version = existing.version

    content = _build_workbook_bytes([_valid_row(bcm="BCM_CAP1", item_no="ITEM_CAP1", equipment_name="New Name")])
    adapter = EquipmentMasterAdapter()
    ctx = _invocation_context(
        session_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        checksum="c" * 64,
        dry_run_job_id=uuid.uuid4(),
        accepted_job_id=uuid.uuid4(),
        content=content,
    )
    with adapter_invocation_context(ctx):
        plan = await adapter.plan_dry_run(db_session)

    rows = plan.summary["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "UPDATE"
    assert row["target_equipment_id"] == existing.id
    assert row["expected_equipment_version"] == original_version
    assert row["normalized_values"]["equipment_name"] == "New Name"
    assert plan.summary["creates"] == 0
    assert plan.summary["updates"] == 1
    assert plan.summary["skips"] == 0

    # Read-only: plan_dry_run must never mutate Equipment.
    await db_session.refresh(existing)
    assert existing.equipment_name == "Old Name"
    assert existing.version == original_version


async def test_plan_dry_run_blocking_finding_produces_skip_with_reason(db_session, seeded_users):
    content = _build_workbook_bytes([_valid_row(bcm=None)])
    adapter = EquipmentMasterAdapter()
    ctx = _invocation_context(
        session_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        checksum="c" * 64,
        dry_run_job_id=uuid.uuid4(),
        accepted_job_id=uuid.uuid4(),
        content=content,
    )
    with adapter_invocation_context(ctx):
        plan = await adapter.plan_dry_run(db_session)

    rows = plan.summary["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "SKIP"
    assert row["target_equipment_id"] is None
    assert row["expected_equipment_version"] is None
    assert row["normalized_values"] == {}
    codes = {w["error_code"] for w in row["warnings"]}
    assert CODE_BCM_MISSING in codes
    assert plan.summary["skips"] == 1
    assert plan.summary["updates"] == 0
    assert plan.summary["creates"] == 0


async def test_plan_dry_run_create_candidate_always_blocked_by_od4(db_session, seeded_users):
    """§9 OD-4: a CREATE candidate is never plan-ed as executable under
    the current source contract -- always SKIP, never a CREATE row with a
    fabricated asset_number."""
    content = _build_workbook_bytes([_valid_row(bcm="BCM_NEVER_CREATE", item_no="ITEM_NEVER_CREATE")])
    adapter = EquipmentMasterAdapter()
    ctx = _invocation_context(
        session_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        checksum="c" * 64,
        dry_run_job_id=uuid.uuid4(),
        accepted_job_id=uuid.uuid4(),
        content=content,
    )
    with adapter_invocation_context(ctx):
        plan = await adapter.plan_dry_run(db_session)

    row = plan.summary["rows"][0]
    assert row["action"] == "SKIP"
    codes = {w["error_code"] for w in row["warnings"]}
    assert CODE_ASSET_NUMBER_REQUIRED_FOR_CREATE in codes
    assert plan.summary["creates"] == 0
    assert plan.summary["skips"] == 1


async def test_plan_dry_run_identity_conflict_counted_as_blocking_conflict(db_session, seeded_users):
    await _seed_equipment(db_session, bcm_code="BCM_CONFLICT_A", item_no="ITEM_CONFLICT_A")
    content = _build_workbook_bytes([_valid_row(bcm="BCM_CONFLICT_A", item_no="ITEM_CONFLICT_DIFFERENT")])
    adapter = EquipmentMasterAdapter()
    ctx = _invocation_context(
        session_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        checksum="c" * 64,
        dry_run_job_id=uuid.uuid4(),
        accepted_job_id=uuid.uuid4(),
        content=content,
    )
    with adapter_invocation_context(ctx):
        plan = await adapter.plan_dry_run(db_session)

    row = plan.summary["rows"][0]
    assert row["action"] == "SKIP"
    codes = {w["error_code"] for w in row["warnings"]}
    assert CODE_IDENTITY_CONFLICT in codes
    assert plan.summary["blocking_conflicts"] == 1


async def test_plan_dry_run_summary_matches_row_counts_exactly(db_session, seeded_users):
    await _seed_equipment(db_session, bcm_code="BCM_SUM_UPD", item_no="ITEM_SUM_UPD")
    content = _build_workbook_bytes(
        [
            _valid_row(bcm="BCM_SUM_UPD", item_no="ITEM_SUM_UPD"),  # UPDATE
            _valid_row(bcm=None, item_no="ITEM_SUM_SKIP"),  # SKIP (blocking)
            _valid_row(bcm="BCM_SUM_CREATE", item_no="ITEM_SUM_CREATE"),  # SKIP (OD-4)
        ]
    )
    adapter = EquipmentMasterAdapter()
    ctx = _invocation_context(
        session_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        checksum="c" * 64,
        dry_run_job_id=uuid.uuid4(),
        accepted_job_id=uuid.uuid4(),
        content=content,
    )
    with adapter_invocation_context(ctx):
        plan = await adapter.plan_dry_run(db_session)

    rows = plan.summary["rows"]
    assert plan.summary["total_rows"] == len(rows) == 3
    assert plan.summary["creates"] == sum(1 for r in rows if r["action"] == "CREATE")
    assert plan.summary["updates"] == sum(1 for r in rows if r["action"] == "UPDATE")
    assert plan.summary["skips"] == sum(1 for r in rows if r["action"] == "SKIP")
    assert plan.summary["creates"] == 0
    assert plan.summary["updates"] == 1
    assert plan.summary["skips"] == 2


# ---------------------------------------------------------------------------
# §14.2/§14.3: persisted plan via the real dry-run HTTP endpoint --
# persistence, identity binding, immutability, supersession, no Equipment
# mutation, audit.
# ---------------------------------------------------------------------------


async def test_e2e_dry_run_persists_immutable_plan_bound_to_identity(client: AsyncClient, seeded_users, db_session):
    existing = await _seed_equipment(
        db_session, bcm_code="BCM_E2E_PLAN", item_no="ITEM_E2E_PLAN", equipment_name="Old Name"
    )
    original_version = existing.version

    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_E2E_PLAN", item_no="ITEM_E2E_PLAN", equipment_name="New Name")]
    )

    dr = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert dr.status_code == 200, dr.text
    assert dr.json()["status"] == "dry_run_completed"

    session_uuid = uuid.UUID(session["id"])
    plan_row = (
        await db_session.execute(
            select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_uuid)
        )
    ).scalar_one()
    assert plan_row.status == "active"
    assert plan_row.confirmed_at is None
    assert plan_row.confirmed_by_user_id is None
    assert plan_row.summary_updates == 1
    assert plan_row.summary_creates == 0

    # §14.1 five-identity chain: bound to session, source, checksum, the
    # accepted validation job, and this exact dry-run job -- never
    # "latest".
    session_db = (await db_session.execute(select(ImportSession).where(ImportSession.id == session_uuid))).scalar_one()
    assert plan_row.import_source_id is not None
    assert plan_row.accepted_validation_job_id == session_db.current_validation_job_id
    dry_run_job = (
        await db_session.execute(
            select(ImportJob).where(ImportJob.import_session_id == session_uuid, ImportJob.job_type == "dry_run")
        )
    ).scalar_one()
    assert plan_row.dry_run_job_id == dry_run_job.id

    plan_rows = (
        (
            await db_session.execute(
                select(EquipmentMasterDryRunPlanRow).where(EquipmentMasterDryRunPlanRow.dry_run_plan_id == plan_row.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(plan_rows) == 1
    assert plan_rows[0].action == "UPDATE"
    assert plan_rows[0].target_equipment_id == existing.id
    assert plan_rows[0].expected_equipment_version == original_version

    # §17/§18: dry-run must never mutate Equipment.
    await db_session.refresh(existing)
    assert existing.equipment_name == "Old Name"
    assert existing.version == original_version

    # §26: audit event recorded.
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CREATED, AuditLog.entity_id == session_uuid
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].after_data["dry_run_plan_id"] == str(plan_row.id)


async def test_e2e_expected_version_never_refreshed_after_concurrent_mutation(
    client: AsyncClient, seeded_users, db_session
):
    """§15.1: the concurrency token is captured once, at dry-run time, and
    never re-read -- a mutation after the dry-run must not change what a
    second dry-run's *first* plan already captured."""
    existing = await _seed_equipment(db_session, bcm_code="BCM_TOKEN", item_no="ITEM_TOKEN")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_TOKEN", item_no="ITEM_TOKEN")]
    )
    dr = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert dr.status_code == 200, dr.text

    session_uuid = uuid.UUID(session["id"])
    first_plan = (
        await db_session.execute(
            select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_uuid)
        )
    ).scalar_one()
    first_row = (
        await db_session.execute(
            select(EquipmentMasterDryRunPlanRow).where(EquipmentMasterDryRunPlanRow.dry_run_plan_id == first_plan.id)
        )
    ).scalar_one()
    captured_token = first_row.expected_equipment_version

    # Simulate another actor mutating Equipment.version after the plan
    # was captured.
    existing.version += 1
    await db_session.commit()

    # The already-persisted row's token must remain exactly what was
    # captured at dry-run time -- never refreshed by anything after.
    await db_session.refresh(first_row)
    assert first_row.expected_equipment_version == captured_token
    assert first_row.expected_equipment_version != existing.version


async def test_e2e_second_dry_run_supersedes_first_plan_atomically(client: AsyncClient, seeded_users, db_session):
    await _seed_equipment(db_session, bcm_code="BCM_SUPERSEDE", item_no="ITEM_SUPERSEDE")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_SUPERSEDE", item_no="ITEM_SUPERSEDE")]
    )
    dr1 = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert dr1.status_code == 200, dr1.text

    session_uuid = uuid.UUID(session["id"])
    first_plan = (
        await db_session.execute(
            select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_uuid)
        )
    ).scalar_one()
    first_plan_id = first_plan.id
    first_row_ids = {
        r.id
        for r in (
            await db_session.execute(
                select(EquipmentMasterDryRunPlanRow).where(EquipmentMasterDryRunPlanRow.dry_run_plan_id == first_plan_id)
            )
        )
        .scalars()
        .all()
    }

    # A second dry-run attempt is allowed from dry_run_completed.
    dr2 = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert dr2.status_code == 200, dr2.text

    # The HTTP call above wrote through a different AsyncSession -- this
    # fixture's own identity-mapped objects (e.g. `first_plan`) are not
    # automatically refreshed by a later SELECT unless expired first.
    db_session.expire_all()

    all_plans = (
        (await db_session.execute(select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_uuid)))
        .scalars()
        .all()
    )
    assert len(all_plans) == 2
    statuses = {p.id: p.status for p in all_plans}
    assert statuses[first_plan_id] == "superseded"
    active_plans = [p for p in all_plans if p.status == "active"]
    assert len(active_plans) == 1
    second_plan = active_plans[0]
    assert second_plan.id != first_plan_id

    # §10: the first plan's rows are never mutated/deleted by supersession.
    await db_session.refresh((await db_session.execute(select(EquipmentMasterDryRunPlanRow).where(EquipmentMasterDryRunPlanRow.id.in_(first_row_ids)))).scalars().first())
    still_present = (
        (await db_session.execute(select(EquipmentMasterDryRunPlanRow).where(EquipmentMasterDryRunPlanRow.dry_run_plan_id == first_plan_id)))
        .scalars()
        .all()
    )
    assert {r.id for r in still_present} == first_row_ids

    # Only one active plan per session (partial-unique-index invariant,
    # exercised at the ORM level here; the migration test proves the DB
    # constraint itself on PostgreSQL).
    current = await import_dry_run_plan_crud.get_current_plan(db_session, import_session_id=session_uuid)
    assert current.id == second_plan.id


# ---------------------------------------------------------------------------
# §14.4a/§14.6/§21/§31: GET .../dry-run-plan and POST .../confirm API surface.
# ---------------------------------------------------------------------------


async def test_api_get_dry_run_plan_returns_summary_and_rows(client: AsyncClient, seeded_users, db_session):
    await _seed_equipment(db_session, bcm_code="BCM_API_GET", item_no="ITEM_API_GET")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_API_GET", item_no="ITEM_API_GET")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)

    r = await client.get(f"/api/v1/import-sessions/{session['id']}/dry-run-plan", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_current"] is True
    assert body["status"] == "active"
    assert body["summary"]["updates"] == 1
    assert body["rows_total"] == 1
    assert len(body["rows"]) == 1
    assert body["rows"][0]["action"] == "UPDATE"


async def test_api_get_dry_run_plan_404_when_never_dry_run(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = await _create_session(client, headers)
    r = await client.get(f"/api/v1/import-sessions/{session['id']}/dry-run-plan", headers=headers)
    assert r.status_code == 404
    assert r.json()["code"] == "IMPORT_DRY_RUN_PLAN_NOT_FOUND"


async def test_api_get_dry_run_plan_rows_paginated(client: AsyncClient, seeded_users, db_session):
    rows = []
    for i in range(5):
        eq = await _seed_equipment(db_session, bcm_code=f"BCM_PAGE_{i}", item_no=f"ITEM_PAGE_{i}")
        rows.append(_valid_row(bcm=f"BCM_PAGE_{i}", item_no=f"ITEM_PAGE_{i}"))
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(client, headers, db_session, rows)
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)

    r1 = await client.get(f"/api/v1/import-sessions/{session['id']}/dry-run-plan?limit=2", headers=headers)
    assert r1.status_code == 200
    body1 = r1.json()
    assert len(body1["rows"]) == 2
    assert body1["rows_total"] == 5
    assert body1["rows_next_cursor"] is not None

    r2 = await client.get(
        f"/api/v1/import-sessions/{session['id']}/dry-run-plan?limit=2&cursor={body1['rows_next_cursor']}",
        headers=headers,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert len(body2["rows"]) == 2
    first_page_numbers = {row["source_row_number"] for row in body1["rows"]}
    second_page_numbers = {row["source_row_number"] for row in body2["rows"]}
    assert first_page_numbers.isdisjoint(second_page_numbers)


async def test_api_get_dry_run_plan_malformed_cursor_returns_400(client: AsyncClient, seeded_users, db_session):
    await _seed_equipment(db_session, bcm_code="BCM_BADCURSOR", item_no="ITEM_BADCURSOR")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_BADCURSOR", item_no="ITEM_BADCURSOR")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)

    r = await client.get(
        f"/api/v1/import-sessions/{session['id']}/dry-run-plan?cursor=not-valid-base64!!", headers=headers
    )
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_INPUT"


async def test_api_confirm_dry_run_plan_success(client: AsyncClient, seeded_users, db_session):
    await _seed_equipment(db_session, bcm_code="BCM_CONFIRM", item_no="ITEM_CONFIRM")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_CONFIRM", item_no="ITEM_CONFIRM")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    plan = (await client.get(f"/api/v1/import-sessions/{session['id']}/dry-run-plan", headers=headers)).json()

    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/dry-run-plan/{plan['id']}/confirm", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["confirmed_at"] is not None
    assert body["confirmed_by_user_id"] is not None

    session_uuid = uuid.UUID(session["id"])
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED, AuditLog.entity_id == session_uuid
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1


async def test_api_confirm_dry_run_plan_idempotent_same_confirmer_preserved(
    client: AsyncClient, seeded_users, db_session
):
    await _seed_equipment(db_session, bcm_code="BCM_CONFIRM_IDEM", item_no="ITEM_CONFIRM_IDEM")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_CONFIRM_IDEM", item_no="ITEM_CONFIRM_IDEM")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    plan = (await client.get(f"/api/v1/import-sessions/{session['id']}/dry-run-plan", headers=headers)).json()

    r1 = await client.post(
        f"/api/v1/import-sessions/{session['id']}/dry-run-plan/{plan['id']}/confirm", headers=headers
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/v1/import-sessions/{session['id']}/dry-run-plan/{plan['id']}/confirm", headers=headers
    )
    assert r2.status_code == 200
    assert r1.json()["confirmed_at"] == r2.json()["confirmed_at"]
    assert r1.json()["confirmed_by_user_id"] == r2.json()["confirmed_by_user_id"]


async def test_api_confirm_dry_run_plan_wrong_plan_id_returns_404(client: AsyncClient, seeded_users, db_session):
    await _seed_equipment(db_session, bcm_code="BCM_WRONGID", item_no="ITEM_WRONGID")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_WRONGID", item_no="ITEM_WRONGID")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)

    bogus_plan_id = uuid.uuid4()
    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/dry-run-plan/{bogus_plan_id}/confirm", headers=headers
    )
    assert r.status_code == 404
    assert r.json()["code"] == "IMPORT_DRY_RUN_PLAN_NOT_FOUND"


async def test_api_confirm_dry_run_plan_superseded_plan_returns_409_stale(
    client: AsyncClient, seeded_users, db_session
):
    await _seed_equipment(db_session, bcm_code="BCM_STALE", item_no="ITEM_STALE")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_STALE", item_no="ITEM_STALE")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    stale_plan = (await client.get(f"/api/v1/import-sessions/{session['id']}/dry-run-plan", headers=headers)).json()

    # A second dry-run supersedes the first plan.
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)

    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/dry-run-plan/{stale_plan['id']}/confirm", headers=headers
    )
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_DRY_RUN_PLAN_STALE"


async def test_api_confirm_dry_run_plan_cancelled_session_returns_409_stale(
    client: AsyncClient, seeded_users, db_session
):
    await _seed_equipment(db_session, bcm_code="BCM_CANCELLED", item_no="ITEM_CANCELLED")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_CANCELLED", item_no="ITEM_CANCELLED")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    plan = (await client.get(f"/api/v1/import-sessions/{session['id']}/dry-run-plan", headers=headers)).json()

    cancel = await client.post(f"/api/v1/import-sessions/{session['id']}/cancel", headers=headers)
    assert cancel.status_code == 200, cancel.text

    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/dry-run-plan/{plan['id']}/confirm", headers=headers
    )
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_DRY_RUN_PLAN_STALE"


async def test_api_dry_run_plan_endpoints_require_administrator(client: AsyncClient, seeded_users, db_session):
    await _seed_equipment(db_session, bcm_code="BCM_RBAC", item_no="ITEM_RBAC")
    admin_headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, admin_headers, db_session, [_valid_row(bcm="BCM_RBAC", item_no="ITEM_RBAC")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=admin_headers)
    plan = (await client.get(f"/api/v1/import-sessions/{session['id']}/dry-run-plan", headers=admin_headers)).json()

    from app.models.user import ROLE_READ_ONLY

    operator_headers = await auth_headers(client, role=ROLE_READ_ONLY)
    r_get = await client.get(f"/api/v1/import-sessions/{session['id']}/dry-run-plan", headers=operator_headers)
    assert r_get.status_code == 403
    r_confirm = await client.post(
        f"/api/v1/import-sessions/{session['id']}/dry-run-plan/{plan['id']}/confirm", headers=operator_headers
    )
    assert r_confirm.status_code == 403


# ---------------------------------------------------------------------------
# §14.9/§6.6: retention redaction of plan-row content columns.
# ---------------------------------------------------------------------------


async def test_retention_redacts_plan_row_content_but_preserves_structural_fields(
    client: AsyncClient, seeded_users, db_session
):
    existing = await _seed_equipment(db_session, bcm_code="BCM_RETAIN", item_no="ITEM_RETAIN")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_RETAIN", item_no="ITEM_RETAIN")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)

    session_uuid = uuid.UUID(session["id"])
    plan_row = (
        await db_session.execute(
            select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_uuid)
        )
    ).scalar_one()
    before = (
        await db_session.execute(
            select(EquipmentMasterDryRunPlanRow).where(EquipmentMasterDryRunPlanRow.dry_run_plan_id == plan_row.id)
        )
    ).scalar_one()
    assert before.normalized_values is not None
    before_id = before.id
    before_expected_version = before.expected_equipment_version
    before_row_number = before.source_row_number

    # Force the session into a claimable, eligible state, then run the
    # real claim + fenced redaction pipeline (§18/§14.9).
    from datetime import datetime, timedelta, timezone

    session_db = (await db_session.execute(select(ImportSession).where(ImportSession.id == session_uuid))).scalar_one()
    session_db.status = "cancelled"
    session_db.terminal_at = datetime.now(timezone.utc) - timedelta(days=400)
    await db_session.commit()

    worker_id = uuid.uuid4()
    claimed_ids, _has_more = await import_retention_crud.claim_sessions_for_cleanup(
        db_session, worker_id=worker_id, retention_days=180, claim_timeout_seconds=300, limit=10
    )
    assert session_uuid in claimed_ids
    redacted = await import_retention_crud.redact_session(db_session, session_id=session_uuid, worker_id=worker_id)
    assert redacted is not None
    await db_session.commit()

    after = (
        await db_session.execute(select(EquipmentMasterDryRunPlanRow).where(EquipmentMasterDryRunPlanRow.id == before_id))
    ).scalar_one()
    assert after.normalized_values is None
    assert after.matched_identity_fields is None
    assert after.warnings is None
    # Structural fields survive redaction.
    assert after.action == "UPDATE"
    assert after.target_equipment_id == existing.id
    assert after.expected_equipment_version == before_expected_version
    assert after.source_row_number == before_row_number
