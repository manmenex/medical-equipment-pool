import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidInputError
from app.core.security import hash_password
from app.models.user import Role, User

# Roadmap PR14A (Backend Audit 4.1): `data` only ever contains keys the
# client explicitly supplied (see UserUpdate/update_user's
# exclude_unset=True) -- a key mapped to None here means the client asked
# to clear that field. Both are `nullable=False` in the database
# (app.models.user.User) and must never be nulled by a PATCH. This only
# rejects an explicit null; blank/whitespace-only string validation for
# full_name is a separate concern left to a future focused PR.
REQUIRED_NON_NULL_FIELDS = frozenset({"full_name", "is_active"})


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    result = await db.execute(
        select(User).where((User.employee_code == identifier) | (User.email == identifier))
    )
    return result.scalar_one_or_none()


async def get_role_by_name(db: AsyncSession, name: str) -> Role | None:
    result = await db.execute(select(Role).where(Role.name == name))
    return result.scalar_one_or_none()


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.full_name))
    return list(result.scalars().all())


async def create(db: AsyncSession, *, data: dict, role_id: uuid.UUID) -> User:
    user = User(
        employee_code=data["employee_code"],
        full_name=data["full_name"],
        email=data["email"],
        phone=data.get("phone"),
        password_hash=hash_password(data["password"]),
        role_id=role_id,
    )
    db.add(user)
    await db.flush()
    return user


async def update(db: AsyncSession, user: User, *, data: dict, role_id: uuid.UUID | None = None) -> User:
    # Pass 1: validate every incoming field before any mutation occurs.
    for key in REQUIRED_NON_NULL_FIELDS:
        if key in data and data[key] is None:
            raise InvalidInputError(f"'{key}' is required and cannot be cleared.")

    # Pass 2: mutate. `phone` is nullable, so an explicit None here is a
    # legitimate clear request, not a bug -- unlike full_name/is_active
    # above, which pass 1 already guarantees are never None at this point.
    if "full_name" in data:
        user.full_name = data["full_name"]
    if "phone" in data:
        user.phone = data["phone"]
    if "is_active" in data:
        user.is_active = data["is_active"]
    if data.get("password"):
        user.password_hash = hash_password(data["password"])
    if role_id is not None:
        user.role_id = role_id
    await db.flush()
    return user
