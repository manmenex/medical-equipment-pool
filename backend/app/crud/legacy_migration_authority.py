"""Roadmap PR21D1 (design doc §55.6, §11-§12 of the PR21D1 task). Minimal,
read-only lookup for `LegacyMigrationAuthority` (Roadmap PR21A schema,
`app.models.legacy_history`) by its approved workbook checksum.

**Deliberately no `create`/`approve` function here.** PR21D1's own scope
guard (§25 "No PR21 frontend implementation", §72) and its explicit
instruction not to "invent a hidden global singleton" (§12) both rule out
building an approval workflow as a side effect of this validation slice.
The combined adapter's own checksum-authority gate (§55.6/§11) is
therefore **fail-closed by construction**: if no `LegacyMigrationAuthority`
row exists for the active `ImportSource`'s checksum, validation/dry-run
must reject the attempt, never silently create one. Tests seed a row
directly (mirroring PR21A's own test convention); production requires a
separate, explicitly-scoped Administrator-facing creation path that does
not yet exist -- see this PR's own final report for that discovered,
un-implemented gap."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
