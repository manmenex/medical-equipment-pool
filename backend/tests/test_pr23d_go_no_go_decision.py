"""Roadmap PR23D -- Go/No-Go Decision + Current-State Re-Issue Support.

Tests `POST/GET /api/v1/cutover-readiness-runs/{run_id}/decision`
(`app.api.v1.cutover_readiness`) and `app.crud.cutover_readiness.
create_go_no_go_decision`'s own contract: Administrator-only mutation,
broad read access, fresh Gate A-F re-evaluation at decision time (never
trusting an earlier `GET .../gate-evaluation` response), BLOCKER
rejection for `GO`, WARNING-acknowledgement coverage for `GO`, `NO_GO`
never gated by readiness, run-status/version/supersession preconditions,
duplicate-decision rejection, and audit-write atomicity.

No current-state re-issue write endpoint exists in this module (see
`app.api.v1.cutover_readiness`'s own module docstring) -- the existing
`POST /borrow` issue workflow is reused unchanged, so there is no
additional write surface to test here.
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.cutover_readiness import CutoverGoNoGoDecision, CutoverReadinessRun
from app.models.import_session import ImportSession, ImportSource
from app.models.legacy_history import LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)
from app.models.user import User
from tests.conftest import auth_headers

_COVERAGE_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
_COVERAGE_END = datetime(2024, 12, 31, tzinfo=timezone.utc)
_LIVE_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
_CUTOVER_INSTANT = datetime(2025, 1, 5, tzinfo=timezone.utc)
_TEST_MIGRATION_HEAD = "0099_pr23d_test_migration_head"


@pytest_asyncio.fixture(autouse=True)
async def _seed_alembic_version(db_engine):
    """Same rationale as `test_pr23b_cutover_readiness_api.py`/
    `test_pr23c_readiness_gate_evaluation.py`'s own identically-named
    fixture: `alembic_version` is not part of `Base.metadata`, so this
    SQLite test engine needs it seeded explicitly, and Gate A's own
    freshness re-check (reused unchanged by PR23D's fresh evaluation)
    needs a known, stable value."""
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        await conn.execute(text("DELETE FROM alembic_version"))
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": _TEST_MIGRATION_HEAD}
        )


async def _actor_id(db_session: AsyncSession) -> uuid.UUID:
    return (await db_session.execute(select(User.id).where(User.employee_code == "ADMINISTRATOR001"))).scalar_one()


def _checksum(seed: str) -> str:
    return (seed * 64)[:64]


def _baseline_sha(seed: str) -> str:
    return (seed * 40)[:40]


async def _seed_equipment_master_source(
    db_session: AsyncSession, *, actor_id: uuid.UUID, seed: str, session_status: str = "completed"
) -> ImportSource:
    session = ImportSession(
        dataset_type="equipment_master", status=session_status, version=0, created_by_user_id=actor_id
    )
    db_session.add(session)
    await db_session.flush()
    source = ImportSource(
        import_session_id=session.id,
        status="registered",
        checksum=_checksum(seed),
        byte_size=10,
        options_fingerprint="x",
        source_fingerprint="y",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    return source


async def _seed_authority(db_session: AsyncSession, *, actor_id: uuid.UUID, seed: str) -> LegacyMigrationAuthority:
    authority = LegacyMigrationAuthority(
        scope="pr23d_test", approved_workbook_sha256=_checksum(seed), approved_by_user_id=actor_id
    )
    db_session.add(authority)
    await db_session.commit()
    await db_session.refresh(authority)
    return authority


async def _seed_legacy_history_import(
    db_session: AsyncSession, *, actor_id: uuid.UUID, authority: LegacyMigrationAuthority, session_status: str = "completed"
) -> None:
    session = ImportSession(
        dataset_type="legacy_transaction_history", status=session_status, version=0, created_by_user_id=actor_id
    )
    db_session.add(session)
    await db_session.flush()
    source = ImportSource(
        import_session_id=session.id,
        status="registered",
        checksum=authority.approved_workbook_sha256,
        byte_size=10,
        options_fingerprint="x",
        source_fingerprint="y",
    )
    db_session.add(source)
    await db_session.commit()


async def _seed_coverage_and_run_and_signoff(
    db_session: AsyncSession, *, actor_id: uuid.UUID, authority: LegacyMigrationAuthority
) -> tuple[LegacyMigrationAuthorityCoverage, LegacyReconciliationRun, LegacyReconciliationSignOff]:
    coverage = LegacyMigrationAuthorityCoverage(
        migration_authority_id=authority.id,
        legacy_coverage_start=_COVERAGE_START,
        legacy_coverage_end=_COVERAGE_END,
        live_system_start=_LIVE_START,
        approval_basis="explicit_administrator_approval",
        approved_by_user_id=actor_id,
    )
    db_session.add(coverage)
    await db_session.flush()
    run = LegacyReconciliationRun(
        coverage_id=coverage.id,
        legacy_coverage_start=coverage.legacy_coverage_start,
        legacy_coverage_end=coverage.legacy_coverage_end,
        live_system_start=coverage.live_system_start,
        rule_version="v1",
        snapshot_as_of=datetime.now(timezone.utc),
        created_by_user_id=actor_id,
        status="completed",
    )
    db_session.add(run)
    await db_session.flush()
    signoff = LegacyReconciliationSignOff(
        run_id=run.id,
        signed_off_by_user_id=actor_id,
        attestation_summary={"run_id": str(run.id)},
        run_version_at_signoff=run.version,
    )
    db_session.add(signoff)
    await db_session.commit()
    await db_session.refresh(coverage)
    await db_session.refresh(run)
    await db_session.refresh(signoff)
    return coverage, run, signoff


async def _create_and_complete_run(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict,
    *,
    seed: str,
    equipment_master_session_status: str = "completed",
) -> dict:
    """End-to-end: create a run via the API, seed one fully-consistent
    evidence chain, complete the run via the API, and return the
    completed run's own JSON body -- exactly the same helper shape as
    `test_pr23c_readiness_gate_evaluation.py`'s own, duplicated locally
    per this repository's established test-file convention."""
    actor_id = await _actor_id(db_session)
    created = (
        await client.post(
            "/api/v1/cutover-readiness-runs",
            headers=headers,
            json={"application_baseline_sha": _baseline_sha(seed), "cutover_instant": _CUTOVER_INSTANT.isoformat()},
        )
    ).json()

    source = await _seed_equipment_master_source(
        db_session, actor_id=actor_id, seed=seed, session_status=equipment_master_session_status
    )
    authority = await _seed_authority(db_session, actor_id=actor_id, seed=seed)
    await _seed_legacy_history_import(db_session, actor_id=actor_id, authority=authority)
    coverage, run, signoff = await _seed_coverage_and_run_and_signoff(db_session, actor_id=actor_id, authority=authority)

    payload = {
        "expected_version": 0,
        "equipment_master_import_source_id": str(source.id),
        "legacy_migration_authority_id": str(authority.id),
        "legacy_coverage_id": str(coverage.id),
        "reconciliation_run_id": str(run.id),
        "reconciliation_signoff_id": str(signoff.id),
        "current_state_verified_at": datetime.now(timezone.utc).isoformat(),
        "current_state_verified_by_user_id": str(actor_id),
    }
    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _live_warning_codes(client: AsyncClient, headers: dict, run_id: str) -> list[str]:
    resp = await client.get(f"/api/v1/cutover-readiness-runs/{run_id}/gate-evaluation", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return sorted({item["code"] for item in body["items"] if item["category"] == "warning"})


# ---------------------------------------------------------------------------
# A/B. Happy path -- GO and NO_GO
# ---------------------------------------------------------------------------


async def test_administrator_can_record_go_when_no_blocker_and_warnings_acknowledged(
    client: AsyncClient, seeded_users, db_session
):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="go-happy")
    warning_codes = await _live_warning_codes(client, headers, completed["id"])

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "GO", "acknowledged_warning_codes": warning_codes},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["decision"] == "GO"
    assert body["cutover_readiness_run_id"] == completed["id"]
    assert body["run_version_at_decision"] == completed["version"]
    assert sorted(body["acknowledged_warning_codes"]) == warning_codes
    assert body["no_go_reason"] is None
    assert uuid.UUID(body["id"])
    assert uuid.UUID(body["recorded_by_user_id"])


async def test_administrator_can_record_no_go(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="no-go-happy")

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "NO_GO", "no_go_reason": "Pilot Ward not yet ready."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["decision"] == "NO_GO"
    assert body["acknowledged_warning_codes"] == []
    assert body["no_go_reason"] == "Pilot Ward not yet ready."


# ---------------------------------------------------------------------------
# C/D/E. Authorization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["equipment_pool_staff", "read_only"])
async def test_non_administrator_cannot_post_decision(client: AsyncClient, seeded_users, db_session, role):
    admin_headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, admin_headers, seed=f"authz-{role}")

    headers = await auth_headers(client, role=role)
    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "NO_GO"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("role", ["administrator", "equipment_pool_staff", "read_only"])
async def test_decision_readable_by_every_role(client: AsyncClient, seeded_users, db_session, role):
    admin_headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, admin_headers, seed=f"read-{role}")
    await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=admin_headers,
        json={"expected_version": completed["version"], "decision": "NO_GO"},
    )

    headers = await auth_headers(client, role=role)
    resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/decision", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"] == "NO_GO"


async def test_get_decision_not_found_when_none_recorded(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="get-not-found")

    resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/decision", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "CUTOVER_DECISION_NOT_FOUND"


async def test_get_decision_run_not_found(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    resp = await client.get(f"/api/v1/cutover-readiness-runs/{uuid.uuid4()}/decision", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "CUTOVER_READINESS_RUN_NOT_FOUND"


# ---------------------------------------------------------------------------
# F. GO rejected when a fresh BLOCKER exists
# ---------------------------------------------------------------------------


async def test_go_rejected_when_fresh_blocker_exists(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="go-blocked")

    # Simulate the database having been migrated further since this
    # run's evidence was captured -- Gate A now returns a fresh BLOCKER.
    await db_session.execute(text("DELETE FROM alembic_version"))
    await db_session.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": "0100_a_later_head"}
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "GO"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "CUTOVER_DECISION_BLOCKED_BY_READINESS"

    # No decision was persisted for the rejected attempt.
    get_resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/decision", headers=headers)
    assert get_resp.status_code == 404


async def test_no_go_not_blocked_by_fresh_blocker(client: AsyncClient, seeded_users, db_session):
    """§13/§27 of the task: NO_GO never requires readiness success."""
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="no-go-despite-blocker")

    await db_session.execute(text("DELETE FROM alembic_version"))
    await db_session.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": "0100_a_later_head"}
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "NO_GO"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["decision"] == "NO_GO"


# ---------------------------------------------------------------------------
# G/H. GO rejected when warning acknowledgement missing or stale
# ---------------------------------------------------------------------------


async def test_go_rejected_when_warning_acknowledgement_missing(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="go-warnings-missing")

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "GO", "acknowledged_warning_codes": []},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "CUTOVER_DECISION_WARNINGS_NOT_ACKNOWLEDGED"


async def test_go_rejected_when_acknowledged_codes_are_stale(client: AsyncClient, seeded_users, db_session):
    """A client-supplied acknowledgement of codes that are not among the
    *currently-live* warnings must never satisfy the acknowledgement
    requirement -- proves a stale/unknown code cannot be used to bypass
    the fresh evaluation (§10 of the task)."""
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="go-warnings-stale")

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={
            "expected_version": completed["version"],
            "decision": "GO",
            "acknowledged_warning_codes": ["THIS_CODE_DOES_NOT_EXIST", "NEITHER_DOES_THIS_ONE"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "CUTOVER_DECISION_WARNINGS_NOT_ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# I/J/K/L. Preconditions
# ---------------------------------------------------------------------------


async def test_stale_expected_version_rejected(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="stale-version")

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": 999, "decision": "NO_GO"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "CUTOVER_DECISION_STALE_VERSION"


async def test_non_completed_run_rejected(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    created = (
        await client.post(
            "/api/v1/cutover-readiness-runs",
            headers=headers,
            json={"application_baseline_sha": _baseline_sha("pending"), "cutover_instant": _CUTOVER_INSTANT.isoformat()},
        )
    ).json()

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{created['id']}/decision",
        headers=headers,
        json={"expected_version": 0, "decision": "NO_GO"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "CUTOVER_DECISION_REQUIRES_COMPLETED_RUN"


async def test_superseded_run_rejected(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="superseded")

    newer = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=headers,
        json={
            "application_baseline_sha": _baseline_sha("superseded-2"),
            "cutover_instant": _CUTOVER_INSTANT.isoformat(),
            "supersedes_run_id": completed["id"],
        },
    )
    assert newer.status_code == 201, newer.text

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "NO_GO"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "CUTOVER_DECISION_RUN_SUPERSEDED"


async def test_duplicate_decision_rejected(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="duplicate")

    first = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "NO_GO"},
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "NO_GO"},
    )
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "CUTOVER_DECISION_ALREADY_EXISTS"


async def test_run_not_found(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{uuid.uuid4()}/decision",
        headers=headers,
        json={"expected_version": 0, "decision": "NO_GO"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "CUTOVER_READINESS_RUN_NOT_FOUND"


# ---------------------------------------------------------------------------
# N. Audit written atomically
# ---------------------------------------------------------------------------


async def test_decision_audit_written(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="audit")

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "NO_GO", "no_go_reason": "test"},
    )
    assert resp.status_code == 201, resp.text
    decision_id = uuid.UUID(resp.json()["id"])

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "cutover_go_no_go_decision", AuditLog.entity_id == decision_id
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 1
    assert audit_rows[0].action == "cutover_go_no_go_decision_recorded"


async def test_rejected_decision_writes_no_audit_row(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="audit-rejected")

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": 999, "decision": "NO_GO"},
    )
    assert resp.status_code == 409

    audit_rows = (
        await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "cutover_go_no_go_decision"))
    ).scalars().all()
    assert audit_rows == []


# ---------------------------------------------------------------------------
# Decision-value domain -- closed vocabulary, extra fields forbidden
# ---------------------------------------------------------------------------


async def test_decision_value_rejects_unknown_string(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="bad-value")

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "APPROVED"},
    )
    assert resp.status_code == 422


async def test_decision_request_forbids_extra_fields(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="extra-field")

    resp = await client.post(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/decision",
        headers=headers,
        json={"expected_version": completed["version"], "decision": "NO_GO", "recorded_by_user_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 422
