from sqlalchemy import func, select

from app.models.user import ALL_ROLES, ROLE_ADMINISTRATOR, Role, User
from app.scripts.seed import seed_reference_data

# ---------------------------------------------------------------------------
# Roadmap PR18D review round 3 (H2): `docs/06-deployment-guide.md` documents
# `alembic upgrade head` followed by `python -m app.scripts.seed` as the
# deployment sequence. Migration 0009 (role_consolidation) already creates
# the confirmed roles (`administrator`, `equipment_pool_staff`, `read_only`)
# as part of a plain `alembic upgrade head` on a fresh database -- so
# `seed_reference_data` blindly inserting the same role names again always
# violated `roles.name`'s uniqueness on that exact, documented, first-
# deployment sequence, surfaced by the Docker production smoke test's real
# migrate-then-seed run. This test proves the fix without needing a real
# Postgres instance: the SQLite `db_session` fixture is enough to exercise
# `seed_reference_data`'s own get-or-create logic for roles and the
# administrator account (the two rows a migration can pre-create; the other
# reference tables below -- departments, categories, locations -- are never
# touched by any migration, so they are intentionally not made idempotent
# here, matching the review's "do not change production seed semantics
# merely to satisfy the smoke test").
# ---------------------------------------------------------------------------


async def test_seed_reference_data_reuses_roles_and_admin_pre_created_by_a_migration(db_session):
    """Direct regression test for the root cause: simulates migration
    0009's own get-or-create role bootstrap running first (as it does on
    a real `alembic upgrade head`), then proves `seed_reference_data`
    reuses those exact rows -- by id -- instead of attempting to insert
    duplicates and failing on `roles.name`'s uniqueness."""
    for role_name in ALL_ROLES:
        db_session.add(Role(name=role_name, permissions={}))
    await db_session.flush()

    pre_existing_role_ids = {
        role.name: role.id for role in (await db_session.execute(select(Role))).scalars().all()
    }
    await db_session.commit()

    await seed_reference_data(db_session)
    await db_session.commit()

    role_count = (await db_session.execute(select(func.count()).select_from(Role))).scalar_one()
    assert role_count == len(ALL_ROLES), "seeding after a migration-created role set must not add duplicates"

    admin = (await db_session.execute(select(User).where(User.employee_code == "ADMIN001"))).scalar_one()
    assert admin.role_id == pre_existing_role_ids[ROLE_ADMINISTRATOR], (
        "the seeded admin account must reference the pre-existing 'administrator' role row, "
        "not a newly (and invalidly) duplicated one"
    )


async def test_seed_reference_data_reuses_a_pre_existing_admin_account(db_session):
    """A second, independent guard: even if the administrator account
    itself (not just its role) already exists -- e.g. an operator created
    it by hand before running this script -- seeding again must not try
    to insert a second `ADMIN001` and fail on `users.employee_code`'s
    uniqueness."""
    for role_name in ALL_ROLES:
        db_session.add(Role(name=role_name, permissions={}))
    await db_session.flush()
    roles = {role.name: role for role in (await db_session.execute(select(Role))).scalars().all()}

    from app.core.security import hash_password

    db_session.add(
        User(
            employee_code="ADMIN001",
            full_name="Pre-existing Admin",
            email="preexisting-admin@hospital.local",
            password_hash=hash_password("Different@123"),
            role_id=roles[ROLE_ADMINISTRATOR].id,
        )
    )
    await db_session.commit()

    await seed_reference_data(db_session)
    await db_session.commit()

    admin_count = (
        await db_session.execute(select(func.count()).select_from(User).where(User.employee_code == "ADMIN001"))
    ).scalar_one()
    assert admin_count == 1

    admin = (await db_session.execute(select(User).where(User.employee_code == "ADMIN001"))).scalar_one()
    assert admin.full_name == "Pre-existing Admin", "an already-existing admin account must not be overwritten"
