"""Reusable audit-logging framework.

`record_audit_event` is the single entry point every call site (auth,
master data, equipment, and future roadmap PRs) should use to write an
audit row. It always goes through `app.crud.audit.create`, which only
flushes (never commits) — the caller's own transaction/commit decides
whether the audit row and the business change land together, so a
failure anywhere in that transaction rolls both back.
"""

import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import audit as audit_crud
from app.models.audit import AuditLog

# Substrings matched case-insensitively against JSON keys in before/after
# payloads. Deliberately broad (e.g. "token" covers access_token,
# refresh_token, jti-adjacent fields) since an audit row is a permanent
# record — a false-positive redaction is far cheaper than a leaked secret.
_SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "jwt",
    "api_key",
    "apikey",
)

_MASK = "***REDACTED***"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def redact_sensitive(data):
    """Recursively mask sensitive values in a dict/list before persistence."""
    if isinstance(data, dict):
        return {
            key: (_MASK if _is_sensitive_key(key) else redact_sensitive(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact_sensitive(item) for item in data]
    return data


async def record_audit_event(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    before: dict | None = None,
    after: dict | None = None,
    request: Request | None = None,
) -> AuditLog:
    ip_address = request.client.host if request is not None and request.client else None
    user_agent = request.headers.get("user-agent") if request is not None else None
    request_id = getattr(request.state, "request_id", None) if request is not None else None
    correlation_id = getattr(request.state, "correlation_id", None) if request is not None else None

    return await audit_crud.create(
        db,
        user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=redact_sensitive(before),
        after_data=redact_sensitive(after),
        request_id=request_id,
        correlation_id=correlation_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
