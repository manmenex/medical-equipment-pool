import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin, UTCDateTime, UUIDPKMixin

JSONType = JSONB().with_variant(JSON(), "sqlite")


class EquipmentStatus(str, enum.Enum):
    """Roadmap PR6 / HOSPITAL_DOMAIN_MODEL.md confirmed 4-state model.

    Superseded the prior 8-value enum (available/borrowed/cleaning/pm/
    calibration/repair/out_of_service/lost). See migration
    0006_equipment_state_model.py for the exact legacy-to-target mapping
    and Equipment.legacy_status for the preserved original value.
    """

    AVAILABLE_AT_POOL = "available_at_pool"
    ISSUED_TO_WARD = "issued_to_ward"
    UNAVAILABLE_DEFECTIVE = "unavailable_defective"
    DECOMMISSIONED = "decommissioned"


EquipmentStatusType = Enum(
    EquipmentStatus,
    name="equipment_status",
    native_enum=False,
    length=30,
    # Without this, SQLAlchemy's Enum type persists each member's *name*
    # (e.g. "AVAILABLE_AT_POOL") rather than its .value
    # ("available_at_pool") -- a latent bug present since 0001 for the
    # prior 8-value enum too (every equipment row created through
    # POST /equipment used the ORM column default, never an explicit raw
    # value, so it was never visible: reads round-trip back through this
    # same Enum type by name, and the API layer serializes the resulting
    # Python enum via .value, masking the on-disk casing). Roadmap PR6's
    # new ck_equipment_status_four_state CHECK constraint (lowercase
    # values only) surfaced it. values_callable makes new writes persist
    # the lowercase .value like every other part of the system (raw SQL,
    # migrations, API contracts) already assumes.
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)

# Roadmap PR6-H2: transition authority is split by *caller*, not just by
# state, because dispatch and receipt are not ordinary status edits -- they
# must create/close a BorrowTransaction atomically with the status change
# (see app.services.borrow_service). A single shared transition table would
# let the generic admin/BME maintenance endpoint (POST
# /equipment/{id}/status) desynchronize equipment.status from the
# transaction ledger, e.g. by manually flipping ISSUED_TO_WARD ->
# AVAILABLE_AT_POOL without ever closing the OPEN transaction. Each table
# below is consumed by exactly one call site -- see
# app.crud.equipment.change_status_for_dispatch_receipt (used only by
# app.services.borrow_service) and .change_status_for_manual_lifecycle
# (used only by the POST /equipment/{id}/status endpoint). Neither table
# grants DECOMMISSIONED an outgoing entry -- terminal in normal workflow,
# see HOSPITAL_DOMAIN_MODEL.md.

# Dispatch (borrow) and receipt (return) transitions. Never reachable from
# the manual maintenance endpoint -- ISSUED_TO_WARD does not appear as a
# key in MANUAL_LIFECYCLE_TRANSITIONS below, so no manual caller can ever
# originate a transition away from it, and AVAILABLE_AT_POOL -> ISSUED_TO_
# WARD (dispatch) exists only here.
DISPATCH_RECEIPT_TRANSITIONS: dict["EquipmentStatus", frozenset["EquipmentStatus"]] = {
    EquipmentStatus.AVAILABLE_AT_POOL: frozenset({EquipmentStatus.ISSUED_TO_WARD}),
    EquipmentStatus.ISSUED_TO_WARD: frozenset(
        {EquipmentStatus.AVAILABLE_AT_POOL, EquipmentStatus.UNAVAILABLE_DEFECTIVE}
    ),
}

# Manual, authorized maintenance-lifecycle transitions for the generic
# admin/BME status endpoint only. Deliberately excludes ISSUED_TO_WARD as a
# source OR target: this endpoint must never synthesize a dispatch, and
# must never resolve/desynchronize an OPEN transaction by editing equipment
# status directly -- receipt is exclusively app.services.borrow_service's
# job, since only it closes the corresponding BorrowTransaction atomically.
#
# AVAILABLE_AT_POOL has no direct DECOMMISSIONED entry: equipment must be
# marked UNAVAILABLE_DEFECTIVE first, and only UNAVAILABLE_DEFECTIVE may
# move to DECOMMISSIONED -- decommissioning always passes through the same
# defective-classification step, never a one-step skip from in-service.
# DECOMMISSIONED itself has no outgoing entry in this table -- terminal, no
# normal-workflow exit.
MANUAL_LIFECYCLE_TRANSITIONS: dict["EquipmentStatus", frozenset["EquipmentStatus"]] = {
    EquipmentStatus.AVAILABLE_AT_POOL: frozenset({EquipmentStatus.UNAVAILABLE_DEFECTIVE}),
    EquipmentStatus.UNAVAILABLE_DEFECTIVE: frozenset(
        {EquipmentStatus.AVAILABLE_AT_POOL, EquipmentStatus.DECOMMISSIONED}
    ),
}


class Equipment(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "equipment"
    # serial_number: Roadmap PR15B (docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md
    # §6.4) -- explicit name converges with migration 0014's
    # `uq_equipment_serial_number` rename instead of leaving `unique=True`
    # produce PostgreSQL's unnamed `equipment_serial_number_key`. The other
    # unique columns below (asset_number, item_no, bcm_code, qr_code_value)
    # already combine `unique=True` with `index=True`, which gives them
    # SQLAlchemy's own `ix_<table>_<column>` naming -- not part of this fix.
    __table_args__ = (UniqueConstraint("serial_number", name="uq_equipment_serial_number"),)
    # updated_at (TimestampMixin) is onupdate=func.now() — server-computed,
    # not known client-side. Without eager_defaults, SQLAlchemy marks it
    # expired after an UPDATE flush instead of fetching it via RETURNING
    # (unlike INSERT, which already fetches it eagerly by default). A plain
    # synchronous attribute access after that — e.g. building a response body
    # once the endpoint has already returned control past its last `await`
    # — has no async context to satisfy the resulting lazy refresh and
    # raises MissingGreenlet. eager_defaults=True makes UPDATE use
    # `RETURNING updated_at` too, so the value is always already loaded.
    __mapper_args__ = {"eager_defaults": True}

    asset_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    serial_number: Mapped[str | None] = mapped_column(String(100))
    equipment_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # See ADR-002 (identifier model), ADR-003 (BCM manual search), ADR-004
    # (hospital Item-No QR). Canonicalization: app.services.identifiers.
    #
    # item_no: the hospital's existing physical QR label content. Internal
    # QR-resolution key only — never offered as a manual-search field and
    # never returned in an operator-facing response. Nullable because
    # existing equipment predates this field and a future controlled Excel
    # import (Roadmap PR12) is the intended backfill path, not a mechanical
    # default.
    #
    # bcm_code: the primary operator-facing identifier hospital staff type
    # to manually find equipment. The only field the manual-search endpoint
    # matches against. Nullable for the same backfill reason as item_no.
    #
    # Both are unique on their canonical persisted form (a standard UNIQUE
    # constraint permits multiple NULLs in both PostgreSQL and SQLite, so
    # unmigrated rows don't collide with each other) and indexed for exact
    # lookup. Canonical-form uniqueness is proven at the database level
    # (PostgreSQL only, see migration 0005) by a CHECK constraint on each
    # column that every stored value already equals its own canonical
    # form, so these plain UNIQUE indexes are sufficient on their own --
    # no functional/expression index is used. bcm_code additionally gets
    # a trigram GIN index (PostgreSQL only, see migration 0004) for
    # responsive partial matching.
    item_no: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    bcm_code: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment_categories.id", ondelete="RESTRICT")
    )
    brand: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    department_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT")
    )
    status: Mapped[EquipmentStatus] = mapped_column(
        EquipmentStatusType, default=EquipmentStatus.AVAILABLE_AT_POOL, nullable=False, index=True
    )
    # Roadmap PR6: the exact pre-migration status value for any row remapped
    # by 0006_equipment_state_model.py (e.g. "cleaning", "pm", "repair"),
    # preserved verbatim for audit/rollback only. Never read by any
    # workflow or eligibility check -- see knowledge/architecture and
    # AGENTS.md's cleaning-retirement guardrail. Left NULL for every row
    # created after that migration.
    legacy_status: Mapped[str | None] = mapped_column(String(30))
    current_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    # Legacy self-generated `MEP:{asset_number}` QR value (pre-dates Roadmap
    # PR5). Retired by ADR-004: the hospital's own Item-No QR label is the
    # only supported QR format now, so this column is no longer written on
    # create (see migration 0005) and is kept only as historical data for
    # equipment created before that cutover — it is never read by any
    # active endpoint.
    qr_code_value: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    rfid_tag: Mapped[str | None] = mapped_column(String(64))
    pm_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    cal_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    # Roadmap PR12 (docs/audits/04-consolidated-implementation-plan.md Part
    # E, row "Add Asset ID"; Part F.1): the inventory import source file's
    # "Asset ID" column -- new, optional metadata, deliberately separate
    # from asset_number (Part E: "not renamed, reused, or merged into
    # either identifier column"). Not unique-constrained: hospital-wide
    # uniqueness is unconfirmed (§14 open question 2), so
    # app.services.import_service treats a duplicate as a conservative,
    # row-level, application-only conflict rather than a database
    # constraint -- see migration 0010's docstring.
    asset_id: Mapped[str | None] = mapped_column(String(100), index=True)
    # Roadmap PR12 (Part F.1 step 3): the import source file's "Asset
    # Status" value, preserved verbatim before being mapped into
    # EquipmentStatus through Part F.2's explicit, approved (currently
    # illustrative) mapping table. Never read by any workflow or
    # eligibility check -- provenance only, the same role legacy_status
    # plays for Roadmap PR6. Left NULL for every row not created/updated
    # by an inventory import.
    raw_source_status: Mapped[str | None] = mapped_column(String(100))
    equipment_metadata: Mapped[dict] = mapped_column("metadata", JSONType, default=dict)

    category: Mapped["EquipmentCategory | None"] = relationship()
    department_owner: Mapped["Department | None"] = relationship()
    current_location: Mapped["Location | None"] = relationship()
    status_history: Mapped[list["EquipmentStatusHistory"]] = relationship(
        back_populates="equipment", order_by="EquipmentStatusHistory.changed_at.desc()"
    )


class EquipmentStatusHistory(UUIDPKMixin, Base):
    __tablename__ = "equipment_status_history"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    # See app.models.audit.AuditLog.created_at's identical comment (Roadmap
    # PR15B, docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §3.4/§3.5).
    changed_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    equipment: Mapped["Equipment"] = relationship(back_populates="status_history")


class PMSchedule(UUIDPKMixin, Base):
    __tablename__ = "pm_schedules"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    notes: Mapped[str | None] = mapped_column(Text)


class CalibrationSchedule(UUIDPKMixin, Base):
    __tablename__ = "calibration_schedules"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    certificate_number: Mapped[str | None] = mapped_column(String(100))
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )


class EquipmentAttachment(UUIDPKMixin, Base):
    __tablename__ = "equipment_attachments"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50))
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
