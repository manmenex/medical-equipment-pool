"""Roadmap PR21E0 -- Legacy Import Operator API Surface. Request/response
contracts for `POST/GET /api/v1/legacy-migration-authorities`.

**Scope policy (§6 of the task).** `LegacyMigrationAuthority.scope` stays a
free-text column at the model/database level (PR21A's own design already
anticipates more than one governance identity over time, §24.2) -- but the
public API deliberately narrows what a caller may *submit* to a closed
allowlist, never arbitrary free text. PR21 V1 has exactly one approved
scope; `LEGACY_MIGRATION_AUTHORITY_SCOPES` is that allowlist, extended
later only by an explicit, separately-authorized governance decision --
never by relaxing this schema ad hoc."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import UUIDStr

LEGACY_MIGRATION_AUTHORITY_SCOPES = ("pr21_legacy_transaction_history_v1",)

LegacyMigrationAuthorityScope = Literal["pr21_legacy_transaction_history_v1"]


def normalize_checksum(raw: str) -> str:
    """§21 of the task: one canonical storage/input policy -- lowercase
    hex, exactly 64 characters, safe surrounding whitespace stripped.
    Raises `ValueError` (never a domain exception directly -- callers
    decide how to surface that: Pydantic turns it into a structured `422`
    automatically when used as a `field_validator`; the query-param GET
    endpoint wraps it into `InvalidInputError` itself, a plain `400`)."""
    normalized = raw.strip().lower()
    if len(normalized) != 64:
        raise ValueError("approved_workbook_sha256 must be exactly 64 hex characters.")
    if any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError("approved_workbook_sha256 must contain only hexadecimal characters.")
    return normalized


class LegacyMigrationAuthorityCreate(BaseModel):
    """§3/§4 of the task. Deliberately excludes `approved_by_user_id`/
    `approved_at`/`created_at`/`id` -- those come from the authenticated
    actor and the server clock, never the request body."""

    scope: LegacyMigrationAuthorityScope
    approved_workbook_sha256: str = Field(min_length=1, max_length=200)

    @field_validator("approved_workbook_sha256")
    @classmethod
    def _validate_checksum(cls, value: str) -> str:
        try:
            return normalize_checksum(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class LegacyMigrationAuthorityOut(BaseModel):
    id: UUIDStr
    scope: str
    approved_workbook_sha256: str
    approved_by_user_id: UUIDStr
    approved_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
