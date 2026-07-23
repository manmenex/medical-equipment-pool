from collections.abc import Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import ROLE_ADMIN, ROLE_TRANSPORT_STAFF, ROLE_WARD_NURSE, Role, User

bearer_scheme = HTTPBearer(auto_error=False)

# RFC 7235 says a 401 response SHOULD include WWW-Authenticate; every 401
# raised for this bearer scheme carries the same challenge.
WWW_AUTHENTICATE_HEADERS = {"WWW-Authenticate": "Bearer"}


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated", headers=WWW_AUTHENTICATE_HEADERS
        )
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers=WWW_AUTHENTICATE_HEADERS,
            )
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers=WWW_AUTHENTICATE_HEADERS,
        ) from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers=WWW_AUTHENTICATE_HEADERS,
        )
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


# Roadmap PR9A (docs/audits/03-hospital-equipment-pool-workflow-audit.md §10
# "Role and Permission Review"): the confirmed 3-role permission matrix
# grants the ward-correction capability to Administrator and Equipment Pool
# Staff, and denies it to Read-Only/Supervisor. Roadmap PR10 ("Role Model
# Consolidation") owns replacing the current 5-role model
# (app.models.user.ALL_ROLES) with that 3-role model everywhere -- this PR
# must not perform that migration, rename/remove any existing role, or grant
# the capability to every authenticated user.
#
# Until PR10 lands, this is the narrowest defensible mapping of *existing*
# roles onto "Equipment Pool Staff": the same population the current code
# already trusts to dispatch and receive equipment themselves
# (app.api.v1.borrow.BORROW_ROLES) -- i.e. the role set that already stands
# in for "Equipment Pool Staff" under the pre-PR10 model, per the workflow
# audit's own framing ("all system interaction -- dispatch, collection,
# cleaning confirmation -- is performed by Equipment Pool staff"). Excludes
# ROLE_VIEWER (the Read-Only/Supervisor equivalent, per the confirmed
# matrix) and ROLE_BIOMEDICAL_ENGINEER (not confirmed as an "Equipment Pool
# Staff" equivalent by the workflow audit's §10 note; granting this
# capability more broadly than the narrowest defensible set is exactly what
# PR10 must be free to tighten without first auditing scattered endpoint
# literals).
#
# Single source of truth: when Roadmap PR10 lands the 3-role model, replace
# this tuple's contents (and only this tuple) -- no other file should ever
# gate ward correction by an inline role list. See docs/DECISION_LOG.md
# ("Roadmap PR9A").
WARD_CORRECTION_ROLES = (ROLE_ADMIN, ROLE_WARD_NURSE, ROLE_TRANSPORT_STAFF)


class PaginationParams:
    def __init__(self, limit: int = 25, cursor: str | None = None):
        self.limit = max(1, min(limit, 200))
        self.cursor = cursor
