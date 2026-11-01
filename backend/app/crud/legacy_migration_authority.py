"""Roadmap PR21D1 (design doc §55.6, §11-§12 of the PR21D1 task) /
PR21E0 (Legacy Import Operator API Surface). Lookup and idempotent
approval for `LegacyMigrationAuthority` (Roadmap PR21A schema,
`app.models.legacy_history`).

**PR21D1's own read-only-only scope is now explicitly superseded by
PR21E0.** PR21D1 deliberately shipped no `create`/`approve` function
here (its own scope guard, §25/§72 of that task, ruled out building an
approval workflow as a side effect of a validation slice) -- production
therefore had no way to create the first `LegacyMigrationAuthority` row
outside a test fixture, a discovered and honestly-reported gap. PR21E0
(§3-§11 of its own task) is the separately-authorized slice that closes
it: `create_or_get_approval` below is the sole production write path for
this table, gated Administrator-only at the API layer
(`app.api.v1.legacy_migration_authorities`), and still fail-closed by
construction -- there is no auto-create path anywhere else in this
codebase (the combined adapter's own checksum gate, `get_by_checksum`
below, is unchanged)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LegacyMigrationAuthorityScopeConflictError
from app.models.legacy_history import LegacyMigrationAuthority


async def get_by_checksum(db: AsyncSession, *, approved_workbook_sha256: str) -> LegacyMigrationAuthority | None:
    """Exact-match lookup only -- `approved_workbook_sha256` is unique
    (`uq_legacy_migration_authorities_checksum`), so at most one row can
    ever match."""
    return (
        await db.execute(
            select(LegacyMigrationAuthority).where(
                LegacyMigrationAuthority.approved_workbook_sha256 == approved_workbook_sha256
            )
        )
    ).scalar_one_or_none()


async def get_by_id(db: AsyncSession, *, authority_id: uuid.UUID) -> LegacyMigrationAuthority | None:
    return await db.get(LegacyMigrationAuthority, authority_id)


async def create_or_get_approval(
    db: AsyncSession, *, scope: str, approved_workbook_sha256: str, actor_id: uuid.UUID
) -> tuple[LegacyMigrationAuthority, bool]:
    """Roadmap PR21E0 (design §5/§10). Race-safe via
    INSERT-then-catch-IntegrityError-then-requery -- mirrors
    `app.crud.import_session.get_or_create_session`'s own established
    pattern, never a `SELECT`-before-`INSERT` (a genuine race between the
    pre-check and the insert would still be possible with that shape;
    this codebase's own precedent avoids it structurally).

    **PR #109 P1 fix round -- transaction ownership.** The conflict-prone
    `INSERT` runs inside its own `db.begin_nested()` SAVEPOINT rather than
    the caller's outer transaction directly. This CRUD helper does not
    own the caller's transaction (the route handler does, committing
    once after this call returns) -- a plain `await db.rollback()` on
    `IntegrityError` would discard the *entire* outer transaction,
    including any unrelated work the caller staged before calling this
    function (the same transaction-ownership class PR90-H1 fixed for
    source registration). `begin_nested()`'s own `__aexit__` rolls back
    only the SAVEPOINT when the `flush()` inside it raises, leaving the
    outer transaction -- and everything already staged on it -- fully
    intact and usable for the requery below and any further caller work.

    - No existing row for this checksum: the insert succeeds, `created`
      is `True`.
    - An existing row already carries this exact checksum (a retry, or a
      genuinely concurrent identical approval that committed first): the
      insert's own `IntegrityError` triggers a requery; if the existing
      row's `scope` matches, it is returned unchanged (`created=False`)
      -- `approved_by_user_id`/`approved_at` are never rewritten, so the
      *original* approver and timestamp always survive every retry.
    - An existing row carries this exact checksum under a *different*
      `scope`: `LegacyMigrationAuthorityScopeConflictError` (`409`) --
      never silently reinterpreted, never overwritten. Raised from
      *outside* the nested transaction (the SAVEPOINT has already been
      released by the time this is raised), so it never leaves the
      session in a failed-transaction state the caller can't use.

    Returns `(authority, created)`."""
    authority = LegacyMigrationAuthority(
        scope=scope, approved_workbook_sha256=approved_workbook_sha256, approved_by_user_id=actor_id
    )
    try:
        async with db.begin_nested():
            db.add(authority)
            await db.flush()
    except IntegrityError:
        existing = await get_by_checksum(db, approved_workbook_sha256=approved_workbook_sha256)
        if existing is None:
            # A different, unrelated integrity failure (e.g. a bad FK on
            # actor_id) -- never masked as a scope conflict.
            raise
        if existing.scope != scope:
            raise LegacyMigrationAuthorityScopeConflictError(
                f"Checksum '{approved_workbook_sha256}' is already approved under scope "
                f"'{existing.scope}' -- cannot also approve it under '{scope}'."
            )
        return existing, False
    return authority, True
