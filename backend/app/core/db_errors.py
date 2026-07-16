import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def translate_integrity_error(db: AsyncSession, message: str) -> AsyncIterator[None]:
    """Catch IntegrityError from the wrapped block, roll back, and raise DuplicateError.

    The session is rolled back before the translated error is raised, so
    nothing in this request can reuse it in a failed-transaction state. The
    original IntegrityError (which may include raw SQL/constraint text) is
    preserved via exception chaining for server-side logs only — `message`
    is the only text that ever reaches the client.
    """
    try:
        yield
    except IntegrityError as exc:
        await db.rollback()
        logger.info("Integrity error translated to DUPLICATE: %s", type(exc.orig).__name__ if exc.orig else "unknown")
        raise DuplicateError(message) from exc
