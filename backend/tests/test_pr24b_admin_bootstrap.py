"""PR24B (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §17): the
production-safe first-administrator bootstrap script
(app.scripts.bootstrap_admin), replacing backend/app/scripts/seed.py's
hardcoded ADMIN001/Admin@12345 for production use.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.audit import AuditLog
from app.models.user import ALL_ROLES, ROLE_ADMINISTRATOR, Role, User
from app.scripts import bootstrap_admin


@pytest.fixture
def session_maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(autouse=True)
def patched_session_local(monkeypatch, session_maker):
    # Same pattern test_import_lease.py uses for code that reads the
    # module's own imported `AsyncSessionLocal` name directly, rather than
    # receiving a session via FastAPI's Depends(get_db) -- this script is
    # a CLI, not an HTTP endpoint, so there is no request-scoped session to
    # inject.
    monkeypatch.setattr(bootstrap_admin, "AsyncSessionLocal", session_maker)


@pytest.fixture
async def roles_only(db_session):
    """Seeds the three confirmed roles (matching migration
    0009_role_consolidation's own effect on a fresh deployment) without
    creating any user -- the "fresh deployment, no administrator yet"
    starting state this script exists for."""
    roles = {}
    for name in ALL_ROLES:
        role = Role(name=name, permissions={})
        db_session.add(role)
        roles[name] = role
    await db_session.commit()
    return roles


async def test_bootstrap_creates_exactly_one_administrator(roles_only, session_maker):
    user, temp_password = await bootstrap_admin.bootstrap_admin(
        employee_code="ADMIN001", email="admin@hospital.local", full_name="System Administrator"
    )
    assert user.employee_code == "ADMIN001"
    assert user.email == "admin@hospital.local"
    assert temp_password  # non-empty
    assert temp_password != "Admin@12345"  # never the seed.py demo password

    async with session_maker() as verify_db:
        result = await verify_db.execute(select(User).where(User.role_id == roles_only[ROLE_ADMINISTRATOR].id))
        admins = result.scalars().all()
        assert len(admins) == 1
        assert admins[0].employee_code == "ADMIN001"


async def test_bootstrap_creates_no_demo_or_sample_data(roles_only, session_maker):
    await bootstrap_admin.bootstrap_admin(
        employee_code="ADMIN001", email="admin@hospital.local", full_name="System Administrator"
    )
    async with session_maker() as verify_db:
        # Only the one administrator this call created -- no seed.py-style
        # sample departments/wards/categories/equipment/transactions exist
        # in this schema fixture at all, so the only thing to assert is
        # that exactly one user total exists.
        result = await verify_db.execute(select(User))
        assert len(result.scalars().all()) == 1


async def test_bootstrap_password_is_never_persisted_in_plaintext(roles_only, session_maker):
    user, temp_password = await bootstrap_admin.bootstrap_admin(
        employee_code="ADMIN001", email="admin@hospital.local", full_name="System Administrator"
    )
    async with session_maker() as verify_db:
        result = await verify_db.execute(select(User).where(User.id == user.id))
        stored = result.scalar_one()
        assert stored.password_hash != temp_password
        assert temp_password not in stored.password_hash


async def test_bootstrap_records_audit_entry_with_no_actor_and_no_secret(roles_only, session_maker):
    user, temp_password = await bootstrap_admin.bootstrap_admin(
        employee_code="ADMIN001", email="admin@hospital.local", full_name="System Administrator"
    )
    async with session_maker() as verify_db:
        result = await verify_db.execute(select(AuditLog).where(AuditLog.entity_id == user.id))
        entry = result.scalar_one()
        assert entry.action == "ADMIN_BOOTSTRAP"
        assert entry.entity_type == "user"
        # user_id=None is deliberate -- no authenticated actor exists yet
        # at bootstrap time; never a fabricated actor.
        assert entry.user_id is None
        after = entry.after_data or {}
        assert "password" not in str(after).lower()
        assert temp_password not in str(after)


async def test_bootstrap_refuses_when_administrator_already_exists(roles_only, session_maker):
    await bootstrap_admin.bootstrap_admin(
        employee_code="ADMIN001", email="admin@hospital.local", full_name="System Administrator"
    )
    with pytest.raises(bootstrap_admin.BootstrapRefused):
        await bootstrap_admin.bootstrap_admin(
            employee_code="ADMIN002", email="second-admin@hospital.local", full_name="Second Admin"
        )
    async with session_maker() as verify_db:
        result = await verify_db.execute(select(User))
        # Still exactly one -- the refused second call made no changes.
        assert len(result.scalars().all()) == 1


async def test_bootstrap_transaction_rolls_back_on_identifier_collision(roles_only, session_maker):
    # Pre-existing non-administrator user occupying the employee_code the
    # bootstrap call will try to use -- exercises the IntegrityError path
    # (app.scripts.bootstrap_admin.bootstrap_admin's own try/except around
    # db.flush()), distinct from the "administrator already exists" refusal
    # path above.
    from app.core.security import hash_password

    async with session_maker() as seed_db:
        other_role = (
            await seed_db.execute(select(Role).where(Role.name == "read_only"))
        ).scalar_one()
        seed_db.add(
            User(
                employee_code="ADMIN001",
                full_name="Unrelated Existing User",
                email="unrelated@hospital.local",
                password_hash=hash_password("Password@123"),
                role_id=other_role.id,
            )
        )
        await seed_db.commit()

    with pytest.raises(bootstrap_admin.BootstrapRefused):
        await bootstrap_admin.bootstrap_admin(
            employee_code="ADMIN001", email="admin@hospital.local", full_name="System Administrator"
        )

    async with session_maker() as verify_db:
        result = await verify_db.execute(select(User))
        users = result.scalars().all()
        # Still exactly the one pre-existing unrelated user -- no partial
        # administrator row survives the rolled-back transaction.
        assert len(users) == 1
        assert users[0].email == "unrelated@hospital.local"
