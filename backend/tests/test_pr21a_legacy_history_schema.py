"""Roadmap PR21A (docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md
§8.1, §14, §24.2, §36) -- Historical Event Schema / Provenance
Foundation. Covers: `LegacyMigrationAuthority`'s immutable checksum
binding and distinctness from `ImportSource`; `LegacyEquipmentEvent`'s
database-enforced identity (`migration_authority_id`, `event_type`,
`legacy_source_row_key`) including the Issue/Receive collision-boundary
regression the design's own §24.2 fix round required; `event_type`
domain enforcement; `equipment_id` requirement and no lifecycle
mutation; `LegacyEquipmentEventSourceRef`'s 1:N provenance; Ward-alias
uniqueness/FK integrity (OD-PR21-4); the PR21 plan provider's retention
integration (temporary plan-row content redacted, permanent
`LegacyEquipmentEvent`/`SourceRef` rows untouched, fail-closed behavior
inherited unchanged from PR21-Foundation); and a real, PostgreSQL-only
migration upgrade/downgrade/re-upgrade round trip for `0019_legacy_
history_foundation.py`.

Does not implement, and does not test, any parser/validation logic
(PR21B/C's own job) or execution (PR21D's own job) -- no adapter exists
yet, so `insert_plan`/`bulk_insert_plan_rows` are exercised directly
here, the same way PR21-Foundation's own provider abstraction was
tested before any concrete PR21 provider existed."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ImportDryRunPlanNotFoundError, ImportDryRunPlanStaleError
from app.crud import legacy_history_dry_run_plan as legacy_history_dry_run_plan_crud
from app.models.equipment import Equipment, EquipmentStatus
from app.models.import_session import ImportSession, ImportSource
from app.models.legacy_history import (
    PR21_V1_APPROVED_WORKBOOK_SHA256,
    LegacyEquipmentEvent,
    LegacyEquipmentEventSourceRef,
    LegacyHistoryDryRunPlan,
    LegacyHistoryDryRunPlanRow,
    LegacyMigrationAuthority,
    LegacyWardAlias,
)
from app.models.master_data import Ward
from app.models.user import User
from app.services.import_plan_provider import get_plan_provider
from app.services.import_plan_providers.legacy_history import DATASET_TYPE, LegacyHistoryDryRunPlanProvider
from tests.conftest import auth_headers

# No module-level `pytestmark = pytest.mark.asyncio` -- `pytest.ini` sets
# `asyncio_mode = auto`, so every `async def test_*` here is already
# collected as an asyncio test without a marker; a blanket marker would
# incorrectly also tag this module's one synchronous test.


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


async def _get_user_id(db_session: AsyncSession) -> uuid.UUID:
    return (await db_session.execute(select(User.id).limit(1))).scalar_one()


async def _seed_equipment(db_session: AsyncSession, **kwargs) -> Equipment:
    defaults = dict(
        asset_number=f"AN-{uuid.uuid4().hex[:10]}",
        equipment_name="Legacy Test Equipment",
        status=EquipmentStatus.AVAILABLE_AT_POOL,
    )
    defaults.update(kwargs)
    eq = Equipment(**defaults)
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    return eq


async def _seed_ward(db_session: AsyncSession, code: str = "W1") -> Ward:
    ward = Ward(code=code, name=f"Ward {code}")
    db_session.add(ward)
    await db_session.commit()
    await db_session.refresh(ward)
    return ward


async def _seed_import_session_and_source(db_session: AsyncSession, *, actor_id: uuid.UUID, checksum: str) -> tuple[ImportSession, ImportSource]:
    session = ImportSession(dataset_type=DATASET_TYPE, status="dry_run_completed", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    source = ImportSource(
        import_session_id=session.id,
        status="frozen",
        checksum=checksum,
        byte_size=1,
        content_type="application/vnd.ms-excel",
        filename="legacy_workbook.xlsx",
        options_fingerprint="x",
        source_fingerprint="y",
        frozen_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(session)
    await db_session.refresh(source)
    return session, source


async def _seed_authority(
    db_session: AsyncSession, *, actor_id: uuid.UUID, checksum: str = PR21_V1_APPROVED_WORKBOOK_SHA256, scope: str = "pr21_legacy_transaction_history_v1"
) -> LegacyMigrationAuthority:
    authority = LegacyMigrationAuthority(scope=scope, approved_workbook_sha256=checksum, approved_by_user_id=actor_id)
    db_session.add(authority)
    await db_session.commit()
    await db_session.refresh(authority)
    return authority


def _make_event(
    *,
    authority_id: uuid.UUID,
    equipment_id: uuid.UUID,
    import_session_id: uuid.UUID,
    import_source_id: uuid.UUID,
    event_type: str = "ISSUE",
    row_key: str = "abc12345",
) -> LegacyEquipmentEvent:
    return LegacyEquipmentEvent(
        migration_authority_id=authority_id,
        equipment_id=equipment_id,
        event_type=event_type,
        occurred_at=datetime.now(timezone.utc),
        legacy_source_row_key=row_key,
        import_session_id=import_session_id,
        import_source_id=import_source_id,
    )


# ---------------------------------------------------------------------------
# A. LegacyMigrationAuthority
# ---------------------------------------------------------------------------


async def test_authority_persists_approved_checksum(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    assert authority.approved_workbook_sha256 == PR21_V1_APPROVED_WORKBOOK_SHA256
    assert authority.approved_at is not None
    assert authority.created_at is not None


async def test_authority_checksum_is_unique(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    await _seed_authority(db_session, actor_id=actor_id, checksum="a" * 64, scope="first")
    db_session.add(LegacyMigrationAuthority(scope="second", approved_workbook_sha256="a" * 64, approved_by_user_id=actor_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_authority_checksum_length_enforced(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(LegacyMigrationAuthority(scope="bad", approved_workbook_sha256="tooshort", approved_by_user_id=actor_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_authority_is_a_distinct_identity_from_import_source(db_session: AsyncSession, seeded_users):
    """§24.2: a same-file retry creates a NEW `ImportSource` row but must
    be able to reuse the SAME `LegacyMigrationAuthority` -- proving the
    two identities are independently addressable, never conflated."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session_1, source_1 = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    session_2, source_2 = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)

    assert source_1.id != source_2.id
    assert source_1.checksum == source_2.checksum == authority.approved_workbook_sha256

    equipment = await _seed_equipment(db_session)
    event_1 = _make_event(
        authority_id=authority.id,
        equipment_id=equipment.id,
        import_session_id=session_1.id,
        import_source_id=source_1.id,
        row_key="key0001",
    )
    db_session.add(event_1)
    await db_session.commit()

    # A retried upload (session_2/source_2) referencing a DIFFERENT
    # source row key under the SAME authority succeeds -- both technical
    # artifacts legitimately feed the one governance identity.
    event_2 = _make_event(
        authority_id=authority.id,
        equipment_id=equipment.id,
        import_session_id=session_2.id,
        import_source_id=source_2.id,
        row_key="key0002",
    )
    db_session.add(event_2)
    await db_session.commit()
    assert event_1.migration_authority_id == event_2.migration_authority_id == authority.id


# ---------------------------------------------------------------------------
# B. Event identity -- database-enforced, migration-authority-scoped
# ---------------------------------------------------------------------------


async def test_same_authority_same_type_same_key_collides(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    db_session.add(
        _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, event_type="ISSUE", row_key="dup0001")
    )
    await db_session.commit()

    db_session.add(
        _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, event_type="ISSUE", row_key="dup0001")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_issue_and_receive_with_the_same_row_key_do_not_collide(db_session: AsyncSession, seeded_users):
    """The exact regression this module's own docstring on
    `uq_legacy_equipment_events_identity` promises: `ลำดับ` values were
    independently verified unique only *within* each sheet (§24) -- an
    Issue row and a Receive row may legitimately carry the identical raw
    key text without being the same historical event. `event_type`
    fulfilling the design's `dataset_type` tuple role must keep these
    apart."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    db_session.add(
        _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, event_type="ISSUE", row_key="shared01")
    )
    db_session.add(
        _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, event_type="RECEIVE", row_key="shared01")
    )
    await db_session.commit()

    rows = (
        await db_session.execute(select(LegacyEquipmentEvent).where(LegacyEquipmentEvent.legacy_source_row_key == "shared01"))
    ).scalars().all()
    assert {r.event_type for r in rows} == {"ISSUE", "RECEIVE"}


async def test_different_authority_same_type_same_key_does_not_collide(db_session: AsyncSession, seeded_users):
    """§24.2: `legacy_source_row_key` is never claimed unique or durable
    outside its owning authority -- two independently-approved
    authorities may legitimately share a raw key value."""
    actor_id = await _get_user_id(db_session)
    authority_1 = await _seed_authority(db_session, actor_id=actor_id, checksum="1" * 64, scope="authority-one")
    authority_2 = await _seed_authority(db_session, actor_id=actor_id, checksum="2" * 64, scope="authority-two")
    session_1, source_1 = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority_1.approved_workbook_sha256)
    session_2, source_2 = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority_2.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    db_session.add(
        _make_event(authority_id=authority_1.id, equipment_id=equipment.id, import_session_id=session_1.id, import_source_id=source_1.id, row_key="cross0001")
    )
    db_session.add(
        _make_event(authority_id=authority_2.id, equipment_id=equipment.id, import_session_id=session_2.id, import_source_id=source_2.id, row_key="cross0001")
    )
    await db_session.commit()

    rows = (
        await db_session.execute(select(LegacyEquipmentEvent).where(LegacyEquipmentEvent.legacy_source_row_key == "cross0001"))
    ).scalars().all()
    assert len(rows) == 2
    assert {r.migration_authority_id for r in rows} == {authority_1.id, authority_2.id}


async def test_source_row_key_alone_is_not_globally_unique(db_session: AsyncSession, seeded_users):
    """Direct proof that no accidental global-uniqueness constraint
    exists on `legacy_source_row_key` by itself -- three rows sharing the
    same raw key text (different authority, different event_type, and
    the earlier authority-distinct case) all coexist successfully."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    db_session.add(
        _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, event_type="ISSUE", row_key="notunique")
    )
    db_session.add(
        _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, event_type="RECEIVE", row_key="notunique")
    )
    await db_session.commit()

    count = len(
        (await db_session.execute(select(LegacyEquipmentEvent).where(LegacyEquipmentEvent.legacy_source_row_key == "notunique"))).scalars().all()
    )
    assert count == 2


# ---------------------------------------------------------------------------
# C/D. event_type domain + equipment requirement
# ---------------------------------------------------------------------------


async def test_event_type_issue_and_receive_accepted(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    for event_type, key in (("ISSUE", "type0001"), ("RECEIVE", "type0002")):
        db_session.add(
            _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, event_type=event_type, row_key=key)
        )
    await db_session.commit()


async def test_event_type_invalid_value_rejected(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    db_session.add(
        _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, event_type="BOGUS", row_key="bad0001")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_equipment_id_is_required(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)

    event = LegacyEquipmentEvent(
        migration_authority_id=authority.id,
        equipment_id=None,
        event_type="ISSUE",
        occurred_at=datetime.now(timezone.utc),
        legacy_source_row_key="noequip1",
        import_session_id=session.id,
        import_source_id=source.id,
    )
    db_session.add(event)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_event_does_not_mutate_equipment_status_or_version(db_session: AsyncSession, seeded_users):
    """§3/§19/§44's invariant, proved directly: inserting a
    `LegacyEquipmentEvent` for a piece of equipment never touches that
    equipment's own row at all."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session, status=EquipmentStatus.AVAILABLE_AT_POOL)
    version_before, status_before = equipment.version, equipment.status

    db_session.add(
        _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="nomutate")
    )
    await db_session.commit()

    await db_session.refresh(equipment)
    assert equipment.version == version_before
    assert equipment.status == status_before


# ---------------------------------------------------------------------------
# F. Provenance -- LegacyEquipmentEventSourceRef
# ---------------------------------------------------------------------------


async def test_one_event_supports_multiple_source_refs(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    event = _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="tworefs1")
    db_session.add(event)
    await db_session.flush()

    header_ref = LegacyEquipmentEventSourceRef(
        legacy_equipment_event_id=event.id,
        import_session_id=session.id,
        import_source_id=source.id,
        source_checksum=source.checksum,
        sheet_name="Orders ยืมเครื่อง",
        source_row_number=10,
    )
    line_item_ref = LegacyEquipmentEventSourceRef(
        legacy_equipment_event_id=event.id,
        import_session_id=session.id,
        import_source_id=source.id,
        source_checksum=source.checksum,
        sheet_name="ข้อมูลส่งเครื่องมือ",
        source_row_number=42,
    )
    db_session.add_all([header_ref, line_item_ref])
    await db_session.commit()

    refs = (
        await db_session.execute(select(LegacyEquipmentEventSourceRef).where(LegacyEquipmentEventSourceRef.legacy_equipment_event_id == event.id))
    ).scalars().all()
    assert len(refs) == 2
    assert {r.sheet_name for r in refs} == {"Orders ยืมเครื่อง", "ข้อมูลส่งเครื่องมือ"}


async def test_source_ref_binds_to_the_correct_event_only(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    event_a = _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="eventA01")
    event_b = _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="eventB01")
    db_session.add_all([event_a, event_b])
    await db_session.flush()

    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event_a.id,
            import_session_id=session.id,
            import_source_id=source.id,
            source_checksum=source.checksum,
            sheet_name="Orders ยืมเครื่อง",
            source_row_number=1,
        )
    )
    await db_session.commit()

    refs_for_b = (
        await db_session.execute(select(LegacyEquipmentEventSourceRef).where(LegacyEquipmentEventSourceRef.legacy_equipment_event_id == event_b.id))
    ).scalars().all()
    assert refs_for_b == []


async def test_shared_order_header_row_is_allowed_across_distinct_events(db_session: AsyncSession, seeded_users):
    """PR #103 fix: one `Orders ยืมเครื่อง` header row (source_row_number
    = H) can describe an order covering multiple equipment line-items,
    each its own independent `LegacyEquipmentEvent`. Event A refs header
    H + line-item L1; Event B refs the SAME header H + a DIFFERENT
    line-item L2. Both commits must succeed -- this is provenance
    topology only, not Issue<->Receive pairing (§11.2, unaffected), and
    creates no link between event A and event B."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    event_a = _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="headerA1")
    event_b = _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="headerB1")
    db_session.add_all([event_a, event_b])
    await db_session.flush()

    header_sheet = "Orders ยืมเครื่อง"
    header_row_number = 7

    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event_a.id,
            import_session_id=session.id,
            import_source_id=source.id,
            source_checksum=source.checksum,
            sheet_name=header_sheet,
            source_row_number=header_row_number,
        )
    )
    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event_a.id,
            import_session_id=session.id,
            import_source_id=source.id,
            source_checksum=source.checksum,
            sheet_name="ข้อมูลส่งเครื่องมือ",
            source_row_number=101,  # L1
        )
    )
    await db_session.commit()

    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event_b.id,
            import_session_id=session.id,
            import_source_id=source.id,
            source_checksum=source.checksum,
            sheet_name=header_sheet,
            source_row_number=header_row_number,
        )
    )
    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event_b.id,
            import_session_id=session.id,
            import_source_id=source.id,
            source_checksum=source.checksum,
            sheet_name="ข้อมูลส่งเครื่องมือ",
            source_row_number=102,  # L2, distinct from L1
        )
    )
    await db_session.commit()

    header_refs = (
        await db_session.execute(
            select(LegacyEquipmentEventSourceRef).where(
                LegacyEquipmentEventSourceRef.sheet_name == header_sheet,
                LegacyEquipmentEventSourceRef.source_row_number == header_row_number,
            )
        )
    ).scalars().all()
    assert {r.legacy_equipment_event_id for r in header_refs} == {event_a.id, event_b.id}


async def test_duplicate_source_ref_on_the_same_event_still_rejected(db_session: AsyncSession, seeded_users):
    """PR #103 fix, negative counterpart: header-row sharing is scoped
    to DIFFERENT events only. The same event registering a provenance
    ref to the identical physical source row twice must still be
    rejected -- proves the per-event dedup was not simply removed
    alongside the added `legacy_equipment_event_id` scope column."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    event_a = _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="dupref01")
    db_session.add(event_a)
    await db_session.flush()

    header_sheet = "Orders ยืมเครื่อง"
    header_row_number = 7

    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event_a.id,
            import_session_id=session.id,
            import_source_id=source.id,
            source_checksum=source.checksum,
            sheet_name=header_sheet,
            source_row_number=header_row_number,
        )
    )
    await db_session.commit()

    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event_a.id,
            import_session_id=session.id,
            import_source_id=source.id,
            source_checksum=source.checksum,
            sheet_name=header_sheet,
            source_row_number=header_row_number,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# F2. Permanent provenance -- session/source ownership consistency (PR #103)
# ---------------------------------------------------------------------------


async def test_event_import_source_must_belong_to_its_own_import_session(db_session: AsyncSession, seeded_users):
    """PR #103 fix: `fk_legacy_equipment_events_source_belongs_to_session`
    -- an event claiming `import_session_id = Session A` but
    `import_source_id = Source B` (a real row, but belonging to a
    DIFFERENT session) must be rejected. Two individually-valid FKs are
    not sufficient; the pair must agree."""
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session_a, source_a = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum="a" * 64)
    session_b, source_b = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum="b" * 64)
    equipment = await _seed_equipment(db_session)
    assert source_a.import_session_id == session_a.id
    assert source_b.import_session_id == session_b.id

    db_session.add(
        _make_event(
            authority_id=authority.id,
            equipment_id=equipment.id,
            import_session_id=session_a.id,
            import_source_id=source_b.id,
            row_key="crosscontext1",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_event_import_source_matching_its_own_session_succeeds(db_session: AsyncSession, seeded_users):
    """Positive counterpart: `import_session_id`/`import_source_id` that
    genuinely belong together commit successfully -- the composite FK
    does not reject the normal, consistent case."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    event = _make_event(
        authority_id=authority.id,
        equipment_id=equipment.id,
        import_session_id=session.id,
        import_source_id=source.id,
        row_key="samecontext1",
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    assert event.import_session_id == session.id
    assert event.import_source_id == source.id


async def test_source_ref_context_must_exactly_match_its_own_event(db_session: AsyncSession, seeded_users):
    """PR #103 fix: `fk_legacy_equipment_event_source_refs_event_context`
    -- a ref claiming provenance for event E but carrying a DIFFERENT
    (session, source) pair than E's own must be rejected, even though
    the ref's `legacy_equipment_event_id`, `import_session_id`, and
    `import_source_id` are each individually a real row somewhere."""
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session_a, source_a = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum="c" * 64)
    session_b, source_b = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum="d" * 64)
    equipment = await _seed_equipment(db_session)

    event = _make_event(
        authority_id=authority.id,
        equipment_id=equipment.id,
        import_session_id=session_a.id,
        import_source_id=source_a.id,
        row_key="ctxevent1",
    )
    db_session.add(event)
    await db_session.flush()

    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event.id,
            import_session_id=session_b.id,
            import_source_id=source_b.id,
            source_checksum=source_b.checksum,
            sheet_name="Orders ยืมเครื่อง",
            source_row_number=1,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_source_ref_partial_context_mismatch_still_rejected(db_session: AsyncSession, seeded_users):
    """PR #103 fix, partial-mismatch variant: only the session differs
    (the ref's own source is a real row -- just not the one belonging to
    the session the ref claims). The composite FK requires the FULL
    triple to match the event's own row, not merely that each column is
    independently valid somewhere."""
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session_a, source_a = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum="e" * 64)
    session_b, _source_b = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum="f" * 64)
    equipment = await _seed_equipment(db_session)

    event = _make_event(
        authority_id=authority.id,
        equipment_id=equipment.id,
        import_session_id=session_a.id,
        import_source_id=source_a.id,
        row_key="partialmismatch1",
    )
    db_session.add(event)
    await db_session.flush()

    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event.id,
            import_session_id=session_b.id,  # wrong session
            import_source_id=source_a.id,  # source_a is real, but belongs to session_a, not session_b
            source_checksum=source_a.checksum,
            sheet_name="Orders ยืมเครื่อง",
            source_row_number=1,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_source_ref_context_matching_its_own_event_succeeds(db_session: AsyncSession, seeded_users):
    """Positive counterpart: a ref whose (session, source) exactly
    matches its own event's commits successfully, and two distinct
    events may still legitimately share the same header row (the PR
    #103 fix round 1 regression, unaffected by this round's composite
    FK)."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    event_a = _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="matchctxA1")
    event_b = _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="matchctxB1")
    db_session.add_all([event_a, event_b])
    await db_session.flush()

    header_sheet = "Orders ยืมเครื่อง"
    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event_a.id,
            import_session_id=session.id,
            import_source_id=source.id,
            source_checksum=source.checksum,
            sheet_name=header_sheet,
            source_row_number=9,
        )
    )
    db_session.add(
        LegacyEquipmentEventSourceRef(
            legacy_equipment_event_id=event_b.id,
            import_session_id=session.id,
            import_source_id=source.id,
            source_checksum=source.checksum,
            sheet_name=header_sheet,
            source_row_number=9,
        )
    )
    await db_session.commit()

    refs = (
        await db_session.execute(
            select(LegacyEquipmentEventSourceRef).where(LegacyEquipmentEventSourceRef.source_row_number == 9)
        )
    ).scalars().all()
    assert {r.legacy_equipment_event_id for r in refs} == {event_a.id, event_b.id}


async def test_source_ref_survives_independently_of_temporary_source_row_storage(db_session: AsyncSession, seeded_users):
    """§26: provenance is normalized (`sheet_name`, `source_row_number`,
    `source_checksum`), never a dump of the full raw row -- confirmed
    structurally, not merely by convention: `LegacyEquipmentEventSourceRef`
    has no free-text/raw-row column at all."""
    columns = {c.name for c in LegacyEquipmentEventSourceRef.__table__.columns}
    assert "raw_row" not in columns
    assert "raw_values" not in columns
    assert {"import_session_id", "import_source_id", "source_checksum", "sheet_name", "source_row_number"} <= columns


# ---------------------------------------------------------------------------
# G. LegacyWardAlias -- OD-PR21-4
# ---------------------------------------------------------------------------


async def test_ward_alias_unambiguous_uniqueness(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    ward = await _seed_ward(db_session, code="ICU")
    db_session.add(LegacyWardAlias(raw_alias="ไอซียู", ward_id=ward.id, created_by_user_id=actor_id))
    await db_session.commit()

    db_session.add(LegacyWardAlias(raw_alias="ไอซียู", ward_id=ward.id, created_by_user_id=actor_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_ward_alias_fk_integrity(db_session: AsyncSession, seeded_users):
    """SQLite does not enforce `FOREIGN KEY` constraints unless `PRAGMA
    foreign_keys=ON` is set on the connection (off by default, unlike
    PostgreSQL) -- enabled explicitly here so this test actually proves
    the constraint exists, rather than silently passing for the wrong
    reason on SQLite while only PostgreSQL would have caught a real
    regression."""
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    db_session.add(LegacyWardAlias(raw_alias="no-such-ward-alias", ward_id=uuid.uuid4(), created_by_user_id=actor_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_ward_alias_no_fuzzy_resolution_mechanism(db_session: AsyncSession, seeded_users):
    """OD-PR21-4: resolving an alias is a plain equality lookup -- a
    near-miss string never resolves."""
    actor_id = await _get_user_id(db_session)
    ward = await _seed_ward(db_session, code="OPD")
    db_session.add(LegacyWardAlias(raw_alias="OPD Ward", ward_id=ward.id, created_by_user_id=actor_id))
    await db_session.commit()

    resolved = (
        await db_session.execute(select(LegacyWardAlias).where(LegacyWardAlias.raw_alias == "opd ward"))
    ).scalar_one_or_none()
    assert resolved is None, "case-differing text must not resolve -- no fuzzy/normalized lookup exists in this table"


# ---------------------------------------------------------------------------
# H. Retention integration -- temporary plan content vs. permanent events
# ---------------------------------------------------------------------------


def test_legacy_history_provider_is_registered_by_default():
    provider = get_plan_provider(DATASET_TYPE)
    assert isinstance(provider, LegacyHistoryDryRunPlanProvider)


async def _seed_plan_with_one_row(db_session: AsyncSession, *, session: ImportSession, source: ImportSource, authority: LegacyMigrationAuthority) -> LegacyHistoryDryRunPlan:
    from app.models.import_session import ImportJob

    validation_job = ImportJob(import_session_id=session.id, job_type="validate", status="succeeded", attempt_number=1)
    dry_run_job = ImportJob(import_session_id=session.id, job_type="dry_run", status="succeeded", attempt_number=1)
    db_session.add_all([validation_job, dry_run_job])
    await db_session.flush()

    plan = await legacy_history_dry_run_plan_crud.insert_plan(
        db_session,
        import_session_id=session.id,
        import_source_id=source.id,
        migration_authority_id=authority.id,
        source_checksum=source.checksum,
        accepted_validation_job_id=validation_job.id,
        dry_run_job_id=dry_run_job.id,
        ruleset_version="v1",
        summary_total_rows=1,
        summary_issue_events=1,
        summary_receive_events=0,
        summary_warnings=0,
        summary_blocking_conflicts=0,
    )
    await legacy_history_dry_run_plan_crud.bulk_insert_plan_rows(
        db_session,
        [
            LegacyHistoryDryRunPlanRow(
                dry_run_plan_id=plan.id,
                source_row_number=1,
                event_type="ISSUE",
                legacy_source_row_key="planrow1",
                normalized_values={"equipment_bcm": "BCM123"},
                warnings=["unmapped BME name"],
            )
        ],
    )
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


async def test_retention_redacts_temporary_plan_row_content(client: AsyncClient, seeded_users, db_session: AsyncSession):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    plan = await _seed_plan_with_one_row(db_session, session=session, source=source, authority=authority)
    row = (
        await db_session.execute(select(LegacyHistoryDryRunPlanRow).where(LegacyHistoryDryRunPlanRow.dry_run_plan_id == plan.id))
    ).scalar_one()
    assert row.normalized_values is not None
    assert row.warnings is not None

    session_db = (await db_session.execute(select(ImportSession).where(ImportSession.id == session.id))).scalar_one()
    session_db.dry_run_completed_at = datetime.now(timezone.utc) - timedelta(days=200)
    session_db.status = "completed"
    session_db.terminal_at = datetime.now(timezone.utc) - timedelta(days=200)
    await db_session.commit()

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 1

    await db_session.refresh(session_db)
    assert session_db.retention_purged_at is not None

    await db_session.refresh(row)
    assert row.normalized_values is None
    assert row.warnings is None
    assert row.source_row_number == 1, "structural columns must survive redaction"
    assert row.event_type == "ISSUE", "structural columns must survive redaction"
    assert row.legacy_source_row_key == "planrow1", "structural columns must survive redaction"


async def test_retention_never_touches_permanent_legacy_equipment_events(client: AsyncClient, seeded_users, db_session: AsyncSession):
    """§39's temporary-vs-permanent boundary, proved directly: a
    `LegacyEquipmentEvent`/`SourceRef` pair belonging to the SAME
    session that retention just purged survives completely untouched --
    permanent historical evidence is never redacted by the 180-day
    import-artifact timer."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    equipment = await _seed_equipment(db_session)

    event = _make_event(authority_id=authority.id, equipment_id=equipment.id, import_session_id=session.id, import_source_id=source.id, row_key="permanent1")
    db_session.add(event)
    await db_session.flush()
    ref = LegacyEquipmentEventSourceRef(
        legacy_equipment_event_id=event.id,
        import_session_id=session.id,
        import_source_id=source.id,
        source_checksum=source.checksum,
        sheet_name="Orders ยืมเครื่อง",
        source_row_number=1,
    )
    db_session.add(ref)

    session_db = (await db_session.execute(select(ImportSession).where(ImportSession.id == session.id))).scalar_one()
    session_db.dry_run_completed_at = datetime.now(timezone.utc) - timedelta(days=200)
    session_db.status = "completed"
    session_db.terminal_at = datetime.now(timezone.utc) - timedelta(days=200)
    await db_session.commit()

    headers = await auth_headers(client)
    r = await client.post("/api/v1/import-sessions/retention/cleanup", headers=headers, json={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["purged_count"] == 1

    await db_session.refresh(event)
    await db_session.refresh(ref)
    assert event.legacy_source_row_key == "permanent1"
    assert event.equipment_id == equipment.id
    assert ref.sheet_name == "Orders ยืมเครื่อง"
    assert ref.source_row_number == 1


# ---------------------------------------------------------------------------
# H2. Dry-run plan row uniqueness -- ISSUE vs RECEIVE row-number overlap
# ---------------------------------------------------------------------------


async def _seed_bare_plan(db_session: AsyncSession, *, session: ImportSession, source: ImportSource, authority: LegacyMigrationAuthority) -> LegacyHistoryDryRunPlan:
    """Like `_seed_plan_with_one_row` but inserts no rows -- callers add
    their own `LegacyHistoryDryRunPlanRow` rows directly."""
    from app.models.import_session import ImportJob

    validation_job = ImportJob(import_session_id=session.id, job_type="validate", status="succeeded", attempt_number=1)
    dry_run_job = ImportJob(import_session_id=session.id, job_type="dry_run", status="succeeded", attempt_number=1)
    db_session.add_all([validation_job, dry_run_job])
    await db_session.flush()

    plan = await legacy_history_dry_run_plan_crud.insert_plan(
        db_session,
        import_session_id=session.id,
        import_source_id=source.id,
        migration_authority_id=authority.id,
        source_checksum=source.checksum,
        accepted_validation_job_id=validation_job.id,
        dry_run_job_id=dry_run_job.id,
        ruleset_version="v1",
        summary_total_rows=0,
        summary_issue_events=0,
        summary_receive_events=0,
        summary_warnings=0,
        summary_blocking_conflicts=0,
    )
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


async def test_plan_row_issue_and_receive_may_share_the_same_source_row_number(db_session: AsyncSession, seeded_users):
    """PR #103 fix: a dry-run plan legitimately contains both an ISSUE
    row and a RECEIVE row that reuse the identical physical
    source_row_number -- those two source sheets are independent
    datasets in PR21 V1 and naturally renumber from 1. Both rows must
    persist in the same plan."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    plan = await _seed_bare_plan(db_session, session=session, source=source, authority=authority)

    await legacy_history_dry_run_plan_crud.bulk_insert_plan_rows(
        db_session,
        [
            LegacyHistoryDryRunPlanRow(
                dry_run_plan_id=plan.id, source_row_number=2, event_type="ISSUE", legacy_source_row_key="issue-key"
            ),
            LegacyHistoryDryRunPlanRow(
                dry_run_plan_id=plan.id, source_row_number=2, event_type="RECEIVE", legacy_source_row_key="receive-key"
            ),
        ],
    )
    await db_session.commit()

    rows = (
        await db_session.execute(select(LegacyHistoryDryRunPlanRow).where(LegacyHistoryDryRunPlanRow.dry_run_plan_id == plan.id))
    ).scalars().all()
    assert len(rows) == 2
    assert {r.event_type for r in rows} == {"ISSUE", "RECEIVE"}
    assert {r.source_row_number for r in rows} == {2}


async def test_plan_row_duplicate_within_same_event_type_still_rejected(db_session: AsyncSession, seeded_users):
    """Negative counterpart: the ISSUE/RECEIVE overlap allowance is
    scoped to different event types only -- two ISSUE rows in the same
    plan claiming the same source_row_number must still be rejected,
    proving duplicate protection was not simply removed."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    plan = await _seed_bare_plan(db_session, session=session, source=source, authority=authority)

    db_session.add(
        LegacyHistoryDryRunPlanRow(dry_run_plan_id=plan.id, source_row_number=2, event_type="ISSUE", legacy_source_row_key="issue-key-1")
    )
    await db_session.commit()

    db_session.add(
        LegacyHistoryDryRunPlanRow(dry_run_plan_id=plan.id, source_row_number=2, event_type="ISSUE", legacy_source_row_key="issue-key-2")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_plan_row_same_row_number_allowed_across_different_plans(db_session: AsyncSession, seeded_users):
    """The uniqueness scope is per-plan -- two different plans may each
    independently claim ISSUE row_number=2 without colliding."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session_a, source_a = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    session_b, source_b = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    plan_a = await _seed_bare_plan(db_session, session=session_a, source=source_a, authority=authority)
    plan_b = await _seed_bare_plan(db_session, session=session_b, source=source_b, authority=authority)

    db_session.add(
        LegacyHistoryDryRunPlanRow(dry_run_plan_id=plan_a.id, source_row_number=2, event_type="ISSUE", legacy_source_row_key="a-key")
    )
    db_session.add(
        LegacyHistoryDryRunPlanRow(dry_run_plan_id=plan_b.id, source_row_number=2, event_type="ISSUE", legacy_source_row_key="b-key")
    )
    await db_session.commit()

    rows = (
        await db_session.execute(select(LegacyHistoryDryRunPlanRow).where(LegacyHistoryDryRunPlanRow.source_row_number == 2))
    ).scalars().all()
    assert {r.dry_run_plan_id for r in rows} == {plan_a.id, plan_b.id}


# ---------------------------------------------------------------------------
# Provider contract -- plan CRUD exercised directly (no adapter exists yet)
# ---------------------------------------------------------------------------


async def test_provider_get_current_plan_and_confirm_round_trip(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    plan = await _seed_plan_with_one_row(db_session, session=session, source=source, authority=authority)

    provider = LegacyHistoryDryRunPlanProvider()
    current = await provider.get_current_plan(db_session, import_session_id=session.id)
    assert current is not None
    assert current.id == plan.id

    result = await provider.confirm_plan(db_session, plan_id=plan.id, import_session_id=session.id, current_user_id=actor_id)
    await db_session.commit()
    assert result.newly_confirmed is True
    assert result.plan.confirmed_by_user_id == actor_id

    replay = await provider.confirm_plan(db_session, plan_id=plan.id, import_session_id=session.id, current_user_id=actor_id)
    assert replay.newly_confirmed is False


async def test_provider_list_plan_rows_rejects_foreign_session(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session_a, source_a = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    plan_a = await _seed_plan_with_one_row(db_session, session=session_a, source=source_a, authority=authority)

    session_b, _source_b = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum="9" * 64)

    provider = LegacyHistoryDryRunPlanProvider()
    with pytest.raises(ImportDryRunPlanNotFoundError):
        await provider.list_plan_rows(db_session, import_session_id=session_b.id, plan_id=plan_a.id, limit=25, cursor=None)


async def test_confirm_plan_rejects_stale_session_state(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id)
    session, source = await _seed_import_session_and_source(db_session, actor_id=actor_id, checksum=authority.approved_workbook_sha256)
    plan = await _seed_plan_with_one_row(db_session, session=session, source=source, authority=authority)

    session_db = (await db_session.execute(select(ImportSession).where(ImportSession.id == session.id))).scalar_one()
    session_db.status = "cancelled"
    await db_session.commit()

    provider = LegacyHistoryDryRunPlanProvider()
    with pytest.raises(ImportDryRunPlanStaleError):
        await provider.confirm_plan(db_session, plan_id=plan.id, import_session_id=session.id, current_user_id=actor_id)


# ---------------------------------------------------------------------------
# I. Migration round trip -- PostgreSQL only, real `alembic` CLI
# ---------------------------------------------------------------------------

pytest.importorskip("asyncpg")

from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from tests.test_postgres_integration import (  # noqa: E402
    _drop_scratch_database,
    _recreate_scratch_database,
    _run_alembic,
    _scratch_dsn,
)


_MIGRATION_0019_TABLES = {
    "legacy_migration_authorities",
    "legacy_equipment_events",
    "legacy_equipment_event_source_refs",
    "legacy_ward_aliases",
    "legacy_history_dry_run_plans",
    "legacy_history_dry_run_plan_rows",
}


async def _existing_tables(names: set[str]) -> set[str]:
    """Returns the subset of `names` that currently exist as real tables.
    Deliberately scoped to a fixed, named set (never a broad `legacy_`
    prefix glob) -- migration 0001's own `Base.metadata.create_all()`
    creates every currently-registered ORM table on a fresh database
    regardless of which revision an `alembic upgrade` targets, so a
    later migration's tables (e.g. 0020, Roadmap PR22B) are already
    physically present the moment migration 0001 runs, even when the
    upgrade target is an earlier revision such as 0019. A prefix-glob
    "exactly these tables and no others" comparison would therefore
    incorrectly see 0020's tables too; checking only this fixed,
    migration-0019-owned name set (mirroring
    `test_migration_0018_downgrade_re_upgrade_round_trip`'s per-table
    `to_regclass` pattern in `test_postgres_integration.py`, the
    established convention for this exact interaction) is unaffected by
    what any other migration does."""
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            actual = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
            return names & actual
    finally:
        await engine.dispose()


@pytest.mark.postgres
async def test_migration_0019_upgrade_downgrade_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        # Always upgrades to "head" (never an intermediate target on a
        # fresh database) and then downgrades back down to just before
        # this migration -- this is the established, later-migration-safe
        # pattern (see `test_migration_0018_downgrade_re_upgrade_round_
        # trip`), since downgrading from head runs every intervening
        # migration's own downgrade() in sequence (0020's, then 0019's),
        # correctly removing both sets of tables regardless of how many
        # later migrations now exist.
        _run_alembic("upgrade", "head")
        tables = await _existing_tables(_MIGRATION_0019_TABLES)
        assert tables == _MIGRATION_0019_TABLES

        _run_alembic("downgrade", "0018_dry_run_plans")
        tables = await _existing_tables(_MIGRATION_0019_TABLES)
        assert tables == set(), "downgrade must remove exactly the six tables this migration added"

        _run_alembic("upgrade", "head")
        tables = await _existing_tables(_MIGRATION_0019_TABLES)
        assert tables == _MIGRATION_0019_TABLES, "re-upgrade must succeed and converge exactly like a fresh install"
    finally:
        await _drop_scratch_database()
