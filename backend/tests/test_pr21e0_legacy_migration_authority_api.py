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
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import legacy_migration_authority as legacy_migration_authority_crud
from app.models.audit import AuditLog
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
