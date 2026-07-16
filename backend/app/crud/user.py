import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import Role, User


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
    if data.get("full_name") is not None:
        user.full_name = data["full_name"]
    if data.get("phone") is not None:
        user.phone = data["phone"]
    if data.get("is_active") is not None:
        user.is_active = data["is_active"]
    if data.get("password"):
        user.password_hash = hash_password(data["password"])
    if role_id is not None:
        user.role_id = role_id
    await db.flush()
    return user
