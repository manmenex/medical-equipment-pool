"""Roadmap PR22D -- Finding Review / Disposition API.

Tests `GET/PATCH /api/v1/legacy-reconciliation-runs`/`legacy-
reconciliation-findings` (`app.api.v1.legacy_reconciliation`) and
`app.crud.legacy_reconciliation`'s disposition-mutation contract:
authorization, the closed four-value disposition domain, CAS/version
freshness, run-status/signed-off gating, and mandatory audit semantics.

The genuine two-connection lock-order/race proof (Run row locked before
the sign-off check, so a concurrent sign-off-style writer following the
same lock order can never interleave) is proved against real PostgreSQL
in `test_pr22d_finding_review_concurrency.py` instead of here, mirroring
this repository's own established convention (see
`test_pr21e0_legacy_migration_authority_api.py`'s identical note) that
every genuine concurrency proof lives in the PostgreSQL-only suite, not
the SQLite one this file's `client`/`db_session` fixtures use.
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
    LegacyReconciliationFindingEvent,
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
    # Always exactly 64 hex characters (ck_legacy_migration_authorities_
    # checksum_length) regardless of `seed`'s own length -- avoids fragile
    # manual `* N` arithmetic at every call site.
    return hashlib.sha256(seed.encode()).hexdigest()


async def _seed_coverage(db_session: AsyncSession, *, actor_id: uuid.UUID, checksum: str) -> LegacyMigrationAuthorityCoverage:
    authority = LegacyMigrationAuthority(scope="pr22d_test", approved_workbook_sha256=_checksum(checksum), approved_by_user_id=actor_id)
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
    )
    defaults.update(overrides)
    run = LegacyReconciliationRun(**defaults)
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


async def _seed_equipment(db_session: AsyncSession, *, seed: str) -> Equipment:
    eq = Equipment(asset_number=f"AN-{seed}", equipment_name="PR22D Test Equipment", status=EquipmentStatus.AVAILABLE_AT_POOL)
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    return eq


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


async def _seed_signoff(db_session: AsyncSession, *, run: LegacyReconciliationRun, actor_id: uuid.UUID) -> LegacyReconciliationSignOff:
    signoff = LegacyReconciliationSignOff(
        run_id=run.id, signed_off_by_user_id=actor_id, attestation_summary={"note": "test"},
        run_version_at_signoff=run.version,
    )
    db_session.add(signoff)
    await db_session.commit()
    await db_session.refresh(signoff)
    return signoff


# ---------------------------------------------------------------------------
# A. Read APIs -- run list/detail, finding list/detail, pagination, filters.
# ---------------------------------------------------------------------------


async def test_run_list_pagination_deterministic_order(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="a")
    # Explicit, strictly increasing created_at -- SQLite's CURRENT_TIMESTAMP
    # default is second-resolution, so three rows seeded in the same test
    # can otherwise tie and fall back to an id-based tiebreak whose order
    # (a random UUID) has no relationship to insertion order.
    base = datetime.now(timezone.utc)
    runs = [
        await _seed_run(db_session, coverage=coverage, actor_id=actor_id, created_at=base + timedelta(seconds=i))
        for i in range(3)
    ]

    headers = await auth_headers(client)
    r1 = await client.get("/api/v1/legacy-reconciliation-runs", headers=headers, params={"limit": 2})
    assert r1.status_code == 200, r1.text
    page1 = r1.json()
    assert len(page1["items"]) == 2
    assert page1["total"] == 3
    assert page1["next_cursor"] is not None
    # Newest created_at first.
    assert page1["items"][0]["id"] == str(runs[2].id)
    assert page1["items"][1]["id"] == str(runs[1].id)

    r2 = await client.get(
        "/api/v1/legacy-reconciliation-runs", headers=headers, params={"limit": 2, "cursor": page1["next_cursor"]}
    )
    assert r2.status_code == 200, r2.text
    page2 = r2.json()
    assert len(page2["items"]) == 1
    assert page2["items"][0]["id"] == str(runs[0].id)
    assert page2["next_cursor"] is None


async def test_run_detail_200(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="b")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    await _seed_finding(db_session, run_id=run.id, code="SOURCE_PROVENANCE", severity="high")
    await _seed_finding(db_session, run_id=run.id, code="WARD_TRACEABILITY_GAP", severity="low")

    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-reconciliation-runs/{run.id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(run.id)
    assert body["coverage_id"] == str(coverage.id)
    assert body["has_signoff"] is False
    assert body["finding_counts_by_disposition"]["open"] == 2


async def test_run_detail_404(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-reconciliation-runs/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "RECONCILIATION_RUN_NOT_FOUND"


async def test_run_detail_reflects_signoff(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="c")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    await _seed_signoff(db_session, run=run, actor_id=actor_id)

    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-reconciliation-runs/{run.id}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["has_signoff"] is True


async def test_finding_list_pagination(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="d")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    # Explicit, strictly increasing created_at -- same tie-avoidance
    # rationale as test_run_list_pagination_deterministic_order above.
    base = datetime.now(timezone.utc)
    findings = [
        await _seed_finding(db_session, run_id=run.id, created_at=base + timedelta(seconds=i)) for i in range(3)
    ]

    headers = await auth_headers(client)
    r1 = await client.get(f"/api/v1/legacy-reconciliation-runs/{run.id}/findings", headers=headers, params={"limit": 2})
    assert r1.status_code == 200, r1.text
    page1 = r1.json()
    assert len(page1["items"]) == 2
    assert page1["total"] == 3
    # Oldest-first.
    assert page1["items"][0]["id"] == str(findings[0].id)
    assert page1["items"][1]["id"] == str(findings[1].id)

    r2 = await client.get(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/findings",
        headers=headers, params={"limit": 2, "cursor": page1["next_cursor"]},
    )
    page2 = r2.json()
    assert len(page2["items"]) == 1
    assert page2["items"][0]["id"] == str(findings[2].id)


async def test_finding_list_run_not_found(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-reconciliation-runs/{uuid.uuid4()}/findings", headers=headers)
    assert r.status_code == 404, r.text


async def test_finding_list_filter_by_code(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="e")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    target = await _seed_finding(db_session, run_id=run.id, code="DUPLICATE_EXACT")
    await _seed_finding(db_session, run_id=run.id, code="SOURCE_PROVENANCE")

    headers = await auth_headers(client)
    r = await client.get(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/findings", headers=headers, params={"code": "DUPLICATE_EXACT"}
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(target.id)


async def test_finding_list_filter_by_severity(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="f")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    target = await _seed_finding(db_session, run_id=run.id, severity="low")
    await _seed_finding(db_session, run_id=run.id, severity="high")

    headers = await auth_headers(client)
    r = await client.get(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/findings", headers=headers, params={"severity": "low"}
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(target.id)


async def test_finding_list_filter_invalid_severity_rejected(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="1")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    headers = await auth_headers(client)
    r = await client.get(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/findings", headers=headers, params={"severity": "critical"}
    )
    assert r.status_code == 400, r.text


@pytest.mark.parametrize(
    "disposition", ["confirmed_valid", "confirmed_duplicate", "accepted_unresolved", "requires_correction"]
)
async def test_finding_list_filter_by_each_disposition(client: AsyncClient, seeded_users, db_session, disposition):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum=f"{disposition[:1]}2")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    target = await _seed_finding(
        db_session, run_id=run.id, disposition=disposition, disposed_by_user_id=actor_id, disposed_at=datetime.now(timezone.utc)
    )
    await _seed_finding(db_session, run_id=run.id)  # open, undisposed

    headers = await auth_headers(client)
    r = await client.get(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/findings", headers=headers, params={"disposition": disposition}
    )
    body = r.json()
    assert body["total"] == 1, body
    assert body["items"][0]["id"] == str(target.id)


async def test_finding_list_filter_open_disposition(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="3")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    open_finding = await _seed_finding(db_session, run_id=run.id)
    await _seed_finding(
        db_session, run_id=run.id, disposition="confirmed_valid", disposed_by_user_id=actor_id,
        disposed_at=datetime.now(timezone.utc),
    )

    headers = await auth_headers(client)
    r = await client.get(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/findings", headers=headers, params={"disposition": "open"}
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(open_finding.id)


async def test_finding_list_filter_by_equipment_id(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="4")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    eq = await _seed_equipment(db_session, seed="fx1")
    target = await _seed_finding(db_session, run_id=run.id, equipment_id=eq.id)
    await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r = await client.get(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/findings", headers=headers, params={"equipment_id": str(eq.id)}
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(target.id)


async def test_finding_list_combined_filters(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="5")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    eq = await _seed_equipment(db_session, seed="fx2")
    target = await _seed_finding(db_session, run_id=run.id, code="DUPLICATE_EXACT", severity="high", equipment_id=eq.id)
    await _seed_finding(db_session, run_id=run.id, code="DUPLICATE_EXACT", severity="low", equipment_id=eq.id)

    headers = await auth_headers(client)
    r = await client.get(
        f"/api/v1/legacy-reconciliation-runs/{run.id}/findings", headers=headers,
        params={"code": "DUPLICATE_EXACT", "severity": "high", "equipment_id": str(eq.id)},
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(target.id)


async def test_finding_detail_200(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="6")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    eq = await _seed_equipment(db_session, seed="fx3")
    finding = await _seed_finding(db_session, run_id=run.id, equipment_id=eq.id, evidence={"reason_code": "no_source_ref"})

    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-reconciliation-findings/{finding.id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(finding.id)
    assert body["evidence"] == {"reason_code": "no_source_ref"}
    assert body["equipment"]["id"] == str(eq.id)
    assert body["equipment"]["asset_number"] == eq.asset_number


async def test_finding_detail_404(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-reconciliation-findings/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404, r.text


async def test_finding_detail_linked_event_refs(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="7")
    authority_id = coverage.migration_authority_id
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    eq = await _seed_equipment(db_session, seed="fx4")
    event = await _seed_legacy_event(db_session, authority_id=authority_id, equipment_id=eq.id, actor_id=actor_id, row_key="row-x")
    finding = await _seed_finding(db_session, run_id=run.id, equipment_id=eq.id)
    db_session.add(LegacyReconciliationFindingEvent(finding_id=finding.id, legacy_equipment_event_id=event.id))
    await db_session.commit()

    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-reconciliation-findings/{finding.id}", headers=headers)
    body = r.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["id"] == str(event.id)
    assert body["events"][0]["legacy_source_row_key"] == "row-x"


# ---------------------------------------------------------------------------
# B. Authorization.
# ---------------------------------------------------------------------------


async def test_disposition_patch_admin_allowed(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="8")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client, role=ROLE_ADMINISTRATOR)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r.status_code == 200, r.text


async def test_disposition_patch_equipment_pool_staff_forbidden(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="9")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client, role=ROLE_EQUIPMENT_POOL_STAFF)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r.status_code == 403, r.text


async def test_disposition_patch_read_only_forbidden(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="a1")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client, role=ROLE_READ_ONLY)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r.status_code == 403, r.text


async def test_disposition_patch_unauthenticated_rejected(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="a2")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r.status_code == 401, r.text


@pytest.mark.parametrize("role", [ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY])
async def test_read_endpoints_allowed_for_all_roles(client: AsyncClient, seeded_users, db_session, role):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum=f"r{role[:2]}")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    headers = await auth_headers(client, role=role)
    r1 = await client.get("/api/v1/legacy-reconciliation-runs", headers=headers)
    assert r1.status_code == 200, r1.text
    r2 = await client.get(f"/api/v1/legacy-reconciliation-runs/{run.id}", headers=headers)
    assert r2.status_code == 200, r2.text
    r3 = await client.get(f"/api/v1/legacy-reconciliation-runs/{run.id}/findings", headers=headers)
    assert r3.status_code == 200, r3.text


# ---------------------------------------------------------------------------
# C. Disposition domain.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disposition", ["confirmed_valid", "confirmed_duplicate", "accepted_unresolved", "requires_correction"]
)
async def test_disposition_all_four_values_accepted(client: AsyncClient, seeded_users, db_session, disposition):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum=f"d{disposition[:1]}")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": disposition, "expected_version": 0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["disposition"] == disposition


async def test_disposition_fifth_value_confirmed_pair_rejected(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="cp")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id, code="PAIRING_CANDIDATE")

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_pair", "expected_version": 0},
    )
    assert r.status_code == 422, r.text


async def test_disposition_arbitrary_value_rejected(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="ar")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "ignored", "expected_version": 0},
    )
    assert r.status_code == 422, r.text


async def test_pairing_candidate_may_be_confirmed_valid(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="pv")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id, code="PAIRING_CANDIDATE", severity="low")

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["disposition"] == "confirmed_valid"


async def test_disposition_note_over_length_rejected(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="nl")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers,
        json={"disposition": "confirmed_valid", "expected_version": 0, "disposition_note": "x" * 4001},
    )
    assert r.status_code == 422, r.text


async def test_disposition_patch_cannot_mutate_immutable_fields(client: AsyncClient, seeded_users, db_session):
    """§17 of the task: only disposition/expected_version/disposition_note
    are ever accepted -- extra fields are silently ignored by Pydantic
    (no generic update schema), never applied to the row."""
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="im")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id, code="SOURCE_PROVENANCE", severity="high")

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers,
        json={
            "disposition": "confirmed_valid", "expected_version": 0,
            "code": "HACKED", "severity": "low", "rule_version": "hacked-v1", "run_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "SOURCE_PROVENANCE"
    assert body["severity"] == "high"
    assert body["run_id"] == str(run.id)


# ---------------------------------------------------------------------------
# D. CAS / freshness.
# ---------------------------------------------------------------------------


async def test_cas_version_0_succeeds_then_version_1(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="c0")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r1 = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["version"] == 1


async def test_cas_stale_expected_version_conflict(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="c1")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r1 = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r1.status_code == 200, r1.text

    # Same stale expected_version=0 retried.
    r2 = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "accepted_unresolved", "expected_version": 0},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["code"] == "RECONCILIATION_FINDING_VERSION_CONFLICT"


async def test_cas_fresh_expected_version_succeeds(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="c2")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r1 = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r1.status_code == 200, r1.text

    r2 = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "accepted_unresolved", "expected_version": 1},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["version"] == 2
    assert r2.json()["disposition"] == "accepted_unresolved"


# ---------------------------------------------------------------------------
# E. Signed-run immutability (§14/§15/§31 of the task).
# ---------------------------------------------------------------------------


async def test_disposition_rejected_when_run_signed_off(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="so")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)
    await _seed_signoff(db_session, run=run, actor_id=actor_id)

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RECONCILIATION_FINDING_SIGNED_OFF"

    await db_session.refresh(finding)
    assert finding.disposition is None
    assert finding.version == 0

    audit_rows = (
        await db_session.execute(select(AuditLog).where(AuditLog.entity_id == finding.id))
    ).scalars().all()
    assert audit_rows == [], "no audit record for a rejected signed-run mutation"


# ---------------------------------------------------------------------------
# F. Run-status gate (§34 of the task).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
async def test_disposition_rejected_for_non_completed_run(client: AsyncClient, seeded_users, db_session, status):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum=f"s{status[:1]}")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status=status)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RECONCILIATION_FINDING_RUN_NOT_COMPLETED"


# ---------------------------------------------------------------------------
# G. Audit.
# ---------------------------------------------------------------------------


async def test_successful_disposition_writes_exactly_one_audit_event(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="au")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0, "disposition_note": "looks right"},
    )
    assert r.status_code == 200, r.text

    audit_rows = (
        await db_session.execute(select(AuditLog).where(AuditLog.entity_id == finding.id))
    ).scalars().all()
    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.action == "reconciliation_finding_disposed"
    assert row.entity_type == "reconciliation_finding"
    assert row.before_data["disposition"] is None
    assert row.before_data["version"] == 0
    assert row.after_data["disposition"] == "confirmed_valid"
    assert row.after_data["version"] == 1
    assert row.after_data["disposition_note"] == "looks right"


async def test_stale_version_rejection_writes_no_audit(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="na")
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = await _seed_finding(db_session, run_id=run.id)

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 99},
    )
    assert r.status_code == 409, r.text

    audit_rows = (
        await db_session.execute(select(AuditLog).where(AuditLog.entity_id == finding.id))
    ).scalars().all()
    assert audit_rows == []


# ---------------------------------------------------------------------------
# H. No business side effects (§33 of the task).
# ---------------------------------------------------------------------------


async def test_disposition_patch_has_no_side_effects_on_other_tables(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    coverage = await _seed_coverage(db_session, actor_id=actor_id, checksum="ns")
    authority_id = coverage.migration_authority_id
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    eq = await _seed_equipment(db_session, seed="fx5")
    event = await _seed_legacy_event(db_session, authority_id=authority_id, equipment_id=eq.id, actor_id=actor_id, row_key="row-ns")
    tx = BorrowTransaction(transaction_no=f"TX-{uuid.uuid4().hex[:10]}", equipment_id=eq.id, borrowed_at=_LIVE_START + timedelta(days=1))
    db_session.add(tx)
    await db_session.commit()
    await db_session.refresh(tx)
    finding = await _seed_finding(db_session, run_id=run.id, equipment_id=eq.id)

    equipment_before = (eq.status, eq.version)
    tx_before = (tx.status.value, tx.borrowed_at, tx.returned_at, tx.equipment_id)
    event_before = (event.equipment_id, event.event_type, event.occurred_at, event.legacy_source_row_key)
    run_before = (run.status, run.version, run.summary_total_findings)

    headers = await auth_headers(client)
    r = await client.patch(
        f"/api/v1/legacy-reconciliation-findings/{finding.id}/disposition",
        headers=headers, json={"disposition": "confirmed_valid", "expected_version": 0},
    )
    assert r.status_code == 200, r.text

    await db_session.refresh(eq)
    await db_session.refresh(tx)
    await db_session.refresh(event)
    await db_session.refresh(run)

    assert (eq.status, eq.version) == equipment_before
    assert (tx.status.value, tx.borrowed_at, tx.returned_at, tx.equipment_id) == tx_before
    assert (event.equipment_id, event.event_type, event.occurred_at, event.legacy_source_row_key) == event_before
    assert (run.status, run.version, run.summary_total_findings) == run_before
