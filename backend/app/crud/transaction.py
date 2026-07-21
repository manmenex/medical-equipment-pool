import uuid
from datetime import datetime

from sqlalchemy import String, and_, cast, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transaction import BorrowTransaction, TransactionStatus
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
    condition_on_return: str,
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
    """
    values: dict = {
        "status": TransactionStatus.CLOSED,
        "returned_at": datetime.utcnow(),
        "condition_on_return": condition_on_return,
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
    status: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> tuple[list[BorrowTransaction], str | None, int]:
    filters = []
    if ward_id is not None:
        filters.append(BorrowTransaction.ward_id == ward_id)
    if equipment_id is not None:
        filters.append(BorrowTransaction.equipment_id == equipment_id)
    if status is not None:
        filters.append(BorrowTransaction.status == status)

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
