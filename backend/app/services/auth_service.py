import uuid
from datetime import datetime

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import (
    AUDIT_ACTION_LOGIN_FAILURE,
    AUDIT_ACTION_LOGIN_SUCCESS,
    AUDIT_ACTION_LOGOUT,
    AUDIT_ACTION_TOKEN_REFRESH,
    AUDIT_ENTITY_AUTH,
    commit_best_effort,
    record_best_effort_audit_event,
)
from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.redis import is_refresh_token_valid, revoke_refresh_token, store_refresh_token
from app.core.security import create_access_token, create_refresh_token, decode_token, verify_password
from app.crud import user as user_crud
from app.models.user import Role, User


class InvalidCredentialsError(DomainError):
    code = "INVALID_CREDENTIALS"
    status_code = 401


class InvalidRefreshTokenError(DomainError):
    code = "INVALID_REFRESH_TOKEN"
    status_code = 401


async def authenticate(
    db: AsyncSession, identifier: str, password: str, *, request: Request | None = None
) -> tuple[User, Role, str, str]:
    user = await user_crud.get_by_identifier(db, identifier)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        # Per ADR-0001: the actor is never the authentication target — a
        # failed login has no authenticated actor, known account or not.
        # A known account may be recorded as the *subject* (entity_id);
        # an unknown submitted identifier is never persisted in any form
        # (not raw, not a deterministic hash, not any other enumerable or
        # correlatable representation) — a low-entropy identifier like an
        # employee code or email remains dictionary-guessable even hashed.
        await record_best_effort_audit_event(
            db,
            actor_user_id=None,
            action=AUDIT_ACTION_LOGIN_FAILURE,
            entity_type=AUDIT_ENTITY_AUTH,
            entity_id=user.id if user is not None else None,
            request=request,
        )
        await commit_best_effort(db)
        raise InvalidCredentialsError("Invalid employee code/email or password")

    role_result = await db.get(Role, user.role_id)
    role = role_result
    if role is None:
        raise InvalidCredentialsError("User has no assigned role")

    user.last_login_at = datetime.utcnow()
    # Best-effort across the whole persistence boundary — both the audit
    # write (record_best_effort_audit_event's own SAVEPOINT) and this
    # commit (commit_best_effort) — must not block a legitimate login. If
    # either fails, last_login_at and/or the audit row may not persist, but
    # token issuance below never depends on this commit succeeding.
    await record_best_effort_audit_event(
        db,
        actor_user_id=user.id,
        action=AUDIT_ACTION_LOGIN_SUCCESS,
        entity_type=AUDIT_ENTITY_AUTH,
        entity_id=user.id,
        request=request,
    )
    # Read everything token issuance needs from the ORM objects *before*
    # commit_best_effort() — a commit-time failure there rolls back the
    # session, which expires every attribute on `user`/`role` and would
    # otherwise turn a legitimate login into a MissingGreenlet 500 the
    # instant those attributes are next touched.
    user_id_str = str(user.id)
    role_name = role.name
    await commit_best_effort(db)

    access_token = create_access_token(user_id_str, role_name)
    refresh_token = create_refresh_token(user_id_str)
    refresh_payload = decode_token(refresh_token)
    await store_refresh_token(
        refresh_payload["jti"], user_id_str, ttl_seconds=settings.JWT_REFRESH_EXPIRE_DAYS * 24 * 3600
    )
    return user, role, access_token, refresh_token


async def refresh_access_token(
    db: AsyncSession, refresh_token: str | None, *, request: Request | None = None
) -> str:
    if not refresh_token:
        raise InvalidRefreshTokenError("Missing refresh token")
    try:
        payload = decode_token(refresh_token)
    except Exception as exc:
        raise InvalidRefreshTokenError("Invalid or expired refresh token") from exc

    if payload.get("type") != "refresh":
        raise InvalidRefreshTokenError("Invalid token type")

    user_id = payload["sub"]
    if not await is_refresh_token_valid(payload["jti"], user_id):
        raise InvalidRefreshTokenError("Refresh token has been revoked")

    try:
        user = await user_crud.get_by_id(db, uuid.UUID(user_id))
    except (ValueError, TypeError) as exc:
        # The "sub" claim is only ever set by this app's own create_refresh_token
        # (see app.core.security), so a malformed value here indicates token
        # corruption rather than user input — treated the same as any other
        # invalid refresh token, not a generic 400.
        raise InvalidRefreshTokenError("Invalid or expired refresh token") from exc
    if user is None or not user.is_active:
        raise InvalidRefreshTokenError("User not found or inactive")

    role = await db.get(Role, user.role_id)
    if role is None:
        raise InvalidRefreshTokenError("User has no assigned role")

    # Best-effort, same rationale as login: preserve current authentication
    # response behavior — an audit-write or commit-time hiccup must not
    # turn a valid refresh into a failure.
    await record_best_effort_audit_event(
        db,
        actor_user_id=user.id,
        action=AUDIT_ACTION_TOKEN_REFRESH,
        entity_type=AUDIT_ENTITY_AUTH,
        entity_id=user.id,
        request=request,
    )
    # See the identical comment in authenticate(): read role.name before
    # commit_best_effort() can roll back and expire it.
    role_name = role.name
    await commit_best_effort(db)

    return create_access_token(user_id, role_name)


async def logout(db: AsyncSession, refresh_token: str | None, *, request: Request | None = None) -> None:
    if not refresh_token:
        return
    actor_user_id: uuid.UUID | None = None
    try:
        payload = decode_token(refresh_token)
        await revoke_refresh_token(payload["jti"])
        actor_user_id = uuid.UUID(payload["sub"])
    except Exception:
        pass

    # Best-effort, same rationale as login/refresh.
    await record_best_effort_audit_event(
        db,
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_LOGOUT,
        entity_type=AUDIT_ENTITY_AUTH,
        entity_id=actor_user_id,
        request=request,
    )
    await commit_best_effort(db)
