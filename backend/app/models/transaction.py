import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.reporting_time import Shift, business_date_and_shift
from app.db.base import Base
from app.models.mixins import TimestampMixin, UTCDateTime, UUIDPKMixin


class TransactionStatus(str, enum.Enum):
    """Roadmap PR7 (knowledge/adr/ADR-005-transaction-model.md) confirmed
    two-state transaction lifecycle.

    Superseded the prior three-value status (borrowed/returned/overdue).
    See migration 0007_transaction_lifecycle.py for the exact
    legacy-to-target mapping and BorrowTransaction.legacy_status for the
    preserved original value. Mirrors app.models.equipment.EquipmentStatus's
    shape (Roadmap PR6 precedent).
    """

    OPEN = "open"
    CLOSED = "closed"


TransactionStatusType = Enum(
    TransactionStatus,
    name="transaction_status",
    native_enum=False,
    length=10,
    # See app.models.equipment.EquipmentStatusType's identical comment:
    # without this, SQLAlchemy's Enum type persists each member's *name*
    # ("OPEN") rather than its .value ("open"). values_callable makes new
    # writes persist the lowercase .value, matching migration 0007's raw
    # SQL and every other part of the system.
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class DispatchType(str, enum.Enum):
    """Roadmap PR7b (docs/audits/04-consolidated-implementation-plan.md
    confirmed-requirements table: "Dispatch types | Exactly 2:
    `ROUTINE_ROUND` ... and `ON_DEMAND`") confirmed two-value dispatch-type
    domain. Mirrors TransactionStatus/EquipmentStatus's (str, enum.Enum)
    shape and the same values_callable persistence technique.
    """

    ROUTINE_ROUND = "routine_round"
    ON_DEMAND = "on_demand"


DispatchTypeType = Enum(
    DispatchType,
    name="dispatch_type",
    native_enum=False,
    length=20,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class RoutineRound(str, enum.Enum):
    """Roadmap PR7b confirmed fixed four-round MVP schedule -- the literal
    clock times themselves, the only values confirmed anywhere in the
    source-of-truth docs (docs/audits/04-consolidated-implementation-plan.md
    confirmed-requirements table: "06:00/11:00/15:00/21:00"; repeated
    verbatim in docs/audits/03-hospital-equipment-pool-workflow-audit.md's
    §12 acceptance criteria). No named label for any round (e.g. "morning")
    is confirmed anywhere, so none is invented here -- the persisted value
    *is* the confirmed value, matching the "do not invent" instruction this
    Roadmap PR was scoped under.

    This is an explicit, confirmed MVP simplification (docs/
    HOSPITAL_DOMAIN_MODEL.md: "Fixed routine-round values are an MVP
    simplification until a separately scoped future change replaces
    them") -- do not extend this enum to model flexible Shift Sessions;
    that is confirmed future direction, not yet scheduled to a Roadmap PR
    (see docs/ROADMAP.md "Confirmed future work").
    """

    ROUND_0600 = "06:00"
    ROUND_1100 = "11:00"
    ROUND_1500 = "15:00"
    ROUND_2100 = "21:00"


RoutineRoundType = Enum(
    RoutineRound,
    name="routine_round",
    native_enum=False,
    length=5,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class ReceiptOutcome(str, enum.Enum):
    """Roadmap PR8B (knowledge/adr/ADR-006-receipt-outcome-contract.md)
    confirmed binary receipt outcome -- the exact domain vocabulary
    `docs/HOSPITAL_DOMAIN_MODEL.md`'s "Confirmed workflow" already used
    ("receipt outcome: usable" / "receipt outcome: defective"), now
    expressed as the request/response contract's own field name and value
    domain instead of only an internal dict lookup
    (RETURN_CONDITION_TO_STATUS's pre-PR8B four-value `condition` string).

    This is a request/response-contract type only -- it does not back a
    database column (no ``ReceiptOutcomeType`` ``Enum(...)`` is defined
    here, unlike TransactionStatusType/DispatchTypeType/RoutineRoundType
    above). ``BorrowTransaction.condition_on_return`` remains the
    unconstrained ``String(30)`` column it already was (see below) --
    Option A from docs/design/PR8_IMPLEMENTATION_PLAN.md's Section 5
    explicitly needs no schema migration, and the column still holds
    genuine pre-PR8B historical values (`available`/`pm`/`calibration`/
    `repair`) that predate this domain and are never remapped.
    """

    USABLE = "usable"
    DEFECTIVE = "defective"


class BorrowTransaction(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "borrow_transactions"
    # Named `idx_tx_one_active_borrow`, matching the identical name
    # migration 0007_transaction_lifecycle.py's raw SQL unconditionally
    # (re)creates this index under on every path -- see 0007's `DROP INDEX
    # IF EXISTS idx_tx_one_active_borrow` / `CREATE UNIQUE INDEX
    # idx_tx_one_active_borrow ...`. Because 0007 (an immutable historical
    # migration) always targets this literal name regardless of what a
    # fresh install's 0001 bootstrap already produced from ORM metadata,
    # the ORM declaration must keep matching it -- renaming it here to the
    # `ix_`-prefixed target name migration 0014 uses (Roadmap PR15B,
    # docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §6.2) would make 0001 create
    # one index under the new name while 0007 unconditionally creates a
    # *second*, differently-named duplicate -- a real bug, not a
    # convergence fix. Migration 0014 renames this index at the database
    # level identically on every path (fresh or historical) precisely
    # because 0007 always leaves it under this legacy name; no ORM-side
    # rename is safe or necessary here, unlike the 7 unique constraints in
    # equipment.py/master_data.py/user.py.
    __table_args__ = (
        Index(
            "idx_tx_one_active_borrow",
            "equipment_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
    )

    transaction_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Roadmap PR7b: no longer accepted from BorrowRequest (See
    # app.schemas.transaction.BorrowRequest) -- one scan/dispatch is always
    # exactly one physical device (docs/HOSPITAL_DOMAIN_MODEL.md: "quantity
    # is not a substitute for equipment identity"). The column and its
    # default=1 are unchanged; every new row simply relies on the default
    # rather than receiving an explicit value. Existing historical values
    # are preserved and remain readable (e.g. app.services.report_service).
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # See app.models.audit.AuditLog.created_at's identical comment (Roadmap
    # PR15B, docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §3.4/§3.5).
    borrowed_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    # Roadmap PR7b: removed from the active request/response contract
    # entirely (See app.schemas.transaction.BorrowRequest, TransactionOut)
    # -- ADR-005 decision 3 already retired the due-date/overdue *workflow*;
    # this removes the now-pointless field from the write path and API
    # surface too. The column itself, and every existing value, are
    # unchanged and remain queryable/exportable (e.g. app.services.
    # report_service's CSV/XLSX export reads it directly from the ORM row).
    # Roadmap PR15B (docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §3.4a):
    # deliberately excluded from the timezone conversion applied to the
    # other four naive-`timestamp` columns -- this column was already
    # removed from the write path before its historical values' timezone
    # provenance could be confirmed, so it remains naive rather than being
    # converted on an unproven assumption.
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    borrower_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    # Roadmap PR7b: relaxed from NOT NULL (migration
    # 0008_dispatch_fields.py) -- no longer accepted or required by
    # BorrowRequest (confirmed acceptance criteria: "when no borrower_name
    # is supplied, then the request succeeds"). Every existing value is
    # preserved as read-only history and remains visible in TransactionOut.
    borrower_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    ward_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("wards.id", ondelete="RESTRICT"), index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT")
    )
    phone_number: Mapped[str | None] = mapped_column(String(20))
    pickup_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    dropoff_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    # Roadmap PR8B: the column itself, its name, and every existing value
    # are unchanged (Option A -- no schema migration). ``receipt_outcome``
    # below is the wire-level business term exposed in the API response
    # (app.schemas.transaction.TransactionOut); the column continues to
    # hold pre-PR8B historical values too (`available`/`pm`/`calibration`/
    # `repair`), which are preserved and remain readable exactly as
    # PR7b preserved borrower_name/due_at/quantity -- never remapped.
    condition_on_return: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    received_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    status: Mapped[TransactionStatus] = mapped_column(
        TransactionStatusType, default=TransactionStatus.OPEN, nullable=False, index=True
    )
    # Roadmap PR7b: nullable at the database level -- an existing row
    # created before this migration has no reliable source to classify as
    # routine-vs-on-demand and is left NULL, not guessed (docs/audits/
    # 04-consolidated-implementation-plan.md Part E, "Add dispatch_type,
    # routine_round"). Required for every *new* dispatch, enforced at the
    # application layer (app.schemas.transaction.BorrowRequest), matching
    # this plan's explicit instruction that ward_id-required is
    # application-layer-only too -- see ward_id above.
    dispatch_type: Mapped[DispatchType | None] = mapped_column(DispatchTypeType, nullable=True)
    # Required only when dispatch_type == ROUTINE_ROUND; must be absent
    # (NULL) for ON_DEMAND and for any historical/unclassified row.
    # Enforced at the application layer (BorrowRequest's model_validator)
    # and, in PostgreSQL, by the CHECK constraint
    # ck_borrow_transactions_routine_round_consistency added by migration
    # 0008_dispatch_fields.py -- defense in depth, not either/or.
    routine_round: Mapped[RoutineRound | None] = mapped_column(RoutineRoundType, nullable=True)
    # Roadmap PR7: the exact pre-migration status value for any row remapped
    # by 0007_transaction_lifecycle.py (e.g. "borrowed", "overdue"),
    # preserved verbatim for audit/rollback only. Never read by any workflow
    # or eligibility check. Left NULL for every row created after that
    # migration. Mirrors app.models.equipment.Equipment.legacy_status
    # (Roadmap PR6 precedent).
    legacy_status: Mapped[str | None] = mapped_column(String(20))

    equipment: Mapped["Equipment"] = relationship()

    @property
    def receipt_outcome(self) -> "ReceiptOutcome | None":
        """Roadmap PR8B wire-level business term for the persisted
        ``condition_on_return`` column -- read by
        ``app.schemas.transaction.TransactionOut`` (``from_attributes``).

        Codex review round 1, finding 2: the request contract is strictly
        binary (`ReceiptOutcome`), so the response field of the same name
        must also be strictly binary -- never one of the pre-PR8B legacy
        strings (`available`/`pm`/`calibration`/`repair`). Returns `None`
        for any column value that is not exactly `"usable"` or
        `"defective"` (including a genuine pre-PR8B legacy value, or a
        transaction that has not been received at all); it never
        translates/backfills a legacy value into the new domain, which
        would fabricate a fact the original receipt never recorded. A
        legacy value remains readable, unchanged, via
        `legacy_condition_on_return` below -- mutually exclusive with this
        property, mirroring `Equipment.legacy_status`'s "marker vs. real
        history, never both" precedent.
        """
        try:
            return ReceiptOutcome(self.condition_on_return)
        except ValueError:
            return None

    @property
    def legacy_condition_on_return(self) -> str | None:
        """Roadmap PR8B: the raw, unmodified pre-PR8B receipt value
        (`available`/`pm`/`calibration`/`repair`) for a transaction
        received before the binary `receipt_outcome` contract existed.
        `None` for a transaction received under the current contract, and
        `None` for a transaction not yet received at all -- mutually
        exclusive with `receipt_outcome` above. Never remapped or
        interpreted; preserved verbatim, mirroring
        `Equipment.legacy_status`'s and `BorrowTransaction.legacy_status`'s
        existing "preserve the exact original value, never fabricate"
        precedent.
        """
        if self.condition_on_return is None:
            return None
        if self.receipt_outcome is not None:
            return None
        return self.condition_on_return

    @property
    def dispatch_business_date(self) -> "date":
        """Roadmap PR16 Slice 2 (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md
        §9) -- computed, never persisted, derived from `borrowed_at` (every
        transaction has one, open or closed). Read by
        `app.schemas.transaction.TransactionOut` (`from_attributes`),
        mirroring the `receipt_outcome`/`legacy_condition_on_return`
        computed-property pattern above.
        """
        business_date, _ = business_date_and_shift(self.borrowed_at)
        return business_date

    @property
    def dispatch_shift(self) -> "Shift":
        """See `dispatch_business_date` above -- same derivation, same
        source timestamp."""
        _, shift = business_date_and_shift(self.borrowed_at)
        return shift

    @property
    def receipt_business_date(self) -> "date | None":
        """Roadmap PR16 Slice 2 -- derived from `returned_at`, which is
        `None` until the transaction is received. `None` here mirrors that
        exactly: an unreceived transaction has no receipt business_date,
        not a fabricated one derived from `borrowed_at` or the current
        time."""
        if self.returned_at is None:
            return None
        business_date, _ = business_date_and_shift(self.returned_at)
        return business_date

    @property
    def receipt_shift(self) -> "Shift | None":
        """See `receipt_business_date` above -- same derivation, same
        source timestamp, same `None`-until-received rule."""
        if self.returned_at is None:
            return None
        _, shift = business_date_and_shift(self.returned_at)
        return shift


class TransactionAttachment(UUIDPKMixin, Base):
    __tablename__ = "transaction_attachments"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("borrow_transactions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(30))  # photo | signature
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
