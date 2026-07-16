import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

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


async def authenticate(db: AsyncSession, identifier: str, password: str) -> tuple[User, Role, str, str]:
    user = await user_crud.get_by_identifier(db, identifier)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid employee code/email or password")

    role_result = await db.get(Role, user.role_id)
    role = role_result
    if role is None:
        raise InvalidCredentialsError("User has no assigned role")

    user.last_login_at = datetime.utcnow()
    await db.commit()

    access_token = create_access_token(str(user.id), role.name)
    refresh_token = create_refresh_token(str(user.id))
    refresh_payload = decode_token(refresh_token)
    await store_refresh_token(
        refresh_payload["jti"], str(user.id), ttl_seconds=settings.JWT_REFRESH_EXPIRE_DAYS * 24 * 3600
    )
    return user, role, access_token, refresh_token


async def refresh_access_token(db: AsyncSession, refresh_token: str | None) -> str:
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

    return create_access_token(user_id, role.name)


async def logout(refresh_token: str | None) -> None:
    if not refresh_token:
        return
    try:
        payload = decode_token(refresh_token)
        await revoke_refresh_token(payload["jti"])
    except Exception:
        pass
