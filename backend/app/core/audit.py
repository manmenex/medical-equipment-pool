"""Reusable audit-logging framework.

`record_audit_event` is the single entry point every call site (auth,
master data, equipment, and future roadmap PRs) should use to write an
audit row. It always goes through `app.crud.audit.create`, which only
flushes (never commits) — the caller's own transaction/commit decides
whether the audit row and the business change land together, so a
failure anywhere in that transaction rolls both back.

Authentication events (login/logout/refresh) are the one exception to
that atomicity: they use `record_best_effort_audit_event` instead, so a
transient audit-write failure can never turn a legitimate authentication
attempt into a 500 — see that function's docstring for the rationale.
"""

import logging
import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import audit as audit_crud
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)

# Audit action values — stable, machine-readable constants. Every call site
# uses one of these instead of an inline string literal, so the set of
# valid actions is discoverable and typo-proof in one place.
AUDIT_ACTION_CREATE = "create"
AUDIT_ACTION_UPDATE = "update"
AUDIT_ACTION_DELETE = "delete"
AUDIT_ACTION_STATUS_CHANGE = "status_change"
AUDIT_ACTION_LOGIN_SUCCESS = "login_success"
AUDIT_ACTION_LOGIN_FAILURE = "login_failure"
AUDIT_ACTION_LOGOUT = "logout"
AUDIT_ACTION_TOKEN_REFRESH = "token_refresh"

# Audit entity-type values, same rationale as the actions above.
AUDIT_ENTITY_EQUIPMENT = "equipment"
AUDIT_ENTITY_USER = "user"
AUDIT_ENTITY_DEPARTMENT = "department"
AUDIT_ENTITY_WARD = "ward"
AUDIT_ENTITY_LOCATION = "location"
AUDIT_ENTITY_CATEGORY = "category"
AUDIT_ENTITY_AUTH = "auth"

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
    "authorization",
    "cookie",
    "private_key",
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


# audit_logs.user_agent is String(255) and client-controlled (an arbitrary
# request header) — never persisted unbounded or unsanitized.
_MAX_USER_AGENT_LENGTH = 255


def _sanitize_user_agent(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    if not cleaned:
        return None
    return cleaned[:_MAX_USER_AGENT_LENGTH]


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
    # request.client.host only — never a forwarded-for header, since this
    # deployment has no configured trusted-proxy chain to validate one
    # against (see ARCHITECTURE_DECISIONS.md, "Managed deployment
    # preferred": no fixed proxy topology is assumed yet).
    ip_address = request.client.host if request is not None and request.client else None
    user_agent = _sanitize_user_agent(request.headers.get("user-agent")) if request is not None else None
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


async def record_best_effort_audit_event(db: AsyncSession, **kwargs) -> None:
    """Authentication-event audit write that must never block authentication.

    Business-mutation audit writes (record_audit_event, used by master
    data and equipment) are deliberately mandatory: a failure there rolls
    back the business change, because the two are supposed to be one
    atomic unit of work. Authentication events are different — there is
    often no other business row to be atomic with, and a transient
    audit-subsystem failure must not be able to lock a legitimate user out
    of a working system. So this wraps the write in a SAVEPOINT: on
    success the audit row joins the caller's pending transaction exactly
    like record_audit_event's would; on failure it is rolled back to the
    savepoint (leaving the rest of the caller's transaction usable) and
    the failure is logged server-side, but never re-raised.
    """
    try:
        async with db.begin_nested():
            await record_audit_event(db, **kwargs)
    except Exception:
        logger.warning(
            "Failed to record authentication audit event (action=%s); "
            "continuing without blocking the authentication flow",
            kwargs.get("action"),
            exc_info=True,
        )


async def commit_best_effort(db: AsyncSession) -> None:
    """Commits an authentication-event transaction — the other half of the
    same best-effort boundary as record_best_effort_audit_event().

    That function only protects the audit *write* (inside its own
    SAVEPOINT); the caller's subsequent `db.commit()` sits outside that
    boundary, so a commit-time failure (e.g. a dropped connection) could
    still propagate and turn an already-decided authentication outcome — a
    successful login/logout/refresh, or a login failure about to raise
    InvalidCredentialsError — into an unrelated 500. This catches that too:
    on failure the session is rolled back so it's left usable, and the
    failure is logged server-side, but never re-raised. By the time this
    runs, the only pending changes are the audit row (and, for a successful
    login, last_login_at) — there is no other business validation left to
    protect, so making the commit itself best-effort here is safe.
    """
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning(
            "Failed to commit authentication audit transaction; "
            "continuing without blocking the authentication flow",
            exc_info=True,
        )
