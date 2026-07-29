import uuid
from datetime import date, datetime, time, timezone
from typing import Literal

from sqlalchemy import String, and_, cast, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.reporting_time import Shift, business_date_and_shift_sql
from app.models.equipment import Equipment
from app.models.transaction import BorrowTransaction, DispatchType, RoutineRound, TransactionStatus
from app.utils.pagination import decode_cursor, encode_cursor

# Roadmap PR4 (docs/kickoffs/PR4-architecture-kickoff.md): the numeric
# suffix's minimum zero-padding width. This is a MINIMUM, not a fixed
# maximum — a suffix past 99999999 is never rejected or truncated, it is
# simply wider (Python's :0Nd format spec only ever pads up, never cuts).
_TRANSACTION_NO_MIN_SUFFIX_WIDTH = 8

# The only two dialects generate_transaction_no() knows how to serve:
# PostgreSQL (production, real SEQUENCE) and SQLite (an explicitly
# isolated, non-concurrency-safe test/dev compatibility path — Owner
# Decision 1). Anything else fails closed via
# UnsupportedDatabaseDialectError rather than silently reusing the
# SQLite fallback, which was never intended for, or proven safe against,
# any other engine.
_DIALECT_POSTGRESQL = "postgresql"
_DIALECT_SQLITE = "sqlite"


class UnsupportedDatabaseDialectError(RuntimeError):
    """Raised when generate_transaction_no() runs against a database
    dialect that is neither the supported production path (PostgreSQL)
    nor the explicitly isolated test/dev compatibility path (SQLite).

    Intentionally a plain RuntimeError subclass, not a DomainError (same
    rationale as app.core.config.InsecureConfigurationError): an
    unsupported or misconfigured database engine is a server-side
    deployment defect, not something a client request caused or can
    retry past. It must fail closed and loud — surfaced as an unhandled
    500 via app.main's generic Exception handler — rather than silently
    falling through to the SQLite-only compatibility fallback, which is
    not concurrency-safe and was never validated against, or intended
    for, any dialect other than SQLite.
    """


async def generate_transaction_no(db: AsyncSession) -> str:
    """Generates the next transaction_no.

    PostgreSQL — the production source of truth — draws from the global
    ``transaction_no_seq`` SEQUENCE created by migration
    0003_transaction_no_seq.py: one atomic ``nextval()`` call, no
    application-level locking or retries, structurally free of the race
    the old COUNT+LIKE scan had. The numeric suffix is globally
    monotonic and deliberately never resets across calendar days (Owner
    Decision 3) — the ``{YYYYMMDD}`` prefix is cosmetic/human-readable
    only and plays no role in uniqueness.

    SQLite (used only by this project's test/dev suite, see
    backend/tests/conftest.py; migrations never run against it) falls
    back to ``_generate_transaction_no_sqlite_fallback``, which is NOT
    concurrency-safe and must never be read as evidence of the
    production behavior above — see that function's docstring and Owner
    Decision 1. PostgreSQL-backed tests
    (tests/test_postgres_integration.py, ``pytest.mark.postgres``) are
    the only proof of real sequence correctness.

    Any dialect that is neither of the above (a misconfigured or
    unsupported production database engine) raises
    ``UnsupportedDatabaseDialectError`` rather than silently reusing the
    SQLite fallback — see that exception's docstring.
    """
    today = datetime.utcnow().strftime("%Y%m%d")
    dialect_name = db.get_bind().dialect.name

    if dialect_name == _DIALECT_POSTGRESQL:
        seq_value = (await db.execute(text("SELECT nextval('transaction_no_seq')"))).scalar_one()
        return f"TX-{today}-{seq_value:0{_TRANSACTION_NO_MIN_SUFFIX_WIDTH}d}"

    if dialect_name == _DIALECT_SQLITE:
        return await _generate_transaction_no_sqlite_fallback(db, today)

    raise UnsupportedDatabaseDialectError(
        f"generate_transaction_no() has no supported implementation for database dialect "
        f"{dialect_name!r}. PostgreSQL is the only production path "
        f"(nextval('transaction_no_seq')); SQLite is an explicitly isolated, non-concurrency-safe "
        f"test/dev-only compatibility fallback. Refusing to silently generate a transaction number "
        f"on an unsupported/unverified dialect."
    )


async def _generate_transaction_no_sqlite_fallback(db: AsyncSession, today: str) -> str:
    """Non-production, SQLite-only compatibility path (Owner Decision 1).

    Retains the original pre-PR4 per-calendar-day COUNT+LIKE approach —
    only the padding width changed, to keep the emitted format
    consistent with the real PostgreSQL generator. This is NOT
    concurrency-safe (it has exactly the same read-then-write race the
    real generator was built to eliminate) and exists solely so this
    project's existing SQLite-backed test/dev suite keeps working
    without a broad test-infrastructure migration. It must never be
    presented as, or mistaken for, proof of production correctness.
    """
    prefix = f"TX-{today}-"
    count_stmt = select(func.count()).select_from(BorrowTransaction).where(
        BorrowTransaction.transaction_no.like(f"{prefix}%")
    )
    count = (await db.execute(count_stmt)).scalar_one()
    return f"{prefix}{count + 1:0{_TRANSACTION_NO_MIN_SUFFIX_WIDTH}d}"


async def get_open_transaction_for_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> BorrowTransaction | None:
    result = await db.execute(
        select(BorrowTransaction).where(
            BorrowTransaction.equipment_id == equipment_id,
            BorrowTransaction.status == TransactionStatus.OPEN,
        )
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, transaction_id: uuid.UUID) -> BorrowTransaction | None:
    result = await db.execute(
        select(BorrowTransaction)
        .options(selectinload(BorrowTransaction.equipment))
        .where(BorrowTransaction.id == transaction_id)
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, *, data: dict) -> BorrowTransaction:
    """Opens a new transaction. ``data`` is expected to omit ``status`` and
    rely on the model's ``TransactionStatus.OPEN`` column default -- the
    OPEN/CLOSED lifecycle has exactly one entry point (this function) and
    exactly one exit point (``close``, below)."""
    tx = BorrowTransaction(**data)
    db.add(tx)
    await db.flush()
    await db.refresh(tx, attribute_names=["equipment"])
    return tx


async def close(
    db: AsyncSession,
    tx: BorrowTransaction,
    *,
    received_by_user_id: uuid.UUID | None,
    receipt_outcome: str,
    notes: str | None,
) -> bool:
    """Conditionally closes an OPEN transaction and reports whether *this*
    call is the one that closed it. The only path that may set
    ``status = TransactionStatus.CLOSED`` -- mirrors
    ``app.crud.equipment.change_status_for_dispatch_receipt``'s role as the
    single authorized mutator for its own lifecycle concern.

    Roadmap PR8A (docs/design/PR8_IMPLEMENTATION_PLAN.md, Section 5 Option A):
    the receipt/close write is the atomic concurrency guard for the receipt
    race. Instead of mutating the ORM object and flushing an unconditional
    ``UPDATE ... WHERE id = :id`` (which cannot tell, at the SQL level, that a
    concurrent request already closed the row), this emits a single

        UPDATE borrow_transactions
           SET status = 'closed', returned_at = ..., condition_on_return = ...,
               received_by_user_id = ...[, notes = ...]
         WHERE id = :id AND status = 'open'

    and decides the winner by affected-row count. Under real concurrency (two
    requests for the same OPEN transaction), PostgreSQL grants exactly one the
    row and flips it ``open -> closed``; every other request's predicate
    ``status = 'open'`` no longer matches by the time its own UPDATE evaluates,
    so it affects **zero** rows. This function returns:

      - ``True``  -- this call transitioned the row (rowcount == 1): the winner.
      - ``False`` -- the row was not OPEN when this UPDATE ran (rowcount == 0):
        a concurrent request already closed it. The caller MUST NOT proceed to
        any equipment-status, status-history, or audit side effect.

    It does **not** mutate or refresh ``tx``: because the statement is executed
    as Core SQL (bypassing the ORM unit of work), ``tx``'s in-memory
    attributes are stale after a winning call. The caller is required to
    ``db.refresh(tx)`` after a ``True`` result before using it for the
    equipment transition or the response (see
    ``app.services.borrow_service.return_equipment``). The ``status = 'open'``
    literal here matches the value the ``TransactionStatusType`` enum persists
    (``native_enum=False`` + ``values_callable``, i.e. the lowercase ``.value``),
    the same literal the partial unique index ``idx_tx_one_active_borrow``
    already relies on.

    Roadmap PR8B (knowledge/adr/ADR-006-receipt-outcome-contract.md):
    ``receipt_outcome`` is the caller-facing business term (already a
    validated ``ReceiptOutcome.value`` -- ``"usable"``/``"defective"`` --
    by the time it reaches here); it is still persisted into the unchanged
    ``condition_on_return`` column (Option A -- no schema migration), which
    also holds genuine pre-PR8B historical values from before this contract
    narrowed.
    """
    values: dict = {
        "status": TransactionStatus.CLOSED,
        "returned_at": datetime.now(timezone.utc),
        "condition_on_return": receipt_outcome,
        "received_by_user_id": received_by_user_id,
    }
    if notes:
        # Preserves the existing "[Return] ..." append behavior. ``tx.notes``
        # is the value read at SELECT time; only the winner uses this result,
        # and nothing else concurrently rewrites a dispatched row's notes, so
        # composing from the in-memory value is correct for the winner (a
        # loser's UPDATE matches zero rows, so its computed value is never
        # persisted).
        values["notes"] = f"{tx.notes or ''}\n[Return] {notes}".strip()

    result = await db.execute(
        update(BorrowTransaction)
        .where(BorrowTransaction.id == tx.id, BorrowTransaction.status == TransactionStatus.OPEN)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def correct_ward(
    db: AsyncSession,
    tx: BorrowTransaction,
    *,
    expected_ward_id: uuid.UUID | None,
    new_ward_id: uuid.UUID,
) -> bool:
    """Conditionally corrects ``ward_id`` and reports whether *this* call is
    the one that applied it. The only path that may change ``ward_id`` on
    an existing row -- mirrors ``close()``'s Roadmap PR8A conditional-UPDATE
    shape (docs/design/PR8_IMPLEMENTATION_PLAN.md's pattern, reused here per
    Roadmap PR9A's concurrency requirement), applied to a different column
    and with no lifecycle involvement whatsoever: this never reads or
    writes ``status``, and operates identically whether the transaction is
    OPEN or CLOSED.

    Emits a single

        UPDATE borrow_transactions
           SET ward_id = :new_ward_id
         WHERE id = :id AND ward_id IS NOT DISTINCT FROM :expected_ward_id

    and decides success by affected-row count, exactly like ``close()``:

      - ``True``  -- this call applied the correction (rowcount == 1): the
        caller's earlier read of ``ward_id`` (``expected_ward_id``) was
        still current at the moment this UPDATE ran, so it is exactly the
        before-value the audit entry must record.
      - ``False`` -- the row's ``ward_id`` was no longer
        ``expected_ward_id`` when this UPDATE ran (rowcount == 0): a
        concurrent correction changed it first. The caller MUST NOT proceed
        to any audit write in that case -- see
        ``app.core.exceptions.WardCorrectionConflictError``.

    ``IS NOT DISTINCT FROM`` (rather than ``=``) is required, not
    cosmetic: ``ward_id`` is nullable (a transaction predating Roadmap
    PR7b's required-ward_id rule may have none), and SQL's ``=`` never
    matches ``NULL`` against anything, including another ``NULL`` -- an
    ordinary ``=`` predicate would make a currently-null ``ward_id`` appear
    to "not match itself," permanently reporting rowcount == 0 (a false
    conflict) for exactly the rows most likely to need a first correction.
    ``BorrowTransaction.ward_id.is_(None)`` still compiles to plain ``IS
    NULL`` when ``expected_ward_id`` is ``None`` via SQLAlchemy's
    ``is_not_distinct_from``, so both the null and non-null cases are
    handled by the same statement. It does **not** mutate or refresh
    ``tx``: like ``close()``, this executes as Core SQL, bypassing the ORM
    unit of work, so a winning caller must ``db.refresh(tx)`` before using
    it for the audit record or the response.
    """
    result = await db.execute(
        update(BorrowTransaction)
        .where(
            BorrowTransaction.id == tx.id,
            BorrowTransaction.ward_id.is_not_distinct_from(expected_ward_id),
        )
        .values(ward_id=new_ward_id)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def list_active(db: AsyncSession) -> list[BorrowTransaction]:
    result = await db.execute(
        select(BorrowTransaction)
        .options(selectinload(BorrowTransaction.equipment))
        .where(BorrowTransaction.status == TransactionStatus.OPEN)
        .order_by(BorrowTransaction.borrowed_at.desc())
    )
    return list(result.scalars().all())


async def search(
    db: AsyncSession,
    *,
    ward_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    equipment_category_id: uuid.UUID | None = None,
    operator_id: uuid.UUID | None = None,
    status: str | None = None,
    dispatch_type: DispatchType | None = None,
    routine_round: RoutineRound | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    shift: Shift | None = None,
    event: Literal["dispatch", "receipt"] = "dispatch",
    require_receipt: bool = False,
    limit: int = 25,
    cursor: str | None = None,
) -> tuple[list[BorrowTransaction], str | None, int]:
    """Roadmap PR13: dispatch_type/routine_round/date-range are history
    filters on top of the existing ward/equipment/status filters -- all
    additive and independently optional, combined with AND like the rest.
    from_date/to_date bound BorrowTransaction.borrowed_at (the dispatch
    date, the only date every transaction has, open or closed) to a
    whole-day-inclusive range.

    Review fix (correctness, not caller-validated here): the upper bound
    is computed as `to_date` at `time.max`, never by adding a day to
    `to_date` -- incrementing a `date` overflows for `date.max`
    (9999-12-31), which callers can send as an ordinary ISO date string.
    `datetime.combine(to_date, time.max)` is always representable for any
    valid `date`, so this bound can never raise. from_date/to_date
    ordering is validated by the caller (app/api/v1/transactions.py)
    before this function is ever called -- search() trusts its inputs,
    consistent with every other filter here.

    Roadmap PR16 Slice 3 (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md
    §8/§9/§11): business_date_from/business_date_to/shift are a distinct
    filter basis from from_date/to_date above -- they compare against the
    *derived* business_date/shift expression (app.core.reporting_time's
    SQL twin), never against datetime.combine-based bounding of the raw
    timestamp. `event` selects which column pair the derivation reads:
    `dispatch` (default) uses `borrowed_at`, `receipt` uses `returned_at`.
    For an open transaction (`returned_at IS NULL`) under `event=receipt`,
    the derived business_date/shift are both NULL, so any non-null
    business_date_from/_to/shift filter naturally excludes that row via
    ordinary SQL NULL-comparison semantics -- no special-case branch is
    needed here for the open-transaction exclusion rule; it is a direct
    consequence of the SQL twin's own NULL-propagation (see
    app.core.reporting_time.business_date_and_shift_sql's docstring/
    comments for the one place that *does* need an explicit NULL branch,
    the `shift` CASE expression). business_date_from/_to ordering is
    validated by the caller before this function is ever called, same as
    from_date/to_date.

    Roadmap PR17 Slice 1 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
    §8/§9/§11): three additive capabilities for the Receive/Issue report
    query functions (app.services.report_query_service) -- none change any
    existing caller's behavior, since GET /transactions never sets any of
    them.

    - `equipment_category_id` filters by `Equipment.category_id` via a
      subquery against `equipment_id`, not a join on the main SELECT --
      keeps the base query's shape (and its `selectinload`) unchanged when
      this filter is not used.
    - `operator_id` filters `borrower_user_id` (event="dispatch") or
      `received_by_user_id` (event="receipt") -- the same event-selected
      column pair the business_date/shift derivation already uses above,
      reused rather than re-decided here.
    - `require_receipt`, when True, unconditionally appends
      `BorrowTransaction.returned_at.is_not(None)` to `filters` --
      independent of whether business_date_from/business_date_to/shift are
      supplied. This is the Receive Report's canonical, always-on
      eligibility predicate (§7.1, corrected per review finding PR17-H1):
      reusing `event="receipt"` alone is not sufficient, because the
      NULL-propagation exclusion above only activates inside the
      business_date/shift branch. Only `search_receive_report()` sets this;
      `GET /transactions` and `search_issue_report()` never do.
    """
    filters = []
    if ward_id is not None:
        filters.append(BorrowTransaction.ward_id == ward_id)
    if equipment_id is not None:
        filters.append(BorrowTransaction.equipment_id == equipment_id)
    if equipment_category_id is not None:
        filters.append(
            BorrowTransaction.equipment_id.in_(
                select(Equipment.id).where(Equipment.category_id == equipment_category_id)
            )
        )
    if operator_id is not None:
        operator_column = (
            BorrowTransaction.borrower_user_id if event == "dispatch" else BorrowTransaction.received_by_user_id
        )
        filters.append(operator_column == operator_id)
    if require_receipt:
        filters.append(BorrowTransaction.returned_at.is_not(None))
    if status is not None:
        filters.append(BorrowTransaction.status == status)
    if dispatch_type is not None:
        filters.append(BorrowTransaction.dispatch_type == dispatch_type)
    if routine_round is not None:
        filters.append(BorrowTransaction.routine_round == routine_round)
    if from_date is not None:
        filters.append(BorrowTransaction.borrowed_at >= datetime.combine(from_date, time.min))
    if to_date is not None:
        filters.append(BorrowTransaction.borrowed_at <= datetime.combine(to_date, time.max))
    if business_date_from is not None or business_date_to is not None or shift is not None:
        event_column = BorrowTransaction.borrowed_at if event == "dispatch" else BorrowTransaction.returned_at
        business_date_expr, shift_expr = business_date_and_shift_sql(event_column)
        if business_date_from is not None:
            filters.append(business_date_expr >= business_date_from)
        if business_date_to is not None:
            filters.append(business_date_expr <= business_date_to)
        if shift is not None:
            filters.append(shift_expr == shift.value)

    count_stmt = select(func.count()).select_from(BorrowTransaction).where(and_(*filters)) if filters else select(
        func.count()
    ).select_from(BorrowTransaction)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(BorrowTransaction).options(selectinload(BorrowTransaction.equipment))
    if filters:
        stmt = stmt.where(and_(*filters))
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                BorrowTransaction.created_at < cursor_dt,
                and_(BorrowTransaction.created_at == cursor_dt, cast(BorrowTransaction.id, String) < cursor_id),
            )
        )
    stmt = stmt.order_by(BorrowTransaction.created_at.desc(), BorrowTransaction.id.desc()).limit(limit + 1)

    rows = list((await db.execute(stmt)).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
        rows = rows[:limit]
    return rows, next_cursor, total
