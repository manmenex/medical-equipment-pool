import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidInputError


async def ensure_referenced_row_exists(
    db: AsyncSession, model: type, id_value: uuid.UUID | None, *, field_name: str
) -> None:
    """Validate a foreign-key reference exists before flush, where practical.

    Raises the same 400 InvalidInputError used for a foreign-key violation
    caught at flush time (see app.core.db_errors), so a missing reference
    gets a consistent response whether it's caught here (proactively, and
    the only mechanism that works against SQLite, which doesn't enforce FK
    constraints by default) or by the database itself (Postgres).

    `id_value=None` is treated as "not provided" and passes silently — the
    referenced fields this is used for are all optional.
    """
    if id_value is None:
        return
    exists = await db.scalar(select(model.id).where(model.id == id_value))
    if exists is None:
        raise InvalidInputError(f"'{field_name}' does not reference an existing resource.")
