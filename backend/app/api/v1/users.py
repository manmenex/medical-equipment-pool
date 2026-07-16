import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_roles
from app.core.audit import AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_USER, record_audit_event
from app.core.db_errors import translate_integrity_error
from app.core.exceptions import InvalidInputError, ResourceNotFoundError
from app.crud import user as user_crud
from app.db.session import get_db
from app.models.user import ROLE_ADMIN, Role
from app.schemas.master_data import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


async def _serialize(db: AsyncSession, user) -> UserOut:
    role = await db.get(Role, user.role_id)
    return UserOut(
        id=str(user.id),
        employee_code=user.employee_code,
        full_name=user.full_name,
        email=user.email,
        role=role.name if role else "",
        is_active=user.is_active,
    )


@router.get("", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))):
    users = await user_crud.list_users(db)
    return [await _serialize(db, u) for u in users]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(ROLE_ADMIN)),
):
    role = await user_crud.get_role_by_name(db, payload.role_name)
    if role is None:
        raise InvalidInputError(f"Unknown role '{payload.role_name}'")
    async with translate_integrity_error(db, resource="user"):
        user = await user_crud.create(db, data=payload.model_dump(), role_id=role.id)
    await record_audit_event(
        db,
        actor_user_id=actor.id,
        action=AUDIT_ACTION_CREATE,
        entity_type=AUDIT_ENTITY_USER,
        entity_id=user.id,
        after=payload.model_dump(),
        request=request,
    )
    await db.commit()
    return await _serialize(db, user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(ROLE_ADMIN)),
):
    user = await user_crud.get_by_id(db, user_id)
    if user is None:
        raise ResourceNotFoundError("User not found")
    before_role = await db.get(Role, user.role_id)
    before = {
        "full_name": user.full_name,
        "phone": user.phone,
        "is_active": user.is_active,
        "role_name": before_role.name if before_role else None,
        "password_hash": user.password_hash,
    }
    role_id = None
    if payload.role_name:
        role = await user_crud.get_role_by_name(db, payload.role_name)
        if role is None:
            raise InvalidInputError(f"Unknown role '{payload.role_name}'")
        role_id = role.id
    async with translate_integrity_error(db, resource="user"):
        user = await user_crud.update(db, user, data=payload.model_dump(exclude_unset=True), role_id=role_id)
    await record_audit_event(
        db,
        actor_user_id=actor.id,
        action=AUDIT_ACTION_UPDATE,
        entity_type=AUDIT_ENTITY_USER,
        entity_id=user.id,
        before=before,
        after=payload.model_dump(exclude_unset=True),
        request=request,
    )
    await db.commit()
    return await _serialize(db, user)
