import uuid
from datetime import datetime

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
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
        await record_audit_event(
            db,
            actor_user_id=user.id if user is not None else None,
            action="login_failure",
            entity_type="auth",
            entity_id=user.id if user is not None else None,
            after={"identifier": identifier},
            request=request,
        )
        await db.commit()
        raise InvalidCredentialsError("Invalid employee code/email or password")

    role_result = await db.get(Role, user.role_id)
    role = role_result
    if role is None:
        raise InvalidCredentialsError("User has no assigned role")

    user.last_login_at = datetime.utcnow()
    await record_audit_event(
        db,
        actor_user_id=user.id,
        action="login_success",
        entity_type="auth",
        entity_id=user.id,
        request=request,
    )
    # Audit row and last_login_at share this one commit: if the audit
    # write's flush above failed, it would have raised before we got here
    # and neither change would be persisted.
    await db.commit()

    access_token = create_access_token(str(user.id), role.name)
    refresh_token = create_refresh_token(str(user.id))
    refresh_payload = decode_token(refresh_token)
    await store_refresh_token(
        refresh_payload["jti"], str(user.id), ttl_seconds=settings.JWT_REFRESH_EXPIRE_DAYS * 24 * 3600
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

    await record_audit_event(
        db,
        actor_user_id=user.id,
        action="token_refresh",
        entity_type="auth",
        entity_id=user.id,
        request=request,
    )
    await db.commit()

    return create_access_token(user_id, role.name)


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

    await record_audit_event(
        db,
        actor_user_id=actor_user_id,
        action="logout",
        entity_type="auth",
        entity_id=actor_user_id,
        request=request,
    )
    await db.commit()
