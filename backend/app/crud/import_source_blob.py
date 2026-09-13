import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_session import ImportSourceBlob

# Roadmap PR20A (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §6.2).
# `import_source_blobs` is 1:1 with `import_sources` -- every write here is
# part of the same uncommitted transaction as the caller's own
# `register_or_correct_source_pending` metadata write (§6.2 step 2(d));
# this module never calls `db.commit()`/`db.rollback()` itself, matching
# every other non-committing CRUD helper in this pipeline.


async def exists_for_source(db: AsyncSession, *, import_source_id: uuid.UUID) -> bool:
    """§6.5: the framework's own signal for whether a registered source has
    verified bytes behind it at all -- used by `run_validation`/
    `run_dry_run` to decide whether to call `ImportSourceReader.open_verified`
    or fall back to the existing PR19A `parse(None)` contract unchanged for
    every dataset_type that doesn't use this storage mechanism (never a
    hardcoded `dataset_type == "equipment_master"` check in shared
    framework code)."""
    subquery = select(ImportSourceBlob.import_source_id).where(ImportSourceBlob.import_source_id == import_source_id)
    return bool((await db.execute(select(subquery.exists()))).scalar_one())


async def upsert_pending(db: AsyncSession, *, import_source_id: uuid.UUID, content: bytes) -> None:
    """§6.2 step 2(d): an upsert/replace-if-exists write, matching
    `register_or_correct_source_pending`'s own idempotent "register-or-
    correct" semantics -- a client retry (identical or corrected bytes,
    before the source freezes) never creates a second blob row. Does not
    flush or commit; the caller's own single `db.commit()` (§6.2 step
    2(e)) finalizes this write together with the source-metadata row in
    one physical transaction."""
    dialect_name = db.get_bind().dialect.name
    insert_fn = pg_insert if dialect_name == "postgresql" else sqlite_insert
    stmt = insert_fn(ImportSourceBlob).values(import_source_id=import_source_id, content=content)
    stmt = stmt.on_conflict_do_update(index_elements=[ImportSourceBlob.import_source_id], set_={"content": content})
    await db.execute(stmt)


async def get_content(db: AsyncSession, *, import_source_id: uuid.UUID) -> bytes | None:
    """§6.5 step 1: loads the blob referenced by `import_source_id`. `None`
    means no row exists -- the caller (`ImportSourceReader.open_verified`)
    is responsible for raising `SourceBlobMissingError`, not this
    function, which stays a plain read with no domain-error knowledge."""
    stmt = select(ImportSourceBlob.content).where(ImportSourceBlob.import_source_id == import_source_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_for_source(db: AsyncSession, *, import_source_id: uuid.UUID) -> None:
    """§6.6: one additional statement inside the same transaction as
    PR19A's existing `redact_session` redaction `UPDATE`s -- never a
    second retention mechanism, never its own commit. A no-op if no blob
    row exists (already purged, or the source never had one)."""
    await db.execute(delete(ImportSourceBlob).where(ImportSourceBlob.import_source_id == import_source_id))
