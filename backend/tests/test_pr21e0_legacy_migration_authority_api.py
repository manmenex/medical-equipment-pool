"""Roadmap PR21E0 -- Legacy Import Operator API Surface, gap A.

Tests `POST/GET /api/v1/legacy-migration-authorities`
(`app.api.v1.legacy_migration_authorities`) and
`app.crud.legacy_migration_authority.create_or_get_approval`'s own
race-safe idempotency contract.

The genuine two-connection concurrent-approval race (§10 of the task) is
proved against real PostgreSQL in
`test_postgres_integration.py::test_pr21e0_concurrent_authority_approval_exactly_one_winner`
instead of here: this file's `db_engine` fixture is a single shared
in-memory SQLite connection (`StaticPool`), which does not support two
independently-committing transactions overlapping in time the way a real
race requires -- mirroring this codebase's own established convention
that every other genuine concurrency proof
(`test_pr20e_create_identity_race_exactly_one_winner`,
`test_pr94_concurrent_confirm_confirm_exactly_one_first_confirmer`, ...)
already lives in that PostgreSQL-only file, never in the SQLite suite."""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.crud import legacy_migration_authority as legacy_migration_authority_crud
from app.models.audit import AuditLog
from app.models.master_data import Ward
from app.models.user import ROLE_READ_ONLY, User
from tests.conftest import auth_headers

_SCOPE = "pr21_legacy_transaction_history_v1"
_CHECKSUM = "a" * 64


async def _actor_id(db_session: AsyncSession) -> uuid.UUID:
    return (await db_session.execute(select(User.id).limit(1))).scalar_one()


# ---------------------------------------------------------------------------
# Authorization.
# ---------------------------------------------------------------------------


async def test_admin_can_approve(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    r = await client.post(
        "/api/v1/legacy-migration-authorities",
        headers=headers,
        json={"scope": _SCOPE, "approved_workbook_sha256": _CHECKSUM},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["scope"] == _SCOPE
    assert body["approved_workbook_sha256"] == _CHECKSUM
    assert body["approved_by_user_id"]
    assert body["approved_at"]


async def test_non_admin_rejected(client: AsyncClient, seeded_users):
    headers = await auth_headers(client, role=ROLE_READ_ONLY)
    r = await client.post(
        "/api/v1/legacy-migration-authorities",
        headers=headers,
        json={"scope": _SCOPE, "approved_workbook_sha256": _CHECKSUM},
    )
    assert r.status_code == 403, r.text


async def test_anonymous_rejected(client: AsyncClient, seeded_users):
    r = await client.post(
        "/api/v1/legacy-migration-authorities",
        json={"scope": _SCOPE, "approved_workbook_sha256": _CHECKSUM},
    )
    assert r.status_code == 401, r.text


async def test_non_admin_rejected_on_get_routes(client: AsyncClient, seeded_users):
    headers = await auth_headers(client, role=ROLE_READ_ONLY)
    r = await client.get(f"/api/v1/legacy-migration-authorities/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 403, r.text
    r = await client.get("/api/v1/legacy-migration-authorities", headers=headers, params={"checksum": _CHECKSUM})
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Checksum validation/normalization.
# ---------------------------------------------------------------------------


async def test_invalid_length_checksum_rejected(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post(
        "/api/v1/legacy-migration-authorities",
        headers=headers,
        json={"scope": _SCOPE, "approved_workbook_sha256": "abc123"},
    )
    assert r.status_code == 422, r.text


async def test_non_hex_checksum_rejected(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post(
        "/api/v1/legacy-migration-authorities",
        headers=headers,
        json={"scope": _SCOPE, "approved_workbook_sha256": "z" * 64},
    )
    assert r.status_code == 422, r.text


async def test_checksum_normalized_to_canonical_lowercase(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    raw = ("  " + ("A" * 64) + "  ")
    r = await client.post(
        "/api/v1/legacy-migration-authorities",
        headers=headers,
        json={"scope": _SCOPE, "approved_workbook_sha256": raw},
    )
    assert r.status_code == 201, r.text
    assert r.json()["approved_workbook_sha256"] == "a" * 64


async def test_unsupported_scope_rejected(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post(
        "/api/v1/legacy-migration-authorities",
        headers=headers,
        json={"scope": "not-a-real-scope", "approved_workbook_sha256": _CHECKSUM},
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# Idempotency / audit.
# ---------------------------------------------------------------------------


async def test_first_approval_stores_actor_and_writes_one_audit_event(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    r = await client.post(
        "/api/v1/legacy-migration-authorities",
        headers=headers,
        json={"scope": _SCOPE, "approved_workbook_sha256": _CHECKSUM},
    )
    assert r.status_code == 201, r.text
    authority_id = uuid.UUID(r.json()["id"])

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "legacy_migration_authority_approved",
                AuditLog.entity_type == "legacy_migration_authority",
                AuditLog.entity_id == authority_id,
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 1


async def test_retry_returns_existing_row_and_writes_no_duplicate_audit(
    client: AsyncClient, seeded_users, db_session
):
    admin_headers = await auth_headers(client)
    r1 = await client.post(
        "/api/v1/legacy-migration-authorities",
        headers=admin_headers,
        json={"scope": _SCOPE, "approved_workbook_sha256": _CHECKSUM},
    )
    assert r1.status_code == 201, r1.text
    first = r1.json()

    r2 = await client.post(
        "/api/v1/legacy-migration-authorities",
        headers=admin_headers,
        json={"scope": _SCOPE, "approved_workbook_sha256": _CHECKSUM},
    )
    assert r2.status_code == 200, r2.text
    second = r2.json()

    assert second["id"] == first["id"]
    assert second["approved_by_user_id"] == first["approved_by_user_id"]
    assert second["approved_at"] == first["approved_at"]

    authority_id = uuid.UUID(first["id"])
    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "legacy_migration_authority_approved",
                AuditLog.entity_id == authority_id,
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 1


async def test_conflicting_scope_conflict_at_crud_layer(db_session: AsyncSession, seeded_users):
    """`LegacyMigrationAuthorityCreate.scope` only accepts the closed V1
    allowlist over HTTP (§6), so a genuine scope conflict cannot currently
    be produced through the HTTP route with only one allowlisted value --
    exercised directly against the CRUD layer instead, which is
    scope-agnostic (the DB column itself is free-text; see that module's
    own docstring), proving the 409 contract independently of how many
    scopes the API layer currently allows."""
    actor_id = await _actor_id(db_session)
    await legacy_migration_authority_crud.create_or_get_approval(
        db_session, scope="scope-one", approved_workbook_sha256=_CHECKSUM, actor_id=actor_id
    )
    await db_session.commit()

    from app.core.exceptions import LegacyMigrationAuthorityScopeConflictError

    with pytest.raises(LegacyMigrationAuthorityScopeConflictError):
        await legacy_migration_authority_crud.create_or_get_approval(
            db_session, scope="scope-two", approved_workbook_sha256=_CHECKSUM, actor_id=actor_id
        )


# ---------------------------------------------------------------------------
# Read routes.
# ---------------------------------------------------------------------------


async def test_get_by_id_and_by_checksum(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    created = (
        await client.post(
            "/api/v1/legacy-migration-authorities",
            headers=headers,
            json={"scope": _SCOPE, "approved_workbook_sha256": _CHECKSUM},
        )
    ).json()

    by_id = await client.get(f"/api/v1/legacy-migration-authorities/{created['id']}", headers=headers)
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["id"] == created["id"]

    by_checksum = await client.get(
        "/api/v1/legacy-migration-authorities", headers=headers, params={"checksum": _CHECKSUM.upper()}
    )
    assert by_checksum.status_code == 200, by_checksum.text
    assert by_checksum.json()["id"] == created["id"]


async def test_get_by_id_unknown_returns_404(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/legacy-migration-authorities/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404, r.text


async def test_get_by_checksum_unknown_returns_404(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.get(
        "/api/v1/legacy-migration-authorities", headers=headers, params={"checksum": "b" * 64}
    )
    assert r.status_code == 404, r.text


async def test_get_by_checksum_invalid_returns_400(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.get(
        "/api/v1/legacy-migration-authorities", headers=headers, params={"checksum": "not-hex"}
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# No delete/update endpoint (§8 of the task).
# ---------------------------------------------------------------------------


async def test_no_delete_or_update_endpoint_exists(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    created = (
        await client.post(
            "/api/v1/legacy-migration-authorities",
            headers=headers,
            json={"scope": _SCOPE, "approved_workbook_sha256": _CHECKSUM},
        )
    ).json()

    delete_resp = await client.delete(f"/api/v1/legacy-migration-authorities/{created['id']}", headers=headers)
    assert delete_resp.status_code == 405, delete_resp.text

    patch_resp = await client.patch(
        f"/api/v1/legacy-migration-authorities/{created['id']}",
        headers=headers,
        json={"approved_workbook_sha256": "b" * 64},
    )
    assert patch_resp.status_code == 405, patch_resp.text

    put_resp = await client.put(
        f"/api/v1/legacy-migration-authorities/{created['id']}",
        headers=headers,
        json={"approved_workbook_sha256": "b" * 64},
    )
    assert put_resp.status_code == 405, put_resp.text


# ---------------------------------------------------------------------------
# PR #109 P1 fix round -- `create_or_get_approval` must never decide the
# fate of the caller's outer transaction. The conflict-prone INSERT is now
# isolated in its own `db.begin_nested()` SAVEPOINT (mirrors
# `app.crud.import_session.register_or_correct_source_pending`'s own
# PR90-H1 fix and `app.core.audit.record_best_effort_audit_event`'s
# identical pattern) rather than calling a bare `await db.rollback()` on
# `IntegrityError`, which would have discarded the caller's *entire*
# transaction, including any unrelated work staged before this helper was
# ever called.
#
# These regressions need a real transaction boundary where a SAVEPOINT is
# opened/rolled-back-to and the *outer* transaction is later committed or
# inspected -- pysqlite's default legacy transaction handling does not
# reliably support that combination (the same documented caveat
# `test_audit.py`'s own `sp_engine` fixture and
# `test_pr20a_source_artifact_infrastructure.py`'s identical fixture both
# work around, see either docstring for the full SQLAlchemy-recipe
# rationale). Rather than apply that recipe to the shared `db_engine`
# fixture used by every other test in this file, it is scoped to a
# dedicated engine/session used only by this section -- exactly the same
# choice those two prior modules already made for this identical class of
# problem. Real PostgreSQL has no such caveat; the genuine two-connection
# concurrency proof already lives in `test_postgres_integration.py`.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sp_engine():
    from sqlalchemy import event

    from app.db.base import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    # See https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
    @event.listens_for(engine.sync_engine, "connect")
    def _do_connect(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _do_begin(conn):
        conn.exec_driver_sql("BEGIN")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def sp_seeded_users(sp_engine):
    from app.core.security import hash_password
    from app.models.user import ALL_ROLES, Role

    session_maker = async_sessionmaker(sp_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        roles = {}
        for name in ALL_ROLES:
            role = Role(name=name, permissions={})
            session.add(role)
            roles[name] = role
        await session.flush()

        users = {}
        for role_name in ALL_ROLES:
            user = User(
                employee_code=f"{role_name.upper()}001",
                full_name=f"Test {role_name}",
                email=f"{role_name}@mep-hospital-test.dev",
                password_hash=hash_password("Password@123"),
                role_id=roles[role_name].id,
            )
            session.add(user)
            users[role_name] = user
        await session.commit()
        return users


async def test_outer_transaction_preserved_on_idempotent_duplicate_approval(sp_engine, sp_seeded_users):
    """§5 of the fix task. Stages an unrelated write BEFORE the duplicate
    approval attempt, forces the real `IntegrityError`/SAVEPOINT-conflict
    path (not a pre-check short-circuit -- the existing row is committed
    on a separate connection first, exactly like production), then proves
    the unrelated write is still present in the same transaction
    afterward. This regression fails under the previous `await
    db.rollback()` implementation, which discarded it."""
    session_maker = async_sessionmaker(sp_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as setup_db:
        actor_id = (await setup_db.execute(select(User.id).limit(1))).scalar_one()
        first, created = await legacy_migration_authority_crud.create_or_get_approval(
            setup_db, scope=_SCOPE, approved_workbook_sha256=_CHECKSUM, actor_id=actor_id
        )
        assert created is True
        await setup_db.commit()
        first_id, first_approved_at, first_approved_by = first.id, first.approved_at, first.approved_by_user_id

    async with session_maker() as db:
        actor_id = (await db.execute(select(User.id).limit(1))).scalar_one()

        # Stage unrelated work BEFORE the duplicate-approval call, and do
        # not commit it yet -- this is what the previous implementation's
        # `await db.rollback()` would have destroyed.
        unrelated = Ward(code="PR109-P1-WARD", name="PR109 P1 Regression Ward")
        db.add(unrelated)
        await db.flush()

        result, created2 = await legacy_migration_authority_crud.create_or_get_approval(
            db, scope=_SCOPE, approved_workbook_sha256=_CHECKSUM, actor_id=actor_id
        )
        assert created2 is False
        assert result.id == first_id
        assert result.approved_by_user_id == first_approved_by
        assert result.approved_at == first_approved_at

        # The unrelated staged write must still be visible in this same
        # session/transaction -- the outer transaction was never rolled
        # back by the helper's own IntegrityError handling.
        still_staged = (await db.execute(select(Ward).where(Ward.code == "PR109-P1-WARD"))).scalar_one_or_none()
        assert still_staged is not None, "unrelated staged write was discarded by the approval helper"

        await db.commit()

    # Durability proof in a completely fresh session/connection.
    async with session_maker() as verify_db:
        ward_row = (await verify_db.execute(select(Ward).where(Ward.code == "PR109-P1-WARD"))).scalar_one_or_none()
        assert ward_row is not None, "the unrelated write did not survive the commit"

        from app.models.legacy_history import LegacyMigrationAuthority

        authorities = (
            await verify_db.execute(
                select(LegacyMigrationAuthority).where(
                    LegacyMigrationAuthority.approved_workbook_sha256 == _CHECKSUM
                )
            )
        ).scalars().all()
        assert len(authorities) == 1
        assert authorities[0].approved_by_user_id == first_approved_by
        assert authorities[0].approved_at == first_approved_at


async def test_outer_transaction_preserved_on_scope_conflict(sp_engine, sp_seeded_users):
    """§6 of the fix task. Same shape as the idempotent-duplicate
    regression above, but for the scope-conflict path: the helper's
    `LegacyMigrationAuthorityScopeConflictError` must not poison the
    caller's outer transaction either -- the caller can still choose to
    commit whatever else it staged."""
    from app.core.exceptions import LegacyMigrationAuthorityScopeConflictError

    session_maker = async_sessionmaker(sp_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as setup_db:
        actor_id = (await setup_db.execute(select(User.id).limit(1))).scalar_one()
        await legacy_migration_authority_crud.create_or_get_approval(
            setup_db, scope="scope-one", approved_workbook_sha256=_CHECKSUM, actor_id=actor_id
        )
        await setup_db.commit()

    async with session_maker() as db:
        actor_id = (await db.execute(select(User.id).limit(1))).scalar_one()

        unrelated = Ward(code="PR109-P1-CONFLW", name="PR109 P1 Conflict Ward")
        db.add(unrelated)
        await db.flush()

        with pytest.raises(LegacyMigrationAuthorityScopeConflictError):
            await legacy_migration_authority_crud.create_or_get_approval(
                db, scope="scope-two", approved_workbook_sha256=_CHECKSUM, actor_id=actor_id
            )

        # The caller's session must remain usable -- neither in a failed-
        # transaction state, nor missing the unrelated staged write.
        still_staged = (
            await db.execute(select(Ward).where(Ward.code == "PR109-P1-CONFLW"))
        ).scalar_one_or_none()
        assert still_staged is not None, "unrelated staged write was discarded by the scope-conflict path"

        await db.commit()

    async with session_maker() as verify_db:
        ward_row = (
            await verify_db.execute(select(Ward).where(Ward.code == "PR109-P1-CONFLW"))
        ).scalar_one_or_none()
        assert ward_row is not None, "the unrelated write did not survive the caller's commit"


def test_create_or_get_approval_never_calls_outer_rollback_or_commit():
    """AST-based static-inspection guard (not substring matching -- the
    function's own docstring legitimately mentions `db.rollback()`/
    `db.commit()` in prose, which a substring check would false-positive
    on), mirroring
    `test_register_or_correct_source_pending_helper_never_calls_outer_rollback_or_commit`
    in `test_pr20a_source_artifact_infrastructure.py` exactly: the helper
    must never contain an actual `db.rollback()`/`db.commit()` *call
    expression* -- only `db.begin_nested()`'s own SAVEPOINT-scoped `async
    with` block may issue transaction control."""
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(legacy_migration_authority_crud.create_or_get_approval))
    tree = ast.parse(source)

    forbidden_calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("rollback", "commit")
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "db"
    ]
    assert forbidden_calls == [], (
        f"create_or_get_approval must never call db.rollback()/db.commit() directly against the caller's "
        f"outer session, found call(s): {forbidden_calls}"
    )
