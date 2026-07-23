from collections.abc import Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import ROLE_ADMIN, Role, User

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
# The current 5-role model (admin/biomedical_engineer/ward_nurse/
# transport_staff/viewer) has no confirmed, evidence-backed equivalent of
# "Equipment Pool Staff" -- the workflow audit's §10 note explicitly says
# biomedical_engineer/ward_nurse/transport_staff "have no clear place in
# this workflow as described" and recommends treating them as out of scope
# for this MVP's role model, not that any one of them stands in for
# Equipment Pool Staff. Which roles other endpoints (dispatch, receipt)
# happen to trust is a different, unrelated authorization decision for
# those endpoints -- ward correction does not inherit permissions from
# dispatch or receipt, and must not infer an equivalence the workflow audit
# never confirmed. Because this action modifies historical operational
# data, an inferred/guessed mapping is not acceptable here.
#
# Until PR10 lands the confirmed 3-role model, this is therefore
# intentionally conservative and restricted to the one role this
# repository's governance already confirms maps to Administrator:
# ROLE_ADMIN. Every other current role (biomedical_engineer, ward_nurse,
# transport_staff, viewer) is denied -- not because any of them is
# confirmed equivalent to Read-Only/Supervisor, but because none of them is
# confirmed equivalent to Equipment Pool Staff either, and a data-correction
# action must fail closed on an unconfirmed mapping rather than guess.
#
# Single source of truth: when Roadmap PR10 lands the 3-role model, replace
# this tuple's contents (and only this tuple) with the confirmed
# Administrator + Equipment Pool Staff roles -- no other file should ever
# gate ward correction by an inline role list. See docs/DECISION_LOG.md
# ("Roadmap PR9A").
WARD_CORRECTION_ROLES = (ROLE_ADMIN,)


class PaginationParams:
    def __init__(self, limit: int = 25, cursor: str | None = None):
        self.limit = max(1, min(limit, 200))
        self.cursor = cursor
