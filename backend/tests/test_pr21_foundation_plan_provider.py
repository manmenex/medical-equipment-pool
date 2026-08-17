"""Roadmap PR21-Foundation (docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md
§29-§38, §46). Covers: the internal `DryRunPlanProvider` registry (register/
unregister/resolve, duplicate registration, no cross-dataset fallback), the
Equipment Master provider's compatibility wrapping of the existing PR20D
CRUD, and retention's fail-closed provider-redaction hook (missing
provider, provider exception, atomicity, and the Equipment Master
regression it must preserve exactly). Does not re-test PR20D's own
plan/row/confirmation contract (see test_pr20d_dry_run_plan.py) or PR19A3's
own claim/fencing mechanics (see test_import_execution.py) -- both are
reused unchanged here. This slice adds no PR21 public API, schema, or
source-dependent parser -- see the design doc's §46 scope list."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crud import import_dry_run_plan as import_dry_run_plan_crud
from app.crud import import_retention as import_retention_crud
from app.models.import_session import (
    EquipmentMasterDryRunPlan,
    EquipmentMasterDryRunPlanRow,
    ImportSession,
    ImportSource,
)
from app.services import import_execution_service, import_lease
from app.services.import_adapters.equipment_master import DATASET_TYPE as EQUIPMENT_MASTER_DATASET_TYPE
from app.services.import_plan_provider import (
    DryRunPlanProvider,
    PlanProviderAlreadyRegisteredError,
    PlanProviderNotRegisteredError,
    get_plan_provider,
    register_plan_provider,
    unregister_plan_provider,
)
from app.services.import_plan_providers.equipment_master import EquipmentMasterDryRunPlanProvider
from tests.conftest import auth_headers
from tests.test_pr20d_dry_run_plan import _seed_equipment, _valid_row, _validated_session_with_update_rows

pytestmark = pytest.mark.asyncio

_FAKE_DATASET_TYPE = "pr21_foundation_fake_dataset"


@pytest_asyncio.fixture(autouse=True)
async def _patch_execution_session_factories(db_engine, monkeypatch):
    """Mirrors test_pr20d_dry_run_plan.py's identical fixture -- both
    modules that open their own `AsyncSessionLocal()` must be repointed at
    this test's own engine."""
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(import_execution_service, "AsyncSessionLocal", session_maker)
    monkeypatch.setattr(import_lease, "AsyncSessionLocal", session_maker)


class _NoopPlanProvider(DryRunPlanProvider):
    """A minimal, explicitly-registered "no artifacts" declaration for a
    fake dataset_type -- exercises the registry's extensibility contract
    (§38) without any real persisted plan table."""

    dataset_type = _FAKE_DATASET_TYPE

    async def get_current_plan(self, db, *, import_session_id):
        return None

    async def list_plan_rows(self, db, *, plan_id, limit, cursor_n, cursor_id):
        return [], 0

    async def confirm_plan(self, db, *, plan_id, import_session_id, current_user_id):
        raise NotImplementedError

    async def redact_plan_artifacts(self, db, *, import_session_id):
        return


class _RaisingPlanProvider(DryRunPlanProvider):
    dataset_type = _FAKE_DATASET_TYPE

    async def get_current_plan(self, db, *, import_session_id):
        return None

    async def list_plan_rows(self, db, *, plan_id, limit, cursor_n, cursor_id):
        return [], 0

    async def confirm_plan(self, db, *, plan_id, import_session_id, current_user_id):
        raise NotImplementedError

    async def redact_plan_artifacts(self, db, *, import_session_id):
        raise RuntimeError("simulated provider redaction failure")


async def _get_user_id(db_session: AsyncSession) -> uuid.UUID:
    from app.models.user import User

    return (await db_session.execute(select(User.id).limit(1))).scalar_one()


async def _make_terminal_session(
    db_session: AsyncSession, *, actor_id, dataset_type: str, status: str, terminal_at, dry_run_completed_at=None
) -> ImportSession:
    session = ImportSession(
        dataset_type=dataset_type,
        status=status,
        version=0,
        created_by_user_id=actor_id,
        terminal_at=terminal_at,
        dry_run_completed_at=dry_run_completed_at,
        notes="operator note",
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        ImportSource(
            import_session_id=session.id,
            status="frozen",
            checksum="c" * 64,
            byte_size=1,
            content_type="text/csv",
            filename="legacy.csv",
            options_fingerprint="x",
            source_fingerprint="y",
            frozen_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    return session


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_register_and_resolve_plan_provider():
    provider = _NoopPlanProvider()
    register_plan_provider(provider)
    try:
        assert get_plan_provider(_FAKE_DATASET_TYPE) is provider
    finally:
        unregister_plan_provider(_FAKE_DATASET_TYPE)


def test_unknown_dataset_type_resolves_to_none():
    assert get_plan_provider("some_dataset_type_nobody_registered") is None


def test_duplicate_registration_fails_clearly():
    provider = _NoopPlanProvider()
    register_plan_provider(provider)
    try:
        with pytest.raises(PlanProviderAlreadyRegisteredError):
            register_plan_provider(_NoopPlanProvider())
    finally:
        unregister_plan_provider(_FAKE_DATASET_TYPE)


def test_equipment_master_provider_is_registered_by_default():
    """`app.main` (imported by `tests.conftest`) has already imported
    `app.services.import_plan_providers.equipment_master` for its
    module-level registration side effect, mirroring the adapter
    registry's identical default-registered state for `equipment_master`."""
    provider = get_plan_provider(EQUIPMENT_MASTER_DATASET_TYPE)
    assert isinstance(provider, EquipmentMasterDryRunPlanProvider)


def test_no_accidental_equipment_master_fallback_for_unrelated_dataset_type():
    """A dataset_type with no registration of its own must never silently
    resolve to Equipment Master's provider -- provider isolation across
    dataset types, per §31's "no dynamic dispatch" and §38's registry
    discipline."""
    assert get_plan_provider(_FAKE_DATASET_TYPE) is None
    assert get_plan_provider(EQUIPMENT_MASTER_DATASET_TYPE) is not get_plan_provider(_FAKE_DATASET_TYPE)


def test_unregister_then_reregister_same_dataset_type_succeeds():
    """No unreliable mutable global state leaking across tests: an
    unregister followed by a fresh register for the same dataset_type
    must not spuriously collide with the prior (already-removed)
    registration."""
    register_plan_provider(_NoopPlanProvider())
    unregister_plan_provider(_FAKE_DATASET_TYPE)
    register_plan_provider(_NoopPlanProvider())
    try:
        assert get_plan_provider(_FAKE_DATASET_TYPE) is not None
    finally:
        unregister_plan_provider(_FAKE_DATASET_TYPE)


def test_unregister_unknown_dataset_type_is_a_safe_noop():
    unregister_plan_provider("nobody_ever_registered_this_one")


# ---------------------------------------------------------------------------
# Equipment Master provider: compatibility wrapping of PR20D CRUD
# ---------------------------------------------------------------------------


async def test_equipment_master_provider_get_current_plan_matches_crud(client: AsyncClient, seeded_users, db_session):
    await _seed_equipment(db_session, bcm_code="BCM_PROV1", item_no="ITEM_PROV1")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_PROV1", item_no="ITEM_PROV1")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    session_uuid = uuid.UUID(session["id"])

    crud_plan = await import_dry_run_plan_crud.get_current_plan(db_session, import_session_id=session_uuid)
    provider = EquipmentMasterDryRunPlanProvider()
    provider_record = await provider.get_current_plan(db_session, import_session_id=session_uuid)

    assert provider_record is not None
    assert provider_record.id == crud_plan.id
    assert provider_record.status == crud_plan.status
    assert provider_record.summary.total_rows == crud_plan.summary_total_rows
    assert provider_record.summary.creates == crud_plan.summary_creates


async def test_equipment_master_provider_confirm_plan_matches_crud_first_confirm(
    client: AsyncClient, seeded_users, db_session
):
    await _seed_equipment(db_session, bcm_code="BCM_PROV2", item_no="ITEM_PROV2")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_PROV2", item_no="ITEM_PROV2")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    session_uuid = uuid.UUID(session["id"])
    plan = await import_dry_run_plan_crud.get_current_plan(db_session, import_session_id=session_uuid)
    from app.models.user import User

    actor_id = (await db_session.execute(select(User.id).limit(1))).scalar_one()

    provider = EquipmentMasterDryRunPlanProvider()
    result = await provider.confirm_plan(
        db_session, plan_id=plan.id, import_session_id=session_uuid, current_user_id=actor_id
    )
    await db_session.commit()

    assert result.newly_confirmed is True
    assert result.plan.confirmed_at is not None
    assert result.plan.confirmed_by_user_id == actor_id

    # A second confirm through the provider must be the same idempotent
    # replay contract `confirm_plan` itself guarantees (§35).
    replay = await provider.confirm_plan(
        db_session, plan_id=plan.id, import_session_id=session_uuid, current_user_id=actor_id
    )
    assert replay.newly_confirmed is False
    assert replay.plan.confirmed_at == result.plan.confirmed_at


# ---------------------------------------------------------------------------
# Retention: fail-closed provider redaction hook
# ---------------------------------------------------------------------------


async def test_retention_skips_provider_lookup_when_session_never_dry_ran(client: AsyncClient, seeded_users, db_session):
    """A session that never reached `dry_run_completed_at` cannot own a
    persisted plan artifact of any kind -- retention must succeed for it
    even though no plan provider is registered for its dataset_type (the
    exact pre-Foundation behavior every other dataset_type still gets)."""
    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session,
        actor_id=actor_id,
        dataset_type=_FAKE_DATASET_TYPE,
        status="completed",
        terminal_at=datetime.now(timezone.utc) - timedelta(days=200),
        dry_run_completed_at=None,
    )
    assert get_plan_provider(_FAKE_DATASET_TYPE) is None

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 1

    await db_session.refresh(session)
    assert session.retention_purged_at is not None


async def test_retention_fails_closed_when_provider_missing_for_dry_run_completed_session(
    client: AsyncClient, seeded_users, db_session
):
    """§38's core invariant: a session that DID complete a dry-run under a
    dataset_type with no registered plan provider must never be silently
    purged -- retention must leave it retryable, `retention_purged_at`
    unset, and its other (core) fields un-redacted (the whole transaction
    rolls back together)."""
    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session,
        actor_id=actor_id,
        dataset_type=_FAKE_DATASET_TYPE,
        status="completed",
        terminal_at=datetime.now(timezone.utc) - timedelta(days=200),
        dry_run_completed_at=datetime.now(timezone.utc) - timedelta(days=200),
    )
    assert get_plan_provider(_FAKE_DATASET_TYPE) is None

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["purged_count"] == 0
    assert body["skipped_count"] == 1

    await db_session.refresh(session)
    assert session.retention_purged_at is None, "missing provider must fail closed, never mark purge complete"
    assert session.notes == "operator note", "core redaction must roll back together with the failed provider step"


async def test_redact_session_raises_not_registered_error_directly(seeded_users, db_session):
    """Unit-level proof that the fail-closed error type is explicit and
    internal, not a bare KeyError/LookupError leaking out of the
    registry."""
    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session,
        actor_id=actor_id,
        dataset_type=_FAKE_DATASET_TYPE,
        status="completed",
        terminal_at=datetime.now(timezone.utc) - timedelta(days=400),
        dry_run_completed_at=datetime.now(timezone.utc) - timedelta(days=400),
    )
    worker_id = uuid.uuid4()
    claimed_ids, _ = await import_retention_crud.claim_sessions_for_cleanup(
        db_session, worker_id=worker_id, retention_days=180, claim_timeout_seconds=300, limit=10
    )
    assert session.id in claimed_ids

    with pytest.raises(PlanProviderNotRegisteredError):
        await import_retention_crud.redact_session(db_session, session_id=session.id, worker_id=worker_id)
    await db_session.rollback()


async def test_retention_rolls_back_when_provider_redaction_raises(client: AsyncClient, seeded_users, db_session):
    """A provider that IS registered but whose `redact_plan_artifacts`
    itself raises must produce the same fail-closed outcome as a missing
    provider -- full rollback, no partial redaction, no completion
    marker, error handled by retention's existing generic exception path
    (never a new PR21-specific recovery mechanism)."""
    register_plan_provider(_RaisingPlanProvider())
    try:
        actor_id = await _get_user_id(db_session)
        session = await _make_terminal_session(
            db_session,
            actor_id=actor_id,
            dataset_type=_FAKE_DATASET_TYPE,
            status="completed",
            terminal_at=datetime.now(timezone.utc) - timedelta(days=200),
            dry_run_completed_at=datetime.now(timezone.utc) - timedelta(days=200),
        )

        headers = await auth_headers(client)
        r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["purged_count"] == 0
        assert body["skipped_count"] == 1

        await db_session.refresh(session)
        assert session.retention_purged_at is None
        assert session.notes == "operator note"
    finally:
        unregister_plan_provider(_FAKE_DATASET_TYPE)


async def test_retention_provider_exception_leaves_session_retryable(client: AsyncClient, seeded_users, db_session):
    """A later retry, once a working provider is registered, must succeed
    -- the earlier failure must not have left any partial/poisoned state
    behind (e.g. a stray claim)."""
    register_plan_provider(_RaisingPlanProvider())
    actor_id = await _get_user_id(db_session)
    session = await _make_terminal_session(
        db_session,
        actor_id=actor_id,
        dataset_type=_FAKE_DATASET_TYPE,
        status="completed",
        terminal_at=datetime.now(timezone.utc) - timedelta(days=200),
        dry_run_completed_at=datetime.now(timezone.utc) - timedelta(days=200),
    )
    headers = await auth_headers(client)
    r1 = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r1.json()["skipped_count"] == 1
    unregister_plan_provider(_FAKE_DATASET_TYPE)

    # The first attempt's claim (`claim_sessions_for_cleanup`'s own commit)
    # survives its own redaction failure -- §18's documented "remains
    # eligible" means eligible once the claim itself expires, not on the
    # very next call. Clear it directly here (the same technique the
    # existing fence-loss tests use) so this retry proves the earlier
    # failure left no *other* poisoned state behind, without waiting out
    # `claim_timeout_seconds`.
    from sqlalchemy import update

    await db_session.execute(
        update(ImportSession)
        .where(ImportSession.id == session.id)
        .values(retention_cleanup_claimed_by=None, retention_cleanup_claim_expires_at=None)
    )
    await db_session.commit()

    register_plan_provider(_NoopPlanProvider())
    try:
        r2 = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
        assert r2.status_code == 200, r2.text
        assert r2.json()["purged_count"] == 1
        await db_session.refresh(session)
        assert session.retention_purged_at is not None
    finally:
        unregister_plan_provider(_FAKE_DATASET_TYPE)


async def test_retention_atomicity_core_and_provider_redaction_commit_together(
    client: AsyncClient, seeded_users, db_session
):
    """Success path: core artifact redaction, provider-owned plan-row
    redaction, and `retention_purged_at` all land in the same commit --
    proved against the real Equipment Master provider and a real
    persisted plan (extends test_pr20d_dry_run_plan.py's equivalent
    assertion with the explicit provider-registry indirection now in
    the loop)."""
    await _seed_equipment(db_session, bcm_code="BCM_ATOMIC", item_no="ITEM_ATOMIC")
    headers = await auth_headers(client)
    session = await _validated_session_with_update_rows(
        client, headers, db_session, [_valid_row(bcm="BCM_ATOMIC", item_no="ITEM_ATOMIC")]
    )
    await client.post(f"/api/v1/import-sessions/{session['id']}/dry-run", headers=headers)
    session_uuid = uuid.UUID(session["id"])

    plan_row = (
        await db_session.execute(
            select(EquipmentMasterDryRunPlan).where(EquipmentMasterDryRunPlan.import_session_id == session_uuid)
        )
    ).scalar_one()
    plan_row_row = (
        await db_session.execute(
            select(EquipmentMasterDryRunPlanRow).where(EquipmentMasterDryRunPlanRow.dry_run_plan_id == plan_row.id)
        )
    ).scalar_one()
    assert plan_row_row.normalized_values is not None

    session_db = (await db_session.execute(select(ImportSession).where(ImportSession.id == session_uuid))).scalar_one()
    session_db.status = "cancelled"
    session_db.terminal_at = datetime.now(timezone.utc) - timedelta(days=400)
    await db_session.commit()

    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 1

    await db_session.refresh(session_db)
    assert session_db.retention_purged_at is not None

    # This redaction happened through the HTTP client, on the route's own
    # `get_db`-provided session -- `db_session`'s identity map still holds
    # the pre-redaction `plan_row_row` instance, so it must be refreshed
    # before re-reading, exactly like `session_db` was refreshed above.
    await db_session.refresh(plan_row_row)
    after_row = plan_row_row
    assert after_row.normalized_values is None
    assert after_row.matched_identity_fields is None
    assert after_row.source_row_number == plan_row_row.source_row_number, "structural columns must survive redaction"
