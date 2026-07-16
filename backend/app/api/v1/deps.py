from collections.abc import Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import Role, User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    request.state.current_user = user
    return user


async def get_current_role_name(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> str:
    result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = result.scalar_one_or_none()
    return role.name if role else ""


def require_roles(*allowed_roles: str) -> Callable:
    async def checker(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        result = await db.execute(select(Role).where(Role.id == user.role_id))
        role = result.scalar_one_or_none()
        if role is None or role.name not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return checker


class PaginationParams:
    def __init__(self, limit: int = 25, cursor: str | None = None):
        self.limit = max(1, min(limit, 200))
        self.cursor = cursor
