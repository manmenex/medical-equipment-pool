import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.exceptions import ImportSessionInvalidStateError
from app.crud import import_session as import_crud
from app.models.import_session import ImportSession, ImportSource
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

VALID_CHECKSUM = "a" * 64


async def _create_session(client: AsyncClient, headers: dict, *, dataset_type: str = "equipment", idempotency_key: str | None = None):
    payload = {"dataset_type": dataset_type}
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    return await client.post("/api/v1/import-sessions", headers=headers, json=payload)


# ---------------------------------------------------------------------------
# §15.1 Session creation idempotency
# ---------------------------------------------------------------------------


async def test_create_session_without_idempotency_key_always_creates_new(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r1 = await _create_session(client, headers)
    r2 = await _create_session(client, headers)
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    assert r1.json()["id"] != r2.json()["id"]


async def test_create_session_with_idempotency_key_replays(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r1 = await _create_session(client, headers, idempotency_key="batch-001")
    r2 = await _create_session(client, headers, idempotency_key="batch-001")
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] == r2.json()["id"]


async def test_create_session_different_dataset_type_same_key_is_distinct(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r1 = await _create_session(client, headers, dataset_type="equipment", idempotency_key="k1")
    r2 = await _create_session(client, headers, dataset_type="receive_history", idempotency_key="k1")
    assert r1.json()["id"] != r2.json()["id"]


async def test_create_session_requires_administrator(client: AsyncClient, seeded_users):
    headers = await auth_headers(client, role="equipment_pool_staff")
    r = await _create_session(client, headers)
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# §21 endpoint #2/#3/#4 -- list, summary, status
# ---------------------------------------------------------------------------


async def test_get_session_summary_and_status(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    created = (await _create_session(client, headers)).json()

    summary = await client.get(f"/api/v1/import-sessions/{created['id']}", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["status"] == "created"

    status = await client.get(f"/api/v1/import-sessions/{created['id']}/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["version"] == 0


async def test_get_session_summary_404_for_unknown_id(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.get(f"/api/v1/import-sessions/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404
    assert r.json()["code"] == "IMPORT_SESSION_NOT_FOUND"


async def test_list_sessions_pagination_and_next_cursor(client: AsyncClient, db_session, seeded_users):
    # Rows are inserted directly with explicit, one-second-apart `created_at`
    # values (rather than via three back-to-back HTTP creates) so the
    # `created_at DESC, id DESC` ordering this test asserts on is
    # deterministic. SQLite's `server_default=func.now()` only has
    # whole-second resolution (`CURRENT_TIMESTAMP`), so three rapid HTTP
    # creates can land in the same second -- a real, dialect-specific
    # scenario, but one this test isn't trying to exercise; it exists to
    # verify the cursor's page-boundary arithmetic, not same-instant
    # tie-break behavior under SQLite's text-based datetime comparison.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    admin = seeded_users["administrator"]
    for i in range(3):
        db_session.add(
            ImportSession(
                dataset_type="pagination-test",
                status="created",
                version=0,
                created_by_user_id=admin.id,
                created_at=base + timedelta(seconds=i),
                updated_at=base + timedelta(seconds=i),
            )
        )
    await db_session.commit()

    headers = await auth_headers(client)
    page1 = await client.get(
        "/api/v1/import-sessions", headers=headers, params={"dataset_type": "pagination-test", "limit": 2}
    )
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert body1["total"] == 3
    assert body1["next_cursor"] is not None

    page2 = await client.get(
        "/api/v1/import-sessions",
        headers=headers,
        params={"dataset_type": "pagination-test", "limit": 2, "cursor": body1["next_cursor"]},
    )
    body2 = page2.json()
    assert len(body2["items"]) == 1
    assert body2["next_cursor"] is None
    seen_ids = {i["id"] for i in body1["items"]} | {i["id"] for i in body2["items"]}
    assert len(seen_ids) == 3


async def test_list_sessions_rejects_zero_limit(client: AsyncClient, seeded_users):
    # §20/M1: `ge=1` -- zero must be rejected, never silently clamped to 1.
    headers = await auth_headers(client)
    r = await client.get("/api/v1/import-sessions", headers=headers, params={"limit": 0})
    assert r.status_code == 422


async def test_list_sessions_rejects_malformed_cursor(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.get("/api/v1/import-sessions", headers=headers, params={"cursor": "not-valid-base64json!!"})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_INPUT"


async def test_list_sessions_rejects_cursor_with_non_uuid_id(client: AsyncClient, seeded_users):
    import base64
    import json

    bad_cursor = base64.urlsafe_b64encode(
        json.dumps({"t": "2026-01-01T00:00:00+00:00", "id": "not-a-uuid"}).encode()
    ).decode()
    headers = await auth_headers(client)
    r = await client.get("/api/v1/import-sessions", headers=headers, params={"cursor": bad_cursor})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# §15.2 Source registration -- create, idempotent no-op, correction, mismatch
# ---------------------------------------------------------------------------


async def test_register_source_first_call_creates(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": VALID_CHECKSUM, "byte_size": 100},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "registered"


async def test_register_source_identical_resubmission_is_idempotent_noop(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    payload = {"checksum": VALID_CHECKSUM, "byte_size": 100, "filename": "legacy.xlsx"}
    r1 = await client.post(f"/api/v1/import-sessions/{session['id']}/source", headers=headers, json=payload)
    r2 = await client.post(f"/api/v1/import-sessions/{session['id']}/source", headers=headers, json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


async def test_register_source_pre_freeze_correction_overwrites(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    first = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": VALID_CHECKSUM, "byte_size": 100},
    )
    corrected = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": "b" * 64, "byte_size": 200},
    )
    assert corrected.status_code == 200
    assert corrected.json()["id"] == first.json()["id"]
    assert corrected.json()["checksum"] == "b" * 64
    assert corrected.json()["byte_size"] == 200


async def test_register_source_rejects_short_checksum(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source", headers=headers, json={"checksum": "tooshort", "byte_size": 1}
    )
    assert r.status_code == 422


async def test_register_source_404_for_unknown_session(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post(
        f"/api/v1/import-sessions/{uuid.uuid4()}/source",
        headers=headers,
        json={"checksum": VALID_CHECKSUM, "byte_size": 1},
    )
    assert r.status_code == 404


async def test_register_source_after_freeze_matching_fingerprint_is_noop(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    payload = {"checksum": VALID_CHECKSUM, "byte_size": 100}
    await client.post(f"/api/v1/import-sessions/{session['id']}/source", headers=headers, json=payload)

    # §6: freeze is a system-performed side effect of validate admission --
    # no /validate endpoint ships with PR19A1, so exercise the reusable
    # crud primitive directly, exactly as PR19A2's validate admission will.
    await import_crud.freeze_source_and_transition_to_validating(
        db_session, session_id=uuid.UUID(session["id"]), expected_version=0
    )

    r = await client.post(f"/api/v1/import-sessions/{session['id']}/source", headers=headers, json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "frozen"


async def test_register_source_after_freeze_differing_fingerprint_is_mismatch(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": VALID_CHECKSUM, "byte_size": 100},
    )
    await import_crud.freeze_source_and_transition_to_validating(
        db_session, session_id=uuid.UUID(session["id"]), expected_version=0
    )

    r = await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": "c" * 64, "byte_size": 999},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_SOURCE_MISMATCH"

    # The row is never mutated once frozen.
    row = (
        await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == uuid.UUID(session["id"])))
    ).scalar_one()
    assert row.checksum == VALID_CHECKSUM
    assert row.byte_size == 100


async def test_freeze_is_irreversible_and_atomic_with_session_transition(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": VALID_CHECKSUM, "byte_size": 100},
    )
    session_id = uuid.UUID(session["id"])
    source_existed, session_row = await import_crud.freeze_source_and_transition_to_validating(
        db_session, session_id=session_id, expected_version=0
    )
    assert source_existed is True
    assert session_row is not None
    assert session_row.status == "validating"
    assert session_row.version == 1

    source = (await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))).scalar_one()
    assert source.status == "frozen"
    assert source.frozen_at is not None

    # Re-freezing (idempotent no-op on the source; session CAS re-evaluated
    # from its new state) does not un-freeze or re-set frozen_at.
    frozen_at_before = source.frozen_at
    await import_crud.freeze_source_and_transition_to_validating(db_session, session_id=session_id, expected_version=1)
    await db_session.refresh(source)
    assert source.frozen_at == frozen_at_before


async def test_freeze_fails_stale_version_does_not_mutate_source(client: AsyncClient, seeded_users, db_session):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    await client.post(
        f"/api/v1/import-sessions/{session['id']}/source",
        headers=headers,
        json={"checksum": VALID_CHECKSUM, "byte_size": 100},
    )
    session_id = uuid.UUID(session["id"])
    # Wrong expected_version -> session CAS fails -> whole transaction
    # rolls back, including the freeze half.
    _, session_row = await import_crud.freeze_source_and_transition_to_validating(
        db_session, session_id=session_id, expected_version=99
    )
    assert session_row is None
    source = (await db_session.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))).scalar_one()
    assert source.status == "registered"


# ---------------------------------------------------------------------------
# §7 CAS / §21 endpoint #6 -- cancel
# ---------------------------------------------------------------------------


async def test_cancel_session_from_created(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/cancel", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert r.json()["version"] == 1


async def test_cancel_already_cancelled_session_is_invalid_state(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    session = (await _create_session(client, headers)).json()
    await client.post(f"/api/v1/import-sessions/{session['id']}/cancel", headers=headers)
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/cancel", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "IMPORT_SESSION_INVALID_STATE"


async def test_cancel_session_404_for_unknown_id(client: AsyncClient, seeded_users):
    headers = await auth_headers(client)
    r = await client.post(f"/api/v1/import-sessions/{uuid.uuid4()}/cancel", headers=headers)
    assert r.status_code == 404


async def test_cancel_session_requires_administrator(client: AsyncClient, seeded_users):
    admin_headers = await auth_headers(client)
    session = (await _create_session(client, admin_headers)).json()
    staff_headers = await auth_headers(client, role="equipment_pool_staff")
    r = await client.post(f"/api/v1/import-sessions/{session['id']}/cancel", headers=staff_headers)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# §7's CAS guard, exercised directly at the crud layer (a lost race must
# never proceed as if it had won).
# ---------------------------------------------------------------------------


async def test_cancel_session_stale_version_is_rejected(db_session, seeded_users):
    from app.models.user import ROLE_ADMINISTRATOR, Role

    role = (await db_session.execute(select(Role).where(Role.name == ROLE_ADMINISTRATOR))).scalar_one()
    session, _ = await import_crud.get_or_create_session(
        db_session, dataset_type="equipment", idempotency_key=None, notes=None, created_by_user_id=seeded_users[ROLE_ADMINISTRATOR].id
    )
    await db_session.commit()

    with pytest.raises(ImportSessionInvalidStateError):
        await import_crud.cancel_session(db_session, session_id=session.id, expected_version=99)
