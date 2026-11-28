"""Roadmap PR23B -- Cutover Readiness Evidence Foundation.

Tests `POST/GET /api/v1/cutover-readiness-runs`,
`GET /api/v1/cutover-readiness-runs/{run_id}`, and
`POST /api/v1/cutover-readiness-runs/{run_id}/complete`
(`app.api.v1.cutover_readiness`) and
`app.crud.cutover_readiness`'s contract: creation, evidence-reference
validation (existence, sign-off/run pairing, `cutover_instant` vs.
`live_system_start`), CAS version conflict, immutability after
completion, authorization, and mandatory audit write.

Genuine two-connection lock-order/race proofs are out of scope for this
slice -- unlike PR22D/E, `complete_readiness_run` is the only write path
against a `CutoverReadinessRun` row after creation (no second concurrent
mutation path to race against), so the `SELECT ... FOR UPDATE` lock's
own purpose (excluding two concurrent completion attempts against the
same run) is already exercised by the version-conflict tests below
against the SQLite test engine's own serialized-writes behavior; a
dedicated PostgreSQL two-connection file is not required to prove it.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.import_session import ImportSession, ImportSource
from app.models.legacy_history import LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)
from app.models.master_data import Ward
from app.models.user import User
from tests.conftest import auth_headers

_COVERAGE_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
_COVERAGE_END = datetime(2024, 12, 31, tzinfo=timezone.utc)
_LIVE_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
_CUTOVER_INSTANT = datetime(2025, 1, 5, tzinfo=timezone.utc)
# PR23B Fix Round 1: a value distinct from any real revision id, so a
# test asserting the API response equals this proves the value came
# from `alembic_version` (seeded by `_seed_alembic_version` below), not
# from a coincidentally-matching hardcoded string.
_TEST_MIGRATION_HEAD = "0099_test_migration_head"


@pytest_asyncio.fixture(autouse=True)
async def _seed_alembic_version(db_engine):
    """PR23B Fix Round 1: `create_readiness_run` reads
    `database_migration_head` server-side from `alembic_version`
    (`app.crud.cutover_readiness._get_current_database_migration_head`)
    -- never from the request body. `alembic_version` is Alembic's own
    bookkeeping table, not part of `Base.metadata`, so it is never
    created by `db_engine`'s `Base.metadata.create_all()`; this fixture
    seeds it explicitly (exactly one row, mirroring what a real
    migrated database looks like) before any test in this module
    creates a run. Runs against `db_engine` directly (not `db_session`)
    so it lands before the test body regardless of `db_session`/
    `client` fixture instantiation order -- SQLite's `StaticPool` here
    means every session in a test shares one physical connection, so a
    write committed here is immediately visible to all of them."""
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


async def _seed_import_source(db_session: AsyncSession, *, actor_id: uuid.UUID, seed: str) -> ImportSource:
    session = ImportSession(dataset_type="equipment_master", status="created", version=0, created_by_user_id=actor_id)
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


async def _seed_coverage_and_run_and_signoff(
    db_session: AsyncSession, *, actor_id: uuid.UUID, seed: str
) -> tuple[LegacyMigrationAuthority, LegacyMigrationAuthorityCoverage, LegacyReconciliationRun, LegacyReconciliationSignOff]:
    authority = LegacyMigrationAuthority(
        scope="pr23b_api_test", approved_workbook_sha256=_checksum(seed), approved_by_user_id=actor_id
    )
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
    await db_session.refresh(authority)
    await db_session.refresh(coverage)
    await db_session.refresh(run)
    await db_session.refresh(signoff)
    return authority, coverage, run, signoff


def _complete_payload(*, source, authority, coverage, run, signoff, actor_id, **overrides) -> dict:
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
    payload.update(overrides)
    return payload


async def _create_run(client: AsyncClient, headers: dict, *, seed: str) -> dict:
    resp = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=headers,
        json={
            "application_baseline_sha": _baseline_sha(seed),
            "cutover_instant": _CUTOVER_INSTANT.isoformat(),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# A. Creation
# ---------------------------------------------------------------------------


async def test_create_run_happy_path(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    body = await _create_run(client, headers, seed="a")
    assert body["status"] == "pending"
    assert body["version"] == 0
    assert body["source_of_truth_strategy"] == "hard_cutover"
    assert body["equipment_master_import_source_id"] is None
    # PR23B Fix Round 1: proves the value came from the database's own
    # `alembic_version` (seeded by `_seed_alembic_version` to
    # `_TEST_MIGRATION_HEAD`), not from any client-supplied value --
    # the request body sent by `_create_run` never includes this field.
    assert body["database_migration_head"] == _TEST_MIGRATION_HEAD

    log = (
        await db_session.execute(select(AuditLog).where(AuditLog.entity_id == uuid.UUID(body["id"])))
    ).scalar_one()
    assert log.action == "cutover_readiness_run_created"
    assert log.after_data["database_migration_head"] == _TEST_MIGRATION_HEAD


async def test_create_run_rejects_short_baseline_sha(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    resp = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=headers,
        json={
            "application_baseline_sha": "tooshort",
            "cutover_instant": _CUTOVER_INSTANT.isoformat(),
        },
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("role", ["equipment_pool_staff", "read_only"])
async def test_create_run_denied_for_non_administrator(client: AsyncClient, seeded_users, role):
    headers = await auth_headers(client, role=role)
    resp = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=headers,
        json={
            "application_baseline_sha": _baseline_sha("z"),
            "cutover_instant": _CUTOVER_INSTANT.isoformat(),
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# B. Read surfaces
# ---------------------------------------------------------------------------


async def test_list_and_get_run(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    created = await _create_run(client, headers, seed="b")

    r_list = await client.get("/api/v1/cutover-readiness-runs", headers=headers)
    assert r_list.status_code == 200
    assert any(item["id"] == created["id"] for item in r_list.json()["items"])

    r_detail = await client.get(f"/api/v1/cutover-readiness-runs/{created['id']}", headers=headers)
    assert r_detail.status_code == 200
    assert r_detail.json()["id"] == created["id"]


async def test_get_run_not_found(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    resp = await client.get(f"/api/v1/cutover-readiness-runs/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "CUTOVER_READINESS_RUN_NOT_FOUND"


@pytest.mark.parametrize("role", ["administrator", "equipment_pool_staff", "read_only"])
async def test_list_readable_by_every_role(client: AsyncClient, seeded_users, role):
    headers = await auth_headers(client, role=role)
    resp = await client.get("/api/v1/cutover-readiness-runs", headers=headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# C. Completion -- happy path
# ---------------------------------------------------------------------------


async def test_complete_run_happy_path(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    created = await _create_run(client, headers, seed="c")

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="c")
    authority, coverage, run, signoff = await _seed_coverage_and_run_and_signoff(db_session, actor_id=actor_id, seed="c")

    payload = _complete_payload(source=source, authority=authority, coverage=coverage, run=run, signoff=signoff, actor_id=actor_id)
    resp = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["version"] == 1
    assert body["equipment_master_import_source_id"] == str(source.id)
    assert body["reconciliation_signoff_id"] == str(signoff.id)

    log = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_id == uuid.UUID(created["id"]), AuditLog.action == "cutover_readiness_run_completed"
            )
        )
    ).scalar_one()
    assert log is not None


async def test_complete_run_with_pilot_ward(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    created = await _create_run(client, headers, seed="pw")

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="pw")
    authority, coverage, run, signoff = await _seed_coverage_and_run_and_signoff(db_session, actor_id=actor_id, seed="pw")
    ward = Ward(code="PR23B-API-WARD", name="PR23B API Ward")
    db_session.add(ward)
    await db_session.commit()
    await db_session.refresh(ward)

    payload = _complete_payload(
        source=source, authority=authority, coverage=coverage, run=run, signoff=signoff, actor_id=actor_id,
        pilot_ward_id=str(ward.id),
    )
    resp = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["pilot_ward_id"] == str(ward.id)


# ---------------------------------------------------------------------------
# D. Completion -- evidence validation failures
# ---------------------------------------------------------------------------


async def test_complete_run_rejects_missing_import_source(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    created = await _create_run(client, headers, seed="d1")

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="d1")
    authority, coverage, run, signoff = await _seed_coverage_and_run_and_signoff(db_session, actor_id=actor_id, seed="d1")

    payload = _complete_payload(
        source=source, authority=authority, coverage=coverage, run=run, signoff=signoff, actor_id=actor_id,
        equipment_master_import_source_id=str(uuid.uuid4()),
    )
    resp = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == "CUTOVER_READINESS_EVIDENCE_INVALID"


async def test_complete_run_rejects_signoff_not_belonging_to_run(client: AsyncClient, seeded_users, db_session):
    """Isolates the sign-off/run pairing check specifically: authority,
    coverage, and reconciliation run are all one mutually-consistent
    chain ("a") -- only the sign-off is swapped for one belonging to an
    unrelated run ("b"), so this fails exactly the pre-existing
    `signoff.run_id == reconciliation_run_id` check, not either of the
    newer PR23B Fix Round 1 provenance checks (which this fixture setup
    does not violate)."""
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    created = await _create_run(client, headers, seed="d2")

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="d2a")
    authority_a, coverage_a, run_a, _signoff_a = await _seed_coverage_and_run_and_signoff(
        db_session, actor_id=actor_id, seed="d2a"
    )
    _authority_b, _coverage_b, _run_b, signoff_b = await _seed_coverage_and_run_and_signoff(
        db_session, actor_id=actor_id, seed="d2b"
    )

    payload = _complete_payload(
        source=source, authority=authority_a, coverage=coverage_a, run=run_a, signoff=signoff_b, actor_id=actor_id
    )
    resp = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == "CUTOVER_READINESS_EVIDENCE_INVALID"
    assert "sign-off" in resp.json()["detail"] or "signoff" in resp.json()["detail"]


async def test_complete_run_rejects_cutover_instant_before_live_system_start(
    client: AsyncClient, seeded_users, db_session
):
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    resp_create = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=await auth_headers(client),
        json={
            "application_baseline_sha": _baseline_sha("early"),
            # Earlier than the coverage's live_system_start (2025-01-01)
            "cutover_instant": (_LIVE_START - timedelta(days=10)).isoformat(),
        },
    )
    assert resp_create.status_code == 201
    created = resp_create.json()

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="early")
    authority, coverage, run, signoff = await _seed_coverage_and_run_and_signoff(db_session, actor_id=actor_id, seed="early")

    payload = _complete_payload(source=source, authority=authority, coverage=coverage, run=run, signoff=signoff, actor_id=actor_id)
    resp = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == "CUTOVER_READINESS_EVIDENCE_INVALID"
    assert "live_system_start" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# E. Completion -- version conflict / immutability
# ---------------------------------------------------------------------------


async def test_complete_run_version_conflict(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    created = await _create_run(client, headers, seed="e")

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="e")
    authority, coverage, run, signoff = await _seed_coverage_and_run_and_signoff(db_session, actor_id=actor_id, seed="e")

    payload = _complete_payload(
        source=source, authority=authority, coverage=coverage, run=run, signoff=signoff, actor_id=actor_id,
        expected_version=99,
    )
    resp = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp.status_code == 409
    assert resp.json()["code"] == "CUTOVER_READINESS_RUN_VERSION_CONFLICT"


async def test_complete_run_twice_rejected_as_not_mutable(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    created = await _create_run(client, headers, seed="f")

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="f")
    authority, coverage, run, signoff = await _seed_coverage_and_run_and_signoff(db_session, actor_id=actor_id, seed="f")

    payload = _complete_payload(source=source, authority=authority, coverage=coverage, run=run, signoff=signoff, actor_id=actor_id)
    resp1 = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp1.status_code == 200, resp1.text

    payload2 = dict(payload)
    payload2["expected_version"] = 1
    resp2 = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload2)
    assert resp2.status_code == 409
    assert resp2.json()["code"] == "CUTOVER_READINESS_RUN_NOT_MUTABLE"


async def test_complete_run_not_found(client: AsyncClient, seeded_users, db_session):
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    source = await _seed_import_source(db_session, actor_id=actor_id, seed="g")
    authority, coverage, run, signoff = await _seed_coverage_and_run_and_signoff(db_session, actor_id=actor_id, seed="g")
    payload = _complete_payload(source=source, authority=authority, coverage=coverage, run=run, signoff=signoff, actor_id=actor_id)

    resp = await client.post(f"/api/v1/cutover-readiness-runs/{uuid.uuid4()}/complete", headers=headers, json=payload)
    assert resp.status_code == 404
    assert resp.json()["code"] == "CUTOVER_READINESS_RUN_NOT_FOUND"


@pytest.mark.parametrize("role", ["equipment_pool_staff", "read_only"])
async def test_complete_run_denied_for_non_administrator(client: AsyncClient, seeded_users, db_session, role):
    actor_id = await _actor_id(db_session)
    admin_headers = await auth_headers(client)
    created = await _create_run(client, admin_headers, seed="h")

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="h")
    authority, coverage, run, signoff = await _seed_coverage_and_run_and_signoff(db_session, actor_id=actor_id, seed="h")
    payload = _complete_payload(source=source, authority=authority, coverage=coverage, run=run, signoff=signoff, actor_id=actor_id)

    headers = await auth_headers(client, role=role)
    resp = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# F. Supersession
# ---------------------------------------------------------------------------


async def test_create_run_with_supersedes_run_id(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    prior = await _create_run(client, headers, seed="i1")
    resp = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=headers,
        json={
            "application_baseline_sha": _baseline_sha("i2"),
            "cutover_instant": _CUTOVER_INSTANT.isoformat(),
            "supersedes_run_id": prior["id"],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["supersedes_run_id"] == prior["id"]


async def test_create_run_with_unknown_supersedes_run_id_rejected(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    resp = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=headers,
        json={
            "application_baseline_sha": _baseline_sha("i3"),
            "cutover_instant": _CUTOVER_INSTANT.isoformat(),
            "supersedes_run_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# G. Migration head server-derivation (PR23B Fix Round 1)
# ---------------------------------------------------------------------------


async def test_create_run_rejects_client_supplied_migration_head(client: AsyncClient, seeded_users):
    """`database_migration_head` is not a field on `RunCreateRequest` at
    all -- `model_config = {"extra": "forbid"}` means a caller sending
    it anyway gets a hard 422, never a silently-ignored field and never
    a chance for the value to reach `CutoverReadinessRun` unvalidated."""
    headers = await auth_headers(client)
    resp = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=headers,
        json={
            "application_baseline_sha": _baseline_sha("spoof"),
            "database_migration_head": "attacker-supplied-fake-head",
            "cutover_instant": _CUTOVER_INSTANT.isoformat(),
        },
    )
    assert resp.status_code == 422


async def test_create_run_migration_head_fails_closed_when_zero_rows(
    client: AsyncClient, seeded_users, db_session
):
    """`alembic_version` exists but is empty (never migrated) -- fails
    closed rather than creating a run with a missing/guessed migration
    head."""
    headers = await auth_headers(client)
    await db_session.execute(text("DELETE FROM alembic_version"))
    await db_session.commit()

    resp = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=headers,
        json={
            "application_baseline_sha": _baseline_sha("zero"),
            "cutover_instant": _CUTOVER_INSTANT.isoformat(),
        },
    )
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "CUTOVER_READINESS_DATABASE_MIGRATION_HEAD_UNAVAILABLE"


async def test_create_run_migration_head_fails_closed_when_multiple_rows(
    client: AsyncClient, seeded_users, db_session
):
    """`alembic_version` has more than one row -- a multi-head state
    this repository's migration policy does not support. Fails closed
    rather than silently picking an arbitrary row."""
    headers = await auth_headers(client)
    await db_session.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": "another_head"})
    await db_session.commit()

    resp = await client.post(
        "/api/v1/cutover-readiness-runs",
        headers=headers,
        json={
            "application_baseline_sha": _baseline_sha("multi"),
            "cutover_instant": _CUTOVER_INSTANT.isoformat(),
        },
    )
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "CUTOVER_READINESS_DATABASE_MIGRATION_HEAD_UNAVAILABLE"


# ---------------------------------------------------------------------------
# H. Completion -- evidence provenance-chain binding (PR23B Fix Round 1)
# ---------------------------------------------------------------------------


async def test_complete_run_rejects_coverage_from_different_authority(
    client: AsyncClient, seeded_users, db_session
):
    """Authority A + Coverage B, where Coverage B actually belongs to
    Authority B -- both ids independently resolve to real rows, but
    they do not form one consistent provenance chain. Existence-only
    validation would have accepted this; the chain check must not."""
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    created = await _create_run(client, headers, seed="j1")

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="j1")
    authority_a, _coverage_a, run_a, signoff_a = await _seed_coverage_and_run_and_signoff(
        db_session, actor_id=actor_id, seed="j1a"
    )
    _authority_b, coverage_b, _run_b, _signoff_b = await _seed_coverage_and_run_and_signoff(
        db_session, actor_id=actor_id, seed="j1b"
    )

    payload = _complete_payload(
        source=source, authority=authority_a, coverage=coverage_b, run=run_a, signoff=signoff_a, actor_id=actor_id
    )
    resp = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "CUTOVER_READINESS_EVIDENCE_INVALID"
    assert "migration authority" in resp.json()["detail"]

    # No partial completion: the run must remain pending and unmutated,
    # never half-advanced by a rejected completion attempt.
    r_detail = await client.get(f"/api/v1/cutover-readiness-runs/{created['id']}", headers=headers)
    assert r_detail.json()["status"] == "pending"
    assert r_detail.json()["version"] == 0
    assert r_detail.json()["legacy_coverage_id"] is None


async def test_complete_run_rejects_reconciliation_run_from_different_coverage(
    client: AsyncClient, seeded_users, db_session
):
    """Coverage A + ReconciliationRun B, where Run B is actually bound
    to Coverage B -- both ids independently resolve to real rows, but
    they do not form one consistent provenance chain."""
    actor_id = await _actor_id(db_session)
    headers = await auth_headers(client)
    created = await _create_run(client, headers, seed="j2")

    source = await _seed_import_source(db_session, actor_id=actor_id, seed="j2")
    authority_a, coverage_a, _run_a, _signoff_a = await _seed_coverage_and_run_and_signoff(
        db_session, actor_id=actor_id, seed="j2a"
    )
    _authority_b, _coverage_b, run_b, signoff_b = await _seed_coverage_and_run_and_signoff(
        db_session, actor_id=actor_id, seed="j2b"
    )

    payload = _complete_payload(
        source=source, authority=authority_a, coverage=coverage_a, run=run_b, signoff=signoff_b, actor_id=actor_id
    )
    resp = await client.post(f"/api/v1/cutover-readiness-runs/{created['id']}/complete", headers=headers, json=payload)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "CUTOVER_READINESS_EVIDENCE_INVALID"
    assert "coverage" in resp.json()["detail"]

    r_detail = await client.get(f"/api/v1/cutover-readiness-runs/{created['id']}", headers=headers)
    assert r_detail.json()["status"] == "pending"
    assert r_detail.json()["version"] == 0
    assert r_detail.json()["reconciliation_run_id"] is None
    assert resp.json()["code"] == "CUTOVER_READINESS_EVIDENCE_INVALID"
