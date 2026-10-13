"""Roadmap PR22E -- Reconciliation Sign-off + Concurrency/Audit.

Tests `POST/GET /api/v1/legacy-reconciliation-runs/{run_id}/sign-off`
(`app.api.v1.legacy_reconciliation`) and
`app.crud.legacy_reconciliation.create_signoff`'s contract: all eight
sign-off preconditions, authorization, mandatory audit atomicity, the
server-generated attestation shape, and immutability.

The genuine two-connection lock-order/race proofs (concurrent sign-off,
sign-off-vs-disposition) and the audit-failure-rollback proof are all
proved in `test_pr22e_reconciliation_signoff_concurrency.py` instead of
here, mirroring `test_pr22d_finding_review_concurrency.py`'s identical
convention -- every genuine transaction-semantics proof lives in the
PostgreSQL-only suite, not the SQLite one this file's `client`/
`db_session` fixtures use. The audit-rollback proof specifically cannot
run correctly against this repository's SQLite test engine (see the
"G. Mandatory audit atomicity" section below for why) -- it is a real
PostgreSQL-only proof, not merely a stylistic choice.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.equipment import Equipment, EquipmentStatus
from app.models.legacy_history import LegacyEquipmentEvent, LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationFinding,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)
from app.models.import_session import ImportSession, ImportSource
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY, User
from app.services.reconciliation.rule_version import PR22_RECONCILIATION_RULE_VERSION
from tests.conftest import auth_headers

_COVERAGE_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
_COVERAGE_END = datetime(2024, 12, 31, tzinfo=timezone.utc)
_LIVE_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


async def _actor_id(db_session: AsyncSession) -> uuid.UUID:
    return (await db_session.execute(select(User.id).where(User.employee_code == "ADMINISTRATOR001"))).scalar_one()


def _checksum(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


async def _seed_coverage(db_session: AsyncSession, *, actor_id: uuid.UUID, checksum: str) -> LegacyMigrationAuthorityCoverage:
    authority = LegacyMigrationAuthority(scope="pr22e_test", approved_workbook_sha256=_checksum(checksum), approved_by_user_id=actor_id)
    db_session.add(authority)
    await db_session.flush()
    coverage = LegacyMigrationAuthorityCoverage(
        migration_authority_id=authority.id,
        legacy_coverage_start=_COVERAGE_START,
        legacy_coverage_end=_COVERAGE_END,
        live_system_start=_LIVE_START,
        approval_basis="explicit_administrator_approval",
        approved_by_user_id=actor_id,
    )
    db_session.add(coverage)
    await db_session.commit()
    await db_session.refresh(coverage)
    return coverage


async def _seed_run(
    db_session: AsyncSession, *, coverage: LegacyMigrationAuthorityCoverage, actor_id: uuid.UUID, **overrides
) -> LegacyReconciliationRun:
    defaults = dict(
        coverage_id=coverage.id,
        legacy_coverage_start=coverage.legacy_coverage_start,
        legacy_coverage_end=coverage.legacy_coverage_end,
        live_system_start=coverage.live_system_start,
        rule_version=PR22_RECONCILIATION_RULE_VERSION,
        snapshot_as_of=datetime.now(timezone.utc),
        created_by_user_id=actor_id,
        status="completed",
        summary_total_findings=0,
    )
    defaults.update(overrides)
    run = LegacyReconciliationRun(**defaults)
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


async def _seed_finding(
    db_session: AsyncSession, *, run_id: uuid.UUID, code: str = "SOURCE_PROVENANCE", severity: str = "high", **overrides
) -> LegacyReconciliationFinding:
    defaults = dict(
        run_id=run_id, code=code, severity=severity, evidence={"reason_code": "test"},
        rule_version=PR22_RECONCILIATION_RULE_VERSION,
    )
    defaults.update(overrides)
    finding = LegacyReconciliationFinding(**defaults)
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    return finding


async def _seed_equipment(db_session: AsyncSession, *, seed: str) -> Equipment:
    eq = Equipment(asset_number=f"AN-{seed}", equipment_name="PR22E Test Equipment", status=EquipmentStatus.AVAILABLE_AT_POOL)
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    return eq


async def _seed_legacy_event(db_session: AsyncSession, *, authority_id, equipment_id, actor_id, row_key: str) -> LegacyEquipmentEvent:
    session = ImportSession(dataset_type="legacy_history", status="dry_run_completed", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    source = ImportSource(
        import_session_id=session.id, status="frozen", checksum="9" * 64, byte_size=1,
        content_type="application/vnd.ms-excel", filename="wb.xlsx", options_fingerprint="x",
        source_fingerprint="y", frozen_at=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(session)
    await db_session.refresh(source)

    event = LegacyEquipmentEvent(
        migration_authority_id=authority_id, equipment_id=equipment_id, event_type="ISSUE",
        occurred_at=_COVERAGE_START + timedelta(days=1), legacy_source_row_key=row_key,
        import_session_id=session.id, import_source_id=source.id,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    return event


async def _seed_fully_dispositioned_run(
    db_session: AsyncSession, *, actor_id: uuid.UUID, checksum: str, dispositions: list[str], **run_overrides
) -> LegacyReconciliationRun:
    """A completed run with one finding per requested disposition value,
    plus `summary_total_findings` set to match -- eligible for sign-off
    unless a requested disposition is `requires_correction` or `None`
    (unreviewed)."""
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum=checksum)
    run = await _seed_run(
        db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=len(dispositions), **run_overrides
    )
    now = datetime.now(timezone.utc)
    for d in dispositions:
        kwargs = {}
        if d is not None:
            kwargs = dict(disposition=d, disposed_by_user_id=actor_id, disposed_at=now)
        await _seed_finding(db_session, run_id=run.id, **kwargs)
    return run


# ---------------------------------------------------------------------------
# A. Happy path / eligible dispositions (§32-33 of the task).
# ---------------------------------------------------------------------------


async def test_signoff_happy_path_creates_row_and_audit(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    run = await _seed_fully_dispositioned_run(
        db_session, actor_id=actor_id, checksum="hp", dispositions=["confirmed_valid", "confirmed_duplicate", "accepted_unresolved"]
    )

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["run_id"] == str(run.id)
    assert body["signed_off_by_user_id"] == str(actor_id)
    assert body["run_version_at_signoff"] == 0
    attestation = body["attestation_summary"]
    assert attestation["summary_total_findings"] == 3
    assert attestation["dispositions"] == {
        "confirmed_valid": 1, "confirmed_duplicate": 1, "accepted_unresolved": 1, "requires_correction": 0,
    }
    assert attestation["unreviewed_findings"] == 0
    assert attestation["rule_version"] == PR22_RECONCILIATION_RULE_VERSION

    rows = (await db_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))).scalars().all()
    assert len(rows) == 1

    audit_rows = (await db_session.execute(select(AuditLog).where(AuditLog.entity_id == rows[0].id))).scalars().all()
    assert len(audit_rows) == 1
    assert audit_rows[0].action == "reconciliation_signoff"
    assert audit_rows[0].entity_type == "reconciliation_signoff"
    assert audit_rows[0].after_data["run_id"] == str(run.id)


@pytest.mark.parametrize("disposition", ["confirmed_valid", "confirmed_duplicate", "accepted_unresolved"])
async def test_signoff_single_eligible_disposition_does_not_block(client: AsyncClient, seeded_users, db_session, disposition):
    actor_id = await _actor_id(db_session)
    run = await _seed_fully_dispositioned_run(db_session, actor_id=actor_id, checksum=f"e{disposition[:2]}", dispositions=[disposition])

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 201, r.text


async def test_signoff_zero_finding_run_eligible(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="zf")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=0)

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["attestation_summary"]["summary_total_findings"] == 0
    assert body["attestation_summary"]["dispositions"] == {
        "confirmed_valid": 0, "confirmed_duplicate": 0, "accepted_unresolved": 0, "requires_correction": 0,
    }


# ---------------------------------------------------------------------------
# B. Blocking preconditions (§34-36 of the task).
# ---------------------------------------------------------------------------


async def test_signoff_requires_correction_blocks_even_if_all_dispositioned(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    run = await _seed_fully_dispositioned_run(
        db_session, actor_id=actor_id, checksum="rc", dispositions=["confirmed_valid", "requires_correction"]
    )

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RECONCILIATION_SIGNOFF_REQUIRES_CORRECTION"

    assert (await db_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))).scalars().all() == []
    assert (await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "reconciliation_signoff"))).scalars().all() == []


async def test_signoff_unreviewed_finding_blocks(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    run = await _seed_fully_dispositioned_run(db_session, actor_id=actor_id, checksum="ur", dispositions=["confirmed_valid", None])

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RECONCILIATION_SIGNOFF_FINDINGS_INCOMPLETE"

    assert (await db_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))).scalars().all() == []
    assert (await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "reconciliation_signoff"))).scalars().all() == []


async def test_signoff_both_blockers_deterministic_precedence_incomplete_first(client: AsyncClient, seeded_users, db_session):
    """§36 of the task: a run with both a null-disposition finding and a
    requires_correction finding must reject deterministically --
    documented precedence (ERROR_CODES.md): incomplete review first."""
    actor_id = await _actor_id(db_session)
    run = await _seed_fully_dispositioned_run(db_session, actor_id=actor_id, checksum="bb", dispositions=["requires_correction", None])

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RECONCILIATION_SIGNOFF_FINDINGS_INCOMPLETE"


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
async def test_signoff_rejected_for_non_completed_run(client: AsyncClient, seeded_users, db_session, status):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum=f"nc{status[:1]}")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status=status)

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RECONCILIATION_SIGNOFF_RUN_NOT_COMPLETED"


async def test_signoff_stale_version_conflict(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="sv")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=0)

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 99}
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RECONCILIATION_SIGNOFF_VERSION_CONFLICT"
    assert (await db_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))).scalars().all() == []


async def test_signoff_coverage_mismatch_rejected(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="cm")
    run = await _seed_run(
        db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=0,
        legacy_coverage_end=coverage.legacy_coverage_end + timedelta(days=1),
    )

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RECONCILIATION_COVERAGE_MISMATCH"
    assert (await db_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))).scalars().all() == []


async def test_signoff_evidence_inconsistent_rejected(client: AsyncClient, seeded_users, db_session):
    """§21/§44 of the task: `summary_total_findings` disagrees with the
    actual persisted finding count -- fail closed, never normalized."""
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="ei")
    # summary_total_findings deliberately wrong (claims 5, actually 1).
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=5)
    await _seed_finding(db_session, run_id=run.id, disposition="confirmed_valid", disposed_by_user_id=actor_id, disposed_at=datetime.now(timezone.utc))

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RECONCILIATION_SIGNOFF_EVIDENCE_INCONSISTENT"
    assert (await db_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))).scalars().all() == []


async def test_signoff_run_not_found(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{uuid.uuid4()}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "RECONCILIATION_RUN_NOT_FOUND"


# ---------------------------------------------------------------------------
# C. Existing sign-off (§14/§39 of the task).
# ---------------------------------------------------------------------------


async def test_second_signoff_post_rejected_original_unchanged(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="dup")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=0)

    headers = await auth_headers(client)
    r1 = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r1.status_code == 201, r1.text
    original = r1.json()

    r2 = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["code"] == "RECONCILIATION_SIGNOFF_ALREADY_EXISTS"

    rows = (await db_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))).scalars().all()
    assert len(rows) == 1
    assert str(rows[0].id) == original["id"]

    audit_rows = (await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "reconciliation_signoff"))).scalars().all()
    assert len(audit_rows) == 1, "no second audit event for a rejected duplicate sign-off"


# ---------------------------------------------------------------------------
# D. GET sign-off (§26 of the task).
# ---------------------------------------------------------------------------


async def test_get_signoff_not_found(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="gnf")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers)
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "RECONCILIATION_SIGNOFF_NOT_FOUND"


async def test_get_signoff_run_not_found(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-reconciliation-runs/{uuid.uuid4()}/sign-off", headers=headers)
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "RECONCILIATION_RUN_NOT_FOUND"


async def test_get_signoff_returns_existing_attestation(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="ga")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=0)

    headers = await auth_headers(client)
    post = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert post.status_code == 201, post.text

    get = await client.get(f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers)
    assert get.status_code == 200, get.text
    assert get.json()["id"] == post.json()["id"]
    assert get.json()["attestation_summary"] == post.json()["attestation_summary"]


# ---------------------------------------------------------------------------
# E. Authorization (§27/§46 of the task).
# ---------------------------------------------------------------------------


async def test_signoff_post_admin_allowed(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="aa")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=0)

    headers = await auth_headers(client, role=ROLE_ADMINISTRATOR)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 201, r.text


async def test_signoff_post_equipment_pool_staff_forbidden(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="ab")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=0)

    headers = await auth_headers(client, role=ROLE_EQUIPMENT_POOL_STAFF)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 403, r.text


async def test_signoff_post_read_only_forbidden(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="ac")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=0)

    headers = await auth_headers(client, role=ROLE_READ_ONLY)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 403, r.text


async def test_signoff_post_unauthenticated_rejected(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="ad")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=0)

    r = await client.post(f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", json={"expected_version": 0})
    assert r.status_code == 401, r.text


@pytest.mark.parametrize("role", [ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY])
async def test_get_signoff_allowed_for_all_roles(client: AsyncClient, seeded_users, db_session, role):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum=f"ae{role[:2]}")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    headers = await auth_headers(client, role=role)
    r = await client.get(f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers)
    assert r.status_code == 404, r.text  # role permitted through; 404 is the resource-state, not an auth failure


# ---------------------------------------------------------------------------
# F. No business side effects (§47 of the task).
# ---------------------------------------------------------------------------


async def test_signoff_has_no_side_effects_on_other_tables(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="ns")
    authority_id = coverage.migration_authority_id
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, summary_total_findings=1)
    eq = await _seed_equipment(db_session, seed="fx1")
    event = await _seed_legacy_event(db_session, authority_id=authority_id, equipment_id=eq.id, actor_id=actor_id, row_key="row-ns")
    tx = BorrowTransaction(transaction_no=f"TX-{uuid.uuid4().hex[:10]}", equipment_id=eq.id, borrowed_at=_LIVE_START + timedelta(days=1))
    db_session.add(tx)
    await db_session.commit()
    await db_session.refresh(tx)
    finding = await _seed_finding(
        db_session, run_id=run.id, equipment_id=eq.id, disposition="confirmed_valid",
        disposed_by_user_id=actor_id, disposed_at=datetime.now(timezone.utc),
    )

    equipment_before = (eq.status, eq.version)
    tx_before = (tx.status.value, tx.borrowed_at, tx.returned_at, tx.equipment_id)
    event_before = (event.equipment_id, event.event_type, event.occurred_at, event.legacy_source_row_key)
    finding_before = (finding.disposition, finding.disposed_by_user_id, finding.version)
    run_before = (run.status, run.version, run.summary_total_findings)

    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/sign-off", headers=headers, json={"expected_version": 0}
    )
    assert r.status_code == 201, r.text

    await db_session.refresh(eq)
    await db_session.refresh(tx)
    await db_session.refresh(event)
    await db_session.refresh(finding)
    await db_session.refresh(run)

    assert (eq.status, eq.version) == equipment_before
    assert (tx.status.value, tx.borrowed_at, tx.returned_at, tx.equipment_id) == tx_before
    assert (event.equipment_id, event.event_type, event.occurred_at, event.legacy_source_row_key) == event_before
    assert (finding.disposition, finding.disposed_by_user_id, finding.version) == finding_before
    assert (run.status, run.version, run.summary_total_findings) == run_before, "sign-off never bumps run.version"


# ---------------------------------------------------------------------------
# G. Mandatory audit atomicity (§24/§42 of the task).
# ---------------------------------------------------------------------------
#
# Fix Round 1 (P2): the audit-failure-rollback proof for `create_signoff`
# now lives in `test_pr22e_reconciliation_signoff_concurrency.py`
# (`test_signoff_audit_failure_rolls_back_signoff`) instead of here.
# `create_signoff`'s duplicate-sign-off defense (this same fix round)
# now genuinely wraps its `INSERT` in a SAVEPOINT
# (`db.begin_nested()`) -- correct and required for that defense to
# actually isolate a concurrent-duplicate `IntegrityError` under real
# PostgreSQL. Investigating why this SQLite-based test started failing
# after that change traced to a real, pre-existing pysqlite/aiosqlite
# limitation, verified independently of any of this PR's application
# code: this repository's SQLite test engine (`tests/conftest.py`) never
# applies the SQLAlchemy-documented pysqlite recipe (`isolation_level=
# None` at connect + an explicit `BEGIN` via a `"begin"` event listener)
# that real SAVEPOINT/ROLLBACK correctness requires -- pysqlite's own
# legacy DML-detection heuristic does not recognize `RELEASE SAVEPOINT`,
# so a row inserted and released under a SAVEPOINT survives a later
# plain `ROLLBACK` on SQLite specifically (reproduced with a *minimal*
# SQLAlchemy ORM example with zero application code involved). The
# identical sequence against real PostgreSQL rolls back correctly (0
# rows), confirmed directly. Since this property is only ever
# meaningful -- and only ever actually enforced by this application --
# under PostgreSQL (SQLite's own `FOR UPDATE`/concurrency limitations
# already mean every other genuine transaction-semantics proof in this
# suite lives in the PostgreSQL-only file), the test moved there rather
# than staying here asserting a guarantee SQLite's own driver cannot
# reliably provide. Fixing the underlying pysqlite session configuration
# repository-wide is out of this fix round's scope (`app/db/session.py`
# is shared by every other test and would need its own dedicated review).
