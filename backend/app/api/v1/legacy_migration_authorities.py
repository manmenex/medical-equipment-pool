"""Roadmap PR21E0 -- Legacy Import Operator API Surface. Closes gap A
(§3-§11 of the task): an Administrator-facing API to explicitly approve a
workbook checksum as a `LegacyMigrationAuthority` -- the production write
path PR21D1 deliberately left unbuilt (see
`app.crud.legacy_migration_authority`'s own module docstring)."""

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, require_roles
from app.core.audit import AUDIT_ACTION_LEGACY_MIGRATION_AUTHORITY_APPROVED, AUDIT_ENTITY_LEGACY_MIGRATION_AUTHORITY, record_audit_event
from app.core.exceptions import InvalidInputError, LegacyMigrationAuthorityNotFoundError
from app.crud import legacy_migration_authority as legacy_migration_authority_crud
from app.db.session import get_db
from app.schemas.legacy_migration_authority import (
    LegacyMigrationAuthorityCreate,
    LegacyMigrationAuthorityOut,
    normalize_checksum,
)

router = APIRouter(prefix="/legacy-migration-authorities", tags=["legacy-migration-authorities"])


@router.post("", response_model=LegacyMigrationAuthorityOut)
async def approve_legacy_migration_authority(
    payload: LegacyMigrationAuthorityCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """§3-§5/§9/§10 of the task. Administrator-only, explicit governance
    action -- never invoked implicitly by validation/dry-run/execute
    (`app.crud.legacy_migration_authority.get_by_checksum` remains the
    only lookup those call sites ever use). Idempotent: a retry with the
    identical `(scope, approved_workbook_sha256)` returns the original
    row unchanged (`200`, same `approved_by_user_id`/`approved_at`) --
    only a genuine first creation returns `201` and writes exactly one
    audit event."""
    authority, created = await legacy_migration_authority_crud.create_or_get_approval(
        db,
        scope=payload.scope,
        approved_workbook_sha256=payload.approved_workbook_sha256,
        actor_id=actor.id,
    )
    if created:
        await record_audit_event(
            db,
            actor_user_id=actor.id,
            action=AUDIT_ACTION_LEGACY_MIGRATION_AUTHORITY_APPROVED,
            entity_type=AUDIT_ENTITY_LEGACY_MIGRATION_AUTHORITY,
            entity_id=authority.id,
            after={
                "scope": authority.scope,
                "approved_workbook_sha256": authority.approved_workbook_sha256,
            },
            request=request,
        )
    await db.commit()
    response.status_code = 201 if created else 200
    return authority


@router.get("/{authority_id}", response_model=LegacyMigrationAuthorityOut)
async def get_legacy_migration_authority(
    authority_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    authority = await legacy_migration_authority_crud.get_by_id(db, authority_id=authority_id)
    if authority is None:
        raise LegacyMigrationAuthorityNotFoundError(f"Legacy migration authority '{authority_id}' not found.")
    return authority


@router.get("", response_model=LegacyMigrationAuthorityOut)
async def find_legacy_migration_authority_by_checksum(
    checksum: str = Query(min_length=1, max_length=200),
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """§7 of the task: the minimum an operator/frontend genuinely needs --
    "is this checksum already approved, and what authority owns it?"
    Deliberately requires `checksum` (never a bare listing of every
    authority) -- avoids exposing unrelated approvals beyond what the
    caller already knows to ask about."""
    try:
        normalized = normalize_checksum(checksum)
    except ValueError as exc:
        raise InvalidInputError(str(exc)) from exc
    authority = await legacy_migration_authority_crud.get_by_checksum(db, approved_workbook_sha256=normalized)
    if authority is None:
        raise LegacyMigrationAuthorityNotFoundError(f"No legacy migration authority approved for this checksum.")
    return authority
