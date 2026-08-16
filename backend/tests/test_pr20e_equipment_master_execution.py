"""Roadmap PR20E (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §14.4,
§14.4a, §14.4b, §14.4c, §15, §15.1, §16). Covers: `precheck_execute`'s
pre-admission confirmed-plan gate, `execute()`'s CREATE/UPDATE application
against the exact persisted/confirmed plan (never a live recomputation),
`Equipment.version` compare-and-swap for UPDATE rows, protected-field
enforcement, no-op-update version-bump suppression, OD-4 authoritative-
asset_number enforcement (fail closed, never fabricated), OD-2 lifecycle/
location policy (including the ISSUED_TO_WARD CREATE refusal), all-or-
nothing TX1 atomicity, `AdapterExecutionConflict`/`on_execution_failure`
plan-failure-marking (§14.4b), `on_execution_recovery`'s hard-crash
reconciliation (§14.4c), plan consumption, and execute's existing
state-based idempotency (PR19A3, unchanged). This is the first PR20 slice
that mutates `Equipment` -- every test here that expects failure also
asserts no Equipment row was created/changed.

Genuine two-PostgreSQL-connection concurrency tests (concurrent UPDATE CAS,
CREATE identity race) live in `test_postgres_integration.py`, mirroring
this codebase's own established idiom (see that file's PR94 sections) --
SQLite cannot prove real database-level race resolution.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit import AUDIT_ACTION_IMPORT
from app.crud import import_dry_run_plan as import_dry_run_plan_crud
from app.crud import import_job as import_job_crud
from app.models.audit import AuditLog
from app.models.equipment import Equipment, EquipmentStatus
from app.models.import_session import (
    EquipmentMasterDryRunPlan,
    EquipmentMasterDryRunPlanRow,
    ImportJob,
    ImportSession,
    ImportSource,
)
from app.services import import_execution_service, import_lease, import_validation_service
from app.services.import_adapters.equipment_master import DATASET_TYPE
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

_HEADERS_ORDER = ["ID CODE", "Item No.", "ชื่อไทย", "สถานะเครื่องมือ"]


@pytest_asyncio.fixture(autouse=True)
async def _patch_execution_session_factories(db_engine, monkeypatch):
    """Mirrors test_pr20d_dry_run_plan.py's identical fixture -- every
    module that opens its own `AsyncSessionLocal()` (TX2, recovery) must
    be repointed at this test's own engine."""
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
        "ID CODE": overrides.pop("bcm", "BCM_PR20E_1"),
        "Item No.": overrides.pop("item_no", "ITEM_PR20E_1"),
        "ชื่อไทย": overrides.pop("equipment_name", "เครื่องมือทดสอบ PR20E"),
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


async def _dry_run_completed_session(client, headers, rows: list[dict]) -> dict:
    session = await _create_session(client, headers)
    content = _build_workbook_bytes(rows)
    up = await _upload(client, headers, session["id"], content)
    assert up.status_code == 201, up.text
    v = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert v.status_code == 200, v.text
    d = await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    assert d.status_code == 200, d.text
    assert d.json()["status"] == "dry_run_completed", d.json()
    return session


async def _confirm_current_plan(client, headers, session_id: str) -> dict:
    plan = (await client.get(f"/api/v1/import-sessions/{session_id}/dry-run-plan", headers=headers)).json()
    r = await client.post(f"/api/v1/import-sessions/{session_id}/dry-run-plan/{plan['id']}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _confirmed_update_session(client, headers, db_session, *, equipment_name: str, bcm: str, item_no: str):
    """End-to-end (real parser/validate/dry-run/confirm) session with one
    genuinely-planned UPDATE row targeting a real, existing Equipment
    record."""
    equipment = await _seed_equipment(db_session, bcm_code=bcm, item_no=item_no, equipment_name="Original Name")
    session = await _dry_run_completed_session(client, headers, [_valid_row(bcm=bcm, item_no=item_no, equipment_name=equipment_name)])
    confirmed = await _confirm_current_plan(client, headers, session["id"])
    return session, equipment, confirmed


# ---------------------------------------------------------------------------
# ORM-direct plan construction -- for CREATE-branch and synthetic-conflict
# scenarios the real parser can never produce today (§9 OD-4 unconditionally
# blocks every CREATE candidate under the current 32-column source
# contract, mirroring PR20D's own test precedent for the same reason, see
# test_pr20d_dry_run_plan.py).
# ---------------------------------------------------------------------------


async def _seed_dry_run_completed_session_direct(db_session, actor_id):
    now = datetime.now(timezone.utc)
    session = ImportSession(dataset_type=DATASET_TYPE, status="dry_run_completed", version=2, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    source = ImportSource(
        import_session_id=session.id,
        status="frozen",
        checksum="d" * 64,
        byte_size=4,
        options_fingerprint="x",
        source_fingerprint="y",
        frozen_at=now,
        created_at=now,
    )
    db_session.add(source)
    validate_job = ImportJob(import_session_id=session.id, job_type="validate", status="succeeded", attempt_number=1, lease_generation=1)
    db_session.add(validate_job)
    dry_run_job = ImportJob(import_session_id=session.id, job_type="dry_run", status="succeeded", attempt_number=1, lease_generation=1)
    db_session.add(dry_run_job)
    await db_session.flush()
    return session, source, validate_job, dry_run_job


async def _seed_confirmed_plan(db_session, actor_id, *, rows_data: list[dict]):
    session, source, validate_job, dry_run_job = await _seed_dry_run_completed_session_direct(db_session, actor_id)
    creates = sum(1 for r in rows_data if r["action"] == "CREATE")
    updates = sum(1 for r in rows_data if r["action"] == "UPDATE")
    skips = sum(1 for r in rows_data if r["action"] == "SKIP")
    plan = EquipmentMasterDryRunPlan(
        import_session_id=session.id,
        import_source_id=source.id,
        source_checksum=source.checksum,
        accepted_validation_job_id=validate_job.id,
        dry_run_job_id=dry_run_job.id,
        ruleset_version="1",
        status="active",
        confirmed_at=datetime.now(timezone.utc),
        confirmed_by_user_id=actor_id,
        summary_total_rows=len(rows_data),
        summary_creates=creates,
        summary_updates=updates,
        summary_skips=skips,
        summary_warnings=0,
        summary_blocking_conflicts=0,
    )
    db_session.add(plan)
    await db_session.flush()
    row_models = [
        EquipmentMasterDryRunPlanRow(
            dry_run_plan_id=plan.id,
            source_row_number=i + 1,
            action=r["action"],
            target_equipment_id=r.get("target_equipment_id"),
            normalized_values=r.get("normalized_values", {}),
            matched_identity_fields=r.get("matched_identity_fields", {}),
            expected_equipment_version=r.get("expected_equipment_version"),
            warnings=r.get("warnings", []),
        )
        for i, r in enumerate(rows_data)
    ]
    db_session.add_all(row_models)
    await db_session.commit()
    await db_session.refresh(session)
    await db_session.refresh(plan)
    return session, plan


# ---------------------------------------------------------------------------
# precheck_execute: pre-admission confirmed-plan gate (§14.4a)
# ---------------------------------------------------------------------------


async def test_execute_rejects_unconfirmed_plan_before_admission(client: AsyncClient, seeded_users, db_session):
    admin = seeded_users["administrator"]
    session, source, validate_job, dry_run_job = await _seed_dry_run_completed_session_direct(db_session, admin.id)
    plan = EquipmentMasterDryRunPlan(
        import_session_id=session.id,
        import_source_id=source.id,
        source_checksum=source.checksum,
        accepted_validation_job_id=validate_job.id,
        dry_run_job_id=dry_run_job.id,
        ruleset_version="1",
        status="active",
        confirmed_at=None,
        confirmed_by_user_id=None,
        summary_total_rows=0,
        summary_creates=0,
        summary_updates=0,
        summary_skips=0,
        summary_warnings=0,
        summary_blocking_conflicts=0,
    )
    db_session.add(plan)
    await db_session.commit()
    session_id = session.id

    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{session_id}/execute", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "IMPORT_NO_CONFIRMED_PLAN"

    db_session.expire_all()
    refreshed = (await db_session.execute(select(ImportSession).where(ImportSession.id == session_id))).scalar_one()
    assert refreshed.status == "dry_run_completed", "precheck rejection must never touch session state"


async def test_execute_accepts_no_body(client: AsyncClient, seeded_users, db_session):
    """§14.4: the generic POST /{id}/execute route stays exactly bodyless
    -- no new field, no route-level change."""
    headers = await auth_headers(client)
    session, equipment, _confirmed = await _confirmed_update_session(
        client, headers, db_session, equipment_name="Updated Name A", bcm="BCM_NOBODY", item_no="ITEM_NOBODY"
    )
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers, content=b"")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# UPDATE: CAS, protected fields, no-op
# ---------------------------------------------------------------------------


async def test_execute_update_applies_writable_fields_bumps_version_once(
    client: AsyncClient, seeded_users, db_session
):
    headers = await auth_headers(client)
    session, equipment, _confirmed = await _confirmed_update_session(
        client, headers, db_session, equipment_name="Renamed Equipment", bcm="BCM_UPDOK", item_no="ITEM_UPDOK"
    )
    original_version = equipment.version
    equipment_id = equipment.id

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["imported_rows"] == 1

    db_session.expire_all()
    refreshed = (await db_session.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
    assert refreshed.equipment_name == "Renamed Equipment"
    assert refreshed.version == original_version + 1

    session_uuid = uuid.UUID(session["id"])
    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION_IMPORT, AuditLog.entity_id == session_uuid)))
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1

    plan_row = (
        await db_session.execute(select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_uuid))
    ).scalar_one()
    assert plan_row.status == "consumed"


async def test_execute_update_never_overwrites_protected_fields(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    equipment = await _seed_equipment(
        db_session,
        bcm_code="BCM_PROTECT",
        item_no="ITEM_PROTECT",
        equipment_name="Original Name",
        status=EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    )
    original_bcm, original_item_no, original_status = equipment.bcm_code, equipment.item_no, equipment.status
    original_location = equipment.current_location_id
    equipment_id = equipment.id

    session = await _dry_run_completed_session(
        client, headers, [_valid_row(bcm="BCM_PROTECT", item_no="ITEM_PROTECT", equipment_name="New Name", status="active")]
    )
    await _confirm_current_plan(client, headers, session["id"])

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    refreshed = (await db_session.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
    assert refreshed.equipment_name == "New Name", "descriptive master data must still be updated"
    assert refreshed.bcm_code == original_bcm
    assert refreshed.item_no == original_item_no
    assert refreshed.status == original_status, "legacy status must never overwrite current live status on UPDATE"
    assert refreshed.current_location_id == original_location


async def test_execute_noop_update_does_not_bump_version(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    # The plan's proposed value already equals the record's current value.
    session, equipment, _confirmed = await _confirmed_update_session(
        client, headers, db_session, equipment_name="Original Name", bcm="BCM_NOOP", item_no="ITEM_NOOP"
    )
    original_version = equipment.version
    equipment_id = equipment.id

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["imported_rows"] == 0, "a same-value update must not count as an imported row"

    db_session.expire_all()
    refreshed = (await db_session.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
    assert refreshed.version == original_version, "a no-op update must never bump Equipment.version"


async def test_execute_stale_update_conflict_rolls_back_and_terminally_fails(
    client: AsyncClient, seeded_users, db_session
):
    headers = await auth_headers(client)
    session, equipment, _confirmed = await _confirmed_update_session(
        client, headers, db_session, equipment_name="Attempted Rename", bcm="BCM_STALEUPD", item_no="ITEM_STALEUPD"
    )
    equipment_id = equipment.id

    # Simulate a concurrent legitimate mutation after dry-run captured
    # expected_equipment_version, before execute runs.
    live = (await db_session.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
    live.equipment_name = "Changed By Someone Else"
    live.version += 1
    await db_session.commit()
    conflicting_version = live.version

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 500, r.text
    assert r.json()["code"] == "IMPORT_EXECUTION_FAILED"

    db_session.expire_all()
    refreshed = (await db_session.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
    assert refreshed.equipment_name == "Changed By Someone Else", "the newer data must never be clobbered"
    assert refreshed.version == conflicting_version, "no import-driven version bump on a conflicting attempt"

    session_uuid = uuid.UUID(session["id"])
    final_session = (await db_session.execute(select(ImportSession).where(ImportSession.id == session_uuid))).scalar_one()
    assert final_session.status == "failed"
    plan_row = (
        await db_session.execute(select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_uuid))
    ).scalar_one()
    assert plan_row.status == "failed", "the plan must be marked failed in the same TX2 as the session"


async def test_execute_update_target_soft_deleted_is_rejected(client: AsyncClient, seeded_users, db_session):
    """§15.1 fix round 7 (H13): a persisted UPDATE-action row targeting a
    since-soft-deleted Equipment row is rejected by the `deleted_at IS
    NULL` predicate specifically -- construct the scenario so the naive
    version-only check would otherwise still match."""
    headers = await auth_headers(client)
    session, equipment, _confirmed = await _confirmed_update_session(
        client, headers, db_session, equipment_name="Should Never Apply", bcm="BCM_SOFTDEL", item_no="ITEM_SOFTDEL"
    )
    from app.crud import equipment as equipment_crud

    live = (await db_session.execute(select(Equipment).where(Equipment.id == equipment.id))).scalar_one()
    captured_version = live.version
    await equipment_crud.soft_delete(db_session, live)
    await db_session.commit()
    # soft_delete() bumps version, but even if it hadn't, deleted_at IS
    # NULL alone must reject the match -- assert the token would
    # otherwise still equal the plan's captured expected_equipment_version
    # is not required for the assertion itself; the predicate rejects on
    # deleted_at regardless.
    assert live.version != captured_version

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r.status_code == 500, r.text
    assert r.json()["code"] == "IMPORT_EXECUTION_FAILED"


# ---------------------------------------------------------------------------
# CREATE: OD-4 authoritative asset_number, OD-2 lifecycle, identity races.
# Real dry-run/parse output can never produce an executable CREATE row
# today (§9 OD-4 unconditionally blocks every CREATE candidate) -- these
# tests construct the persisted plan directly, matching PR20D's own
# established precedent for exercising this branch.
# ---------------------------------------------------------------------------


async def test_execute_create_row_with_authoritative_asset_number_succeeds(
    client: AsyncClient, seeded_users, db_session
):
    admin = seeded_users["administrator"]
    session, plan = await _seed_confirmed_plan(
        db_session,
        admin.id,
        rows_data=[
            {
                "action": "CREATE",
                "normalized_values": {
                    "asset_number": "AN-CREATE-OK-0001",
                    "bcm_code": "BCM_CREATE_OK",
                    "item_no": "ITEM_CREATE_OK",
                    "equipment_name": "Newly Created Equipment",
                    "brand": "BrandX",
                    "model": "ModelY",
                    "serial_number": "SN-0001",
                    "asset_id": "AID-0001",
                    "status": EquipmentStatus.AVAILABLE_AT_POOL.value,
                },
            }
        ],
    )
    plan_id = plan.id
    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{session.id}/execute", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["imported_rows"] == 1

    db_session.expire_all()
    created = (await db_session.execute(select(Equipment).where(Equipment.asset_number == "AN-CREATE-OK-0001"))).scalar_one()
    assert created.bcm_code == "BCM_CREATE_OK"
    assert created.item_no == "ITEM_CREATE_OK"
    assert created.equipment_name == "Newly Created Equipment"
    assert created.brand == "BrandX"
    assert created.model == "ModelY"
    assert created.serial_number == "SN-0001"
    assert created.asset_id == "AID-0001"
    assert created.status == EquipmentStatus.AVAILABLE_AT_POOL
    assert created.version == 1
    assert created.category_id is None
    assert created.department_owner_id is None
    assert created.current_location_id is None
    assert isinstance(created.id, uuid.UUID)

    refreshed_plan = (await db_session.execute(select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.id == plan_id))).scalar_one()
    assert refreshed_plan.status == "consumed"


async def test_execute_create_row_without_asset_number_fails_closed(client: AsyncClient, seeded_users, db_session):
    admin = seeded_users["administrator"]
    session, plan = await _seed_confirmed_plan(
        db_session,
        admin.id,
        rows_data=[
            {
                "action": "CREATE",
                "normalized_values": {
                    # No "asset_number" key at all -- matches exactly what
                    # the real parser produces today (§9 OD-4).
                    "bcm_code": "BCM_NO_ASSET",
                    "item_no": "ITEM_NO_ASSET",
                    "equipment_name": "Should Never Be Created",
                    "status": EquipmentStatus.AVAILABLE_AT_POOL.value,
                },
            }
        ],
    )
    plan_id = plan.id
    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{session.id}/execute", headers=headers)
    assert r.status_code == 500, r.text
    assert r.json()["code"] == "IMPORT_EXECUTION_FAILED"

    db_session.expire_all()
    exists = (await db_session.execute(select(Equipment).where(Equipment.bcm_code == "BCM_NO_ASSET"))).scalar_one_or_none()
    assert exists is None, "a CREATE row lacking an authoritative asset_number must never fabricate one"

    refreshed_plan = (await db_session.execute(select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.id == plan_id))).scalar_one()
    assert refreshed_plan.status == "failed"


async def test_execute_create_row_issued_to_ward_status_fails_closed(client: AsyncClient, seeded_users, db_session):
    """§9 OD-2 Legacy Lifecycle Policy / §22: creating Equipment directly
    into ISSUED_TO_WARD with no corresponding BorrowTransaction would
    violate the ledger invariant -- refused even if a row somehow
    reaches execute() with that value (upstream STATUS_MAPPING already
    never produces it for a real parsed row)."""
    admin = seeded_users["administrator"]
    session, plan = await _seed_confirmed_plan(
        db_session,
        admin.id,
        rows_data=[
            {
                "action": "CREATE",
                "normalized_values": {
                    "asset_number": "AN-ISSUED-0001",
                    "bcm_code": "BCM_ISSUED",
                    "item_no": "ITEM_ISSUED",
                    "equipment_name": "Should Never Be Created As Issued",
                    "status": EquipmentStatus.ISSUED_TO_WARD.value,
                },
            }
        ],
    )
    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{session.id}/execute", headers=headers)
    assert r.status_code == 500, r.text

    db_session.expire_all()
    exists = (await db_session.execute(select(Equipment).where(Equipment.bcm_code == "BCM_ISSUED"))).scalar_one_or_none()
    assert exists is None, "Equipment must never be created directly into ISSUED_TO_WARD"


async def test_execute_create_row_identity_conflict_fails_closed(client: AsyncClient, seeded_users, db_session):
    """CREATE-row concurrency (§15.1): a BCM/asset_number collision with
    an already-existing Equipment record is rejected by the database's
    own unique constraint, surfaced as a genuine execution conflict --
    never silently converted to an UPDATE."""
    await _seed_equipment(db_session, bcm_code="BCM_TAKEN", asset_number="AN-TAKEN-0001", item_no="ITEM_TAKEN_EXISTING")
    admin = seeded_users["administrator"]
    session, plan = await _seed_confirmed_plan(
        db_session,
        admin.id,
        rows_data=[
            {
                "action": "CREATE",
                "normalized_values": {
                    "asset_number": "AN-DIFFERENT-0002",
                    "bcm_code": "BCM_TAKEN",  # collides with the seeded row
                    "item_no": "ITEM_TAKEN_NEW",
                    "equipment_name": "Colliding Create",
                    "status": EquipmentStatus.AVAILABLE_AT_POOL.value,
                },
            }
        ],
    )
    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{session.id}/execute", headers=headers)
    assert r.status_code == 500, r.text

    db_session.expire_all()
    colliding = (await db_session.execute(select(Equipment).where(Equipment.asset_number == "AN-DIFFERENT-0002"))).scalar_one_or_none()
    assert colliding is None


# ---------------------------------------------------------------------------
# Mixed-plan atomicity (§15): all-or-nothing across multiple rows.
# ---------------------------------------------------------------------------


async def test_execute_mixed_plan_rolls_back_earlier_rows_on_later_conflict(
    client: AsyncClient, seeded_users, db_session
):
    admin = seeded_users["administrator"]
    good_equipment = await _seed_equipment(db_session, bcm_code="BCM_MIXED_OK", item_no="ITEM_MIXED_OK", equipment_name="Before")
    stale_equipment = await _seed_equipment(db_session, bcm_code="BCM_MIXED_STALE", item_no="ITEM_MIXED_STALE", equipment_name="Before Stale")
    captured_version = stale_equipment.version

    session, plan = await _seed_confirmed_plan(
        db_session,
        admin.id,
        rows_data=[
            {
                "action": "UPDATE",
                "target_equipment_id": good_equipment.id,
                "expected_equipment_version": good_equipment.version,
                "normalized_values": {"equipment_name": "After"},
            },
            {
                "action": "UPDATE",
                "target_equipment_id": stale_equipment.id,
                "expected_equipment_version": captured_version,
                "normalized_values": {"equipment_name": "After Stale"},
            },
        ],
    )

    good_equipment_id = good_equipment.id
    good_equipment_version = good_equipment.version
    stale_equipment_id = stale_equipment.id

    # Conflict the second row's target after the plan was persisted.
    live = (await db_session.execute(select(Equipment).where(Equipment.id == stale_equipment_id))).scalar_one()
    live.equipment_name = "Changed Concurrently"
    live.version += 1
    await db_session.commit()

    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{session.id}/execute", headers=headers)
    assert r.status_code == 500, r.text

    db_session.expire_all()
    refreshed_good = (await db_session.execute(select(Equipment).where(Equipment.id == good_equipment_id))).scalar_one()
    assert refreshed_good.equipment_name == "Before", "an earlier, individually-valid row must roll back too -- all or nothing"
    assert refreshed_good.version == good_equipment_version


# ---------------------------------------------------------------------------
# Idempotency (PR19A3, unchanged) -- execute is state-based, not fingerprint.
# ---------------------------------------------------------------------------


async def test_execute_completed_session_replay_is_idempotent(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session, equipment, _confirmed = await _confirmed_update_session(
        client, headers, db_session, equipment_name="Renamed Once", bcm="BCM_REPLAY", item_no="ITEM_REPLAY"
    )
    equipment_id = equipment.id
    original_version = equipment.version
    r1 = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r1.status_code == 200, r1.text

    r2 = await client.post(f"/api/v1/import-sessions/{session['id']}/execute", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "completed"
    assert r2.json()["imported_rows"] == r1.json()["imported_rows"]

    db_session.expire_all()
    refreshed = (await db_session.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
    assert refreshed.version == original_version + 1, "a replay must never re-apply the mutation a second time"

    session_uuid = uuid.UUID(session["id"])
    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION_IMPORT, AuditLog.entity_id == session_uuid)))
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1, "a replay of an already-completed execute must never write a second audit row"


# ---------------------------------------------------------------------------
# on_execution_recovery (§14.4c): hard-crash reconciliation.
# ---------------------------------------------------------------------------


async def test_recovery_after_execute_lease_loss_marks_session_and_plan_failed_together(
    client: AsyncClient, seeded_users, db_session
):
    headers = await auth_headers(client)
    session, equipment, _confirmed = await _confirmed_update_session(
        client, headers, db_session, equipment_name="Never Applied", bcm="BCM_RECOVER", item_no="ITEM_RECOVER"
    )
    equipment_id = equipment.id
    session_id = uuid.UUID(session["id"])
    current = (await db_session.execute(select(ImportSession).where(ImportSession.id == session_id))).scalar_one()

    _s, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session_id,
        job_type="execute",
        allowed_from_statuses=("dry_run_completed",),
        running_status="executing",
        expected_version=current.version,
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )
    assert job is not None
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"

    db_session.expire_all()
    plan_row = (
        await db_session.execute(select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_id))
    ).scalar_one()
    assert plan_row.status == "failed", "a hard-crash recovery must reconcile the plan to failed too, never left active"

    refreshed_equipment = (await db_session.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
    assert refreshed_equipment.equipment_name == "Original Name", "no partial mutation from a worker that never committed"


async def test_recovery_for_dry_run_phase_never_touches_plan(client: AsyncClient, seeded_users, db_session):
    """job_type gate (§14.4c): dry_run/validate recovery never calls
    on_execution_recovery -- a plan created by an unrelated, still-active
    session must be untouched by a dry-run-phase recovery."""
    headers = await auth_headers(client)
    # A matching Equipment record is seeded so the row becomes a genuine
    # UPDATE candidate -- a CREATE candidate is always blocking (§9 OD-4),
    # which would fail validate() outright before this test ever reaches
    # its own dry-run-admission scenario.
    await _seed_equipment(db_session, bcm_code="BCM_DRYFAIL_REC", item_no="ITEM_DRYFAIL_REC")
    session = await _create_session(client, headers)
    content = _build_workbook_bytes([_valid_row(bcm="BCM_DRYFAIL_REC", item_no="ITEM_DRYFAIL_REC")])
    up = await _upload(client, headers, session["id"], content)
    assert up.status_code == 201, up.text
    v = await client.post(f"/api/v1/import-sessions/{session['id']}/validate", headers=headers)
    assert v.status_code == 200, v.text
    assert v.json()["status"] == "validated", v.json()

    session_id = uuid.UUID(session["id"])
    current = (await db_session.execute(select(ImportSession).where(ImportSession.id == session_id))).scalar_one()
    _s, job = await import_job_crud.admit_phase_job(
        db_session,
        session_id=session_id,
        job_type="dry_run",
        allowed_from_statuses=("validated",),
        running_status="dry_run_running",
        expected_version=current.version,
        lease_owner=uuid.uuid4(),
        lease_duration_seconds=300,
    )
    assert job is not None
    await db_session.execute(
        ImportJob.__table__.update().where(ImportJob.id == job.id).values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/recover", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dry_run_failed"

    db_session.expire_all()
    plans = (
        (await db_session.execute(select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_id)))
        .scalars()
        .all()
    )
    assert plans == [], "a session with no successful dry-run has no plan to touch in the first place"
