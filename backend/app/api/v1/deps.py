from collections.abc import Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY, Role, User

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


# Roadmap PR10 (Role Model Consolidation, docs/audits/03-hospital-equipment
# -pool-workflow-audit.md §10 "Role and Permission Review"): centralized,
# named capability groups mirroring the confirmed 3-role permission matrix.
# Every endpoint's role gate references one of these groups -- never an
# inline ad hoc role tuple -- so the whole application's authorization
# matrix has exactly one reviewable source of truth. See
# docs/BUSINESS_RULES.md and docs/DECISION_LOG.md ("Roadmap PR10") for the
# full capability-by-capability rationale.

# Equipment Pool day-to-day operations: view/search (see get_current_user,
# used directly for those), dispatch, receipt, ward correction, and marking
# equipment defective. Both Administrator and Equipment Pool Staff perform
# these; Read Only never does (view-only).
EQUIPMENT_POOL_OPERATION_ROLES = (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF)

# Administrator-only actions: reactivating defective equipment,
# decommissioning, equipment master-data create/update, ward/department/
# location/category master-data management, user and role management, and
# audit-log reads. Equipment Pool Staff is explicitly denied every one of
# these -- confirmed by docs/audits/03-hospital-equipment-pool-workflow-audit.md
# §10's matrix (reactivation "recommend Admin-only gate for MVP"; master
# data "lean toward Admin-only for MVP"; user management "Administrator
# only").
ADMINISTRATOR_ONLY_ROLES = (ROLE_ADMINISTRATOR,)

# Read/reporting surfaces already available to every one of the pre-PR10
# roles that had any access at all (admin, biomedical_engineer, viewer) --
# PR10 preserves that existing breadth rather than narrowing it, per "do not
# add export capability unless it already exists" and "do not add new
# endpoints." All three new roles may view/export.
VIEW_AND_REPORT_ROLES = (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY)

# Ward correction (Roadmap PR9A's endpoint): Administrator and Equipment
# Pool Staff, per the confirmed matrix's "Correct a destination ward" row
# ("✅ (with mandatory audit note)" for Equipment Pool Staff). Read Only is
# denied. This replaces PR9's temporary Administrator-only restriction now
# that the confirmed 3-role model exists -- no other change to the
# ward-correction contract, concurrency guard, audit behavior, or OPEN/
# CLOSED support.
WARD_CORRECTION_ROLES = EQUIPMENT_POOL_OPERATION_ROLES


class PaginationParams:
    def __init__(self, limit: int = 25, cursor: str | None = None):
        self.limit = max(1, min(limit, 200))
        self.cursor = cursor
