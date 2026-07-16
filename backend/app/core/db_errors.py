import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import Enum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, DuplicateError, InvalidInputError

logger = logging.getLogger(__name__)

# PostgreSQL SQLSTATE codes for the integrity_constraint_violation class we
# distinguish. See https://www.postgresql.org/docs/current/errcodes-appendix.html
# asyncpg's own exception classes expose a `.sqlstate` attribute on `exc.orig`
# with exactly these values, so this is a structured check, not string parsing.
SQLSTATE_UNIQUE_VIOLATION = "23505"
SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
SQLSTATE_NOT_NULL_VIOLATION = "23502"
SQLSTATE_CHECK_VIOLATION = "23514"


class IntegrityViolationKind(str, Enum):
    UNIQUE = "unique"
    FOREIGN_KEY = "foreign_key"
    NOT_NULL = "not_null"
    CHECK = "check"
    UNKNOWN = "unknown"


def _classify(exc: IntegrityError) -> IntegrityViolationKind:
    """Classify an IntegrityError using the driver's structured error code.

    Preferred path: PostgreSQL SQLSTATE (asyncpg exposes this directly on
    the original exception, no string parsing involved).

    Fallback path (SQLite and any driver with no SQLSTATE): SQLite's
    sqlite3 module does not expose a structured error code for IntegrityError
    subtypes at all, so distinguishing them is only possible by checking the
    fixed, driver-generated prefix of the message (not the whole message,
    and never anything client-supplied). This text is used only to pick a
    classification server-side — it is never included in the response.
    """
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == SQLSTATE_UNIQUE_VIOLATION:
        return IntegrityViolationKind.UNIQUE
    if sqlstate == SQLSTATE_FOREIGN_KEY_VIOLATION:
        return IntegrityViolationKind.FOREIGN_KEY
    if sqlstate == SQLSTATE_NOT_NULL_VIOLATION:
        return IntegrityViolationKind.NOT_NULL
    if sqlstate == SQLSTATE_CHECK_VIOLATION:
        return IntegrityViolationKind.CHECK
    if sqlstate is not None:
        # A SQLSTATE we don't specifically handle (e.g. exclusion_violation,
        # 23P01) — safe generic fallback rather than guessing.
        return IntegrityViolationKind.UNKNOWN

    message = str(exc.orig) if exc.orig is not None else ""
    if "UNIQUE constraint failed" in message:
        return IntegrityViolationKind.UNIQUE
    if "FOREIGN KEY constraint failed" in message:
        return IntegrityViolationKind.FOREIGN_KEY
    if "NOT NULL constraint failed" in message:
        return IntegrityViolationKind.NOT_NULL
    if "CHECK constraint failed" in message:
        return IntegrityViolationKind.CHECK
    return IntegrityViolationKind.UNKNOWN


@asynccontextmanager
async def translate_integrity_error(db: AsyncSession, *, resource: str) -> AsyncIterator[None]:
    """Catch IntegrityError from the wrapped block, roll back, and raise a safe DomainError.

    `resource` is a short, safe, human-readable label (e.g. "department",
    "equipment") used to build a generic message — never the raw database
    error text, constraint name, SQL, or SQL parameters.

    Classification contract (documented, consistent across every call site):
      - unique_violation      -> 409 DuplicateError      (code DUPLICATE)
      - foreign_key_violation -> 400 InvalidInputError    (code INVALID_INPUT)
      - not_null/check        -> 400 InvalidInputError    (code INVALID_INPUT)
      - unclassifiable        -> 409 ConflictError         (code CONFLICT)

    Foreign key violations map to 400, not 404: the resource actually being
    created/updated is not itself missing — a field within the request
    references a related resource that does not exist, which is a client
    input problem. This is the same contract used by the pre-flush
    existence checks in app.core.references, so a bad reference is always
    400 INVALID_INPUT regardless of whether it's caught before or during
    the flush.

    The session is rolled back before the translated error is raised, so
    nothing in this request can reuse it in a failed-transaction state. The
    original IntegrityError (which may include raw SQL/constraint text) is
    preserved via exception chaining for server-side logs only — the
    generated message is the only text that ever reaches the client.
    """
    try:
        yield
    except IntegrityError as exc:
        await db.rollback()
        kind = _classify(exc)
        logger.info(
            "Integrity error on resource=%s classified as %s (driver_exc=%s)",
            resource,
            kind.value,
            type(exc.orig).__name__ if exc.orig is not None else "unknown",
        )
        if kind is IntegrityViolationKind.UNIQUE:
            raise DuplicateError(f"A {resource} with this identifier already exists.") from exc
        if kind is IntegrityViolationKind.FOREIGN_KEY:
            raise InvalidInputError(f"This {resource} references another resource that does not exist.") from exc
        if kind in (IntegrityViolationKind.NOT_NULL, IntegrityViolationKind.CHECK):
            raise InvalidInputError(f"The submitted {resource} data is invalid.") from exc
        raise ConflictError(f"Unable to process this {resource} due to a data conflict.") from exc
