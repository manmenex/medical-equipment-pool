"""Roadmap PR23C -- Readiness Gate Evaluation.

Tests `GET /api/v1/cutover-readiness-runs/{run_id}/gate-evaluation`
(`app.api.v1.cutover_readiness`) and
`app.services.cutover_readiness_gates.evaluate_gates`'s contract:
per-gate BLOCKER/WARNING/INFO categorization, the always-present
non-automated Gate A/F warnings, Gate B/C import-completion checks,
Gate D supersession/version-freshness staleness detection, Gate E
structural satisfaction, the `run.status != "completed"` precondition,
and read access for every role.

No mutation exists in this endpoint -- there is no lock-order/race
scenario to prove here, unlike PR23B's own `complete_readiness_run`.
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cutover_readiness import CutoverReadinessRun
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
_TEST_MIGRATION_HEAD = "0099_pr23c_test_migration_head"


@pytest_asyncio.fixture(autouse=True)
async def _seed_alembic_version(db_engine):
    """Same rationale as `test_pr23b_cutover_readiness_api.py`'s own
    identically-named fixture: `alembic_version` is not part of
    `Base.metadata`, so this SQLite test engine needs it seeded
    explicitly before any run can be created, and Gate A's freshness
    re-check needs a known, stable value to compare a completed run's
    own captured evidence against."""
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
    db_session: AsyncSession, *, actor_id: uuid.UUID, seed: str, session_status: str
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


async def _seed_wrong_dataset_source(
    db_session: AsyncSession, *, actor_id: uuid.UUID, seed: str, session_status: str = "completed"
) -> ImportSource:
    """A completed import source whose owning session is NOT an
    Equipment Master import (`legacy_transaction_history` instead) --
    used to prove both Gate B and the PR23B completion boundary reject
    a cross-wired `equipment_master_import_source_id` reference
    (PR23C Fix Round 1)."""
    session = ImportSession(
        dataset_type="legacy_transaction_history", status=session_status, version=0, created_by_user_id=actor_id
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
        scope="pr23c_test", approved_workbook_sha256=_checksum(seed), approved_by_user_id=actor_id
    )
    db_session.add(authority)
    await db_session.commit()
    await db_session.refresh(authority)
    return authority


async def _seed_legacy_history_import(
    db_session: AsyncSession, *, actor_id: uuid.UUID, authority: LegacyMigrationAuthority, session_status: str
) -> None:
    """A completed (or not) `legacy_transaction_history` import whose
    `ImportSource.checksum` matches `authority`'s own approved checksum
    -- Gate C's own evaluation joins on exactly this relationship."""
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
    legacy_history_session_status: str = "completed",
) -> dict:
    """End-to-end: create a run via the API, seed one fully-consistent
    evidence chain, complete the run via the API, and return the
    completed run's own JSON body. Every gate-evaluation test starts
    from a genuinely completed run, exactly as production requires."""
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
    await _seed_legacy_history_import(
        db_session, actor_id=actor_id, authority=authority, session_status=legacy_history_session_status
    )
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


def _items_for_gate(body: dict, gate: str) -> list[dict]:
    return [item for item in body["items"] if item["gate"] == gate]


def _gate_status(body: dict, gate: str) -> str:
    return next(g["status"] for g in body["gates"] if g["gate"] == gate)


# ---------------------------------------------------------------------------
# A. Happy path
# ---------------------------------------------------------------------------


async def test_gate_evaluation_happy_path(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="a")

    resp = await client.get(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/gate-evaluation", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["cutover_readiness_run_id"] == completed["id"]
    assert {g["gate"] for g in body["gates"]} == {"A", "B", "C", "D", "E", "F"}
    assert all(g["mandatory"] is True for g in body["gates"])

    # Gate A/F always carry non-automated manual-attestation warnings --
    # there is no persisted evidence for "CI green"/"staff trained"/etc.
    # -- so they are never reported "satisfied" by this service.
    assert _gate_status(body, "A") == "warning"
    assert _gate_status(body, "F") == "warning"
    assert all(item["manual_attestation_required"] for item in _items_for_gate(body, "A") if item["category"] == "warning")
    assert all(item["manual_attestation_required"] for item in _items_for_gate(body, "F"))

    # Gate A's own migration-head freshness sub-check must still pass
    # (no BLOCKER item) since alembic_version was not mutated.
    assert not any(item["category"] == "blocker" for item in _items_for_gate(body, "A"))

    # Gates B, C, D, E are genuinely satisfied given fully consistent,
    # completed evidence.
    assert _gate_status(body, "B") == "satisfied"
    assert _gate_status(body, "C") == "satisfied"
    assert _gate_status(body, "D") == "satisfied"
    assert _gate_status(body, "E") == "satisfied"

    assert body["has_blocker"] is False


async def test_gate_evaluation_requires_completed_run(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    created = (
        await client.post(
            "/api/v1/cutover-readiness-runs",
            headers=headers,
            json={"application_baseline_sha": _baseline_sha("pending"), "cutover_instant": _CUTOVER_INSTANT.isoformat()},
        )
    ).json()

    resp = await client.get(f"/api/v1/cutover-readiness-runs/{created['id']}/gate-evaluation", headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "CUTOVER_READINESS_GATE_EVALUATION_REQUIRES_COMPLETED_RUN"


async def test_gate_evaluation_not_found(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    resp = await client.get(f"/api/v1/cutover-readiness-runs/{uuid.uuid4()}/gate-evaluation", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "CUTOVER_READINESS_RUN_NOT_FOUND"


@pytest.mark.parametrize("role", ["administrator", "equipment_pool_staff", "read_only"])
async def test_gate_evaluation_readable_by_every_role(client: AsyncClient, seeded_users, db_session, role):
    admin_headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, admin_headers, seed=f"role-{role}")

    headers = await auth_headers(client, role=role)
    resp = await client.get(
        f"/api/v1/cutover-readiness-runs/{completed['id']}/gate-evaluation", headers=headers
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# B. Gate A -- migration head staleness
# ---------------------------------------------------------------------------


async def test_gate_a_blocks_when_migration_head_stale(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="stale-head")

    # Simulate the database having been migrated further since this
    # run's evidence was captured.
    await db_session.execute(text("DELETE FROM alembic_version"))
    await db_session.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": "0100_a_later_head"}
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/gate-evaluation", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _gate_status(body, "A") == "blocker"
    assert any(item["code"] == "GATE_A_MIGRATION_HEAD_STALE" for item in _items_for_gate(body, "A"))
    assert body["has_blocker"] is True


# ---------------------------------------------------------------------------
# C. Gate B -- Equipment Master import completion
# ---------------------------------------------------------------------------


async def test_gate_b_blocks_when_equipment_master_import_not_completed(
    client: AsyncClient, seeded_users, db_session
):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(
        client, db_session, headers, seed="b-not-completed", equipment_master_session_status="dry_run_completed"
    )

    resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/gate-evaluation", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _gate_status(body, "B") == "blocker"
    assert any(item["code"] == "GATE_B_IMPORT_NOT_COMPLETED" for item in _items_for_gate(body, "B"))


# ---------------------------------------------------------------------------
# D. Gate C -- legacy transaction history import completion
# ---------------------------------------------------------------------------


async def test_gate_c_blocks_when_legacy_history_import_not_completed(
    client: AsyncClient, seeded_users, db_session
):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(
        client, db_session, headers, seed="c-not-completed", legacy_history_session_status="failed"
    )

    resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/gate-evaluation", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _gate_status(body, "C") == "blocker"
    assert any(item["code"] == "GATE_C_IMPORT_NOT_COMPLETED" for item in _items_for_gate(body, "C"))


# ---------------------------------------------------------------------------
# E. Gate D -- reconciliation supersession and version freshness
# ---------------------------------------------------------------------------


async def test_gate_d_blocks_when_reconciliation_run_superseded(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="d-superseded")

    governing_run_id = uuid.UUID(completed["reconciliation_run_id"])
    actor_id = await _actor_id(db_session)
    governing_run = (
        await db_session.execute(select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == governing_run_id))
    ).scalar_one()

    newer_run = LegacyReconciliationRun(
        coverage_id=governing_run.coverage_id,
        legacy_coverage_start=governing_run.legacy_coverage_start,
        legacy_coverage_end=governing_run.legacy_coverage_end,
        live_system_start=governing_run.live_system_start,
        rule_version="v1",
        snapshot_as_of=datetime.now(timezone.utc),
        created_by_user_id=actor_id,
        status="completed",
        supersedes_run_id=governing_run_id,
    )
    db_session.add(newer_run)
    await db_session.commit()

    resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/gate-evaluation", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _gate_status(body, "D") == "blocker"
    assert any(item["code"] == "GATE_D_RECONCILIATION_RUN_SUPERSEDED" for item in _items_for_gate(body, "D"))


async def test_gate_d_blocks_when_reconciliation_run_version_mismatches_signoff(
    client: AsyncClient, seeded_users, db_session
):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="d-version-mismatch")

    governing_run_id = uuid.UUID(completed["reconciliation_run_id"])
    await db_session.execute(
        update(LegacyReconciliationRun)
        .where(LegacyReconciliationRun.id == governing_run_id)
        .values(version=LegacyReconciliationRun.version + 1)
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/gate-evaluation", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _gate_status(body, "D") == "blocker"
    assert any(
        item["code"] == "GATE_D_RECONCILIATION_RUN_VERSION_MISMATCH" for item in _items_for_gate(body, "D")
    )


# ---------------------------------------------------------------------------
# F. Gate E -- current-state verification evidence
# ---------------------------------------------------------------------------


async def test_gate_e_satisfied_surfaces_verification_evidence(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    completed = await _create_and_complete_run(client, db_session, headers, seed="e-satisfied")

    resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/gate-evaluation", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _gate_status(body, "E") == "satisfied"
    items = _items_for_gate(body, "E")
    assert len(items) == 1
    assert items[0]["detail"]["current_state_verified_at"] is not None


# ---------------------------------------------------------------------------
# G. Gate B / PR23B completion boundary -- cross-wired Equipment Master
# evidence (PR23C Fix Round 1). `equipment_master_import_source_id` is only
# a UUID reference; its field name does not by itself guarantee the
# referenced ImportSource belongs to an Equipment Master ImportSession. A
# completed source/session for a *different* dataset_type
# (legacy_transaction_history here) must never be accepted as Equipment
# Master evidence, at either the completion boundary or gate-evaluation
# time.
# ---------------------------------------------------------------------------


async def test_complete_run_rejects_wrong_dataset_equipment_master_source(
    client: AsyncClient, seeded_users, db_session
):
    """PR23B's own completion boundary must reject a cross-wired
    equipment_master_import_source_id at capture time -- evidence must be
    valid when captured, not only discovered invalid later by PR23C's
    gate evaluation."""
    headers = await auth_headers(client)
    actor_id = await _actor_id(db_session)
    created = (
        await client.post(
            "/api/v1/cutover-readiness-runs",
            headers=headers,
            json={
                "application_baseline_sha": _baseline_sha("wrong-dataset"),
                "cutover_instant": _CUTOVER_INSTANT.isoformat(),
            },
        )
    ).json()

    wrong_source = await _seed_wrong_dataset_source(db_session, actor_id=actor_id, seed="wrong-dataset")
    authority = await _seed_authority(db_session, actor_id=actor_id, seed="wrong-dataset")
    await _seed_legacy_history_import(
        db_session, actor_id=actor_id, authority=authority, session_status="completed"
    )
    coverage, run, signoff = await _seed_coverage_and_run_and_signoff(
        db_session, actor_id=actor_id, authority=authority
    )

    payload = {
        "expected_version": 0,
        "equipment_master_import_source_id": str(wrong_source.id),
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
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "CUTOVER_READINESS_EVIDENCE_INVALID"
    assert "legacy_transaction_history" in resp.json()["detail"]

    # No partial completion: the run must remain pending and unmutated,
    # never half-advanced by a rejected completion attempt.
    r_detail = await client.get(f"/api/v1/cutover-readiness-runs/{created['id']}", headers=headers)
    assert r_detail.json()["status"] == "pending"
    assert r_detail.json()["version"] == 0
    assert r_detail.json()["equipment_master_import_source_id"] is None


async def test_gate_b_blocks_when_import_source_is_wrong_dataset_type(
    client: AsyncClient, seeded_users, db_session
):
    """Defense-in-depth: even if a cross-wired equipment_master_import_
    source_id somehow reached a completed run (bypassing PR23B's own
    completion-boundary check, e.g. a row inserted directly, or a future
    regression in that check), Gate B must independently detect and
    BLOCKER it -- never report GATE_B_SATISFIED for a non-Equipment-
    Master source. This test fails on reviewed head
    eac9a46c45dbd2c8e66c13486dc6cdd6effe5c6c (Gate B accepted any
    completed session regardless of dataset_type) and passes after the
    fix."""
    headers = await auth_headers(client)
    actor_id = await _actor_id(db_session)
    completed = await _create_and_complete_run(client, db_session, headers, seed="gate-b-cross-wire")

    wrong_source = await _seed_wrong_dataset_source(db_session, actor_id=actor_id, seed="gate-b-cross-wire-src")
    await db_session.execute(
        update(CutoverReadinessRun)
        .where(CutoverReadinessRun.id == uuid.UUID(completed["id"]))
        .values(equipment_master_import_source_id=wrong_source.id)
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/cutover-readiness-runs/{completed['id']}/gate-evaluation", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _gate_status(body, "B") == "blocker"
    b_items = _items_for_gate(body, "B")
    assert any(item["code"] == "GATE_B_WRONG_DATASET_TYPE" for item in b_items)
    assert not any(item["code"] == "GATE_B_SATISFIED" for item in b_items)
    blocker_item = next(item for item in b_items if item["code"] == "GATE_B_WRONG_DATASET_TYPE")
    assert blocker_item["detail"]["expected_dataset_type"] == "equipment_master"
    assert blocker_item["detail"]["actual_dataset_type"] == "legacy_transaction_history"
    assert body["has_blocker"] is True
