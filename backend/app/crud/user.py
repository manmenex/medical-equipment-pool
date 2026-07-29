import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidInputError
from app.core.security import hash_password
from app.models.transaction import BorrowTransaction
from app.models.user import Role, User
from app.utils.pagination import decode_alpha_cursor, encode_alpha_cursor

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


async def list_operators(
    db: AsyncSession,
    *,
    q: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[User], str | None, int]:
    """Roadmap PR17 Slice 2 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
    §10.4/§11): the bounded, report-scoped operator lookup behind
    `GET /report-options/operators`.

    Source / population rule: exactly the distinct `User` rows referenced
    by `BorrowTransaction.borrower_user_id` or `.received_by_user_id`, at
    least once, across all transactions -- a `SELECT DISTINCT` union of
    both FK columns, filtered as an `IN` subquery against `User`. This is
    never every `User` row (that remains `list_users` above, reachable
    only via the Administrator-only `GET /users`) -- a Read Only account,
    or an Administrator who has never dispatched/received anything, is
    never returned here, regardless of role. `NULL` FK values contribute
    nothing to the set.

    Both active and inactive operators are returned (§10.4 "Active/inactive
    behavior") -- `is_active` is left for the caller/schema to surface, not
    filtered out here; `User` rows are never deleted, only deactivated.

    Ordered `full_name ASC, id ASC` (a stable alphabetical order for a
    name-driven `<select>`), not `created_at` -- a distinct cursor basis
    from the reports' own chronological ordering (§10.1/§10.2).
    """
    operator_ids = (
        select(BorrowTransaction.borrower_user_id)
        .where(BorrowTransaction.borrower_user_id.is_not(None))
        .union(
            select(BorrowTransaction.received_by_user_id).where(
                BorrowTransaction.received_by_user_id.is_not(None)
            )
        )
    )

    filters = [User.id.in_(operator_ids)]
    if q:
        # Same LIKE-wildcard-escaping technique as
        # app.crud.equipment.search_bcm -- a literal "%"/"_" in the typed
        # query must not act as a wildcard.
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(User.full_name.ilike(f"%{escaped}%", escape="\\"))

    count_stmt = select(func.count()).select_from(User).where(and_(*filters))
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(User).where(and_(*filters))
    if cursor:
        cursor_name, cursor_id = decode_alpha_cursor(cursor)
        # Compares the native `Uuid`-typed column directly against a
        # parsed `uuid.UUID` value, not a `cast(..., String)` comparison
        # against `str(user.id)` -- the latter breaks on SQLite, whose
        # `Uuid` type stores/CASTs without dashes while `str(uuid.UUID(...))`
        # always includes them, so the two representations never compare
        # equal and the cursor can never advance past a tie (discovered
        # while testing this exact function; see PR17 Slice 1's PR
        # description for the same defect in the pre-existing
        # `transaction_crud.search()`/`equipment_crud.search()` cursor,
        # left unfixed there as pre-existing shared infrastructure outside
        # that slice's scope -- fixed directly here since this query is
        # new code introduced by this slice).
        stmt = stmt.where(
            or_(
                User.full_name > cursor_name,
                and_(User.full_name == cursor_name, User.id > uuid.UUID(cursor_id)),
            )
        )
    stmt = stmt.order_by(User.full_name.asc(), User.id.asc()).limit(limit + 1)

    rows = list((await db.execute(stmt)).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_alpha_cursor(last.full_name, str(last.id))
        rows = rows[:limit]
    return rows, next_cursor, total
