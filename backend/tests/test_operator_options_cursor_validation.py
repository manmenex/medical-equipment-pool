import base64
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import InvalidInputError
from app.crud import user as user_crud
from app.models.user import ROLE_ADMINISTRATOR
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Maintenance fix (cursor-hygiene technical debt recorded in
# docs/DECISION_LOG.md "Roadmap PR17 -- Operational Reports Complete" and
# GitHub PR #69): `app.crud.user.list_operators` decoded a cursor via the
# already-hardened `decode_alpha_cursor` (GitHub PR #68) but then performed
# its own `uuid.UUID(cursor_id)` conversion unguarded -- a structurally
# well-formed alpha cursor (valid Base64, valid JSON, has "v"/"id" keys)
# whose "id" is not a real UUID escaped as an uncaught exception (HTTP 500)
# rather than the repository-standard structured 400 INVALID_INPUT client
# error. This mirrors the exact fix `equipment_crud.list_for_verify_checklist`
# already applied for the same class of gap (PR68-Blocker3).
# ---------------------------------------------------------------------------


def _b64_json(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _assert_invalid_input_envelope(resp):
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"
    assert body["status"] == 400
    assert isinstance(body["detail"], str)
    assert "Traceback" not in body["detail"]
    assert "traceback" not in body
    assert set(body.keys()) == {"detail", "code", "status"}


# ---------------------------------------------------------------------------
# Unit tests: list_operators rejects a malformed cursor before any query
# runs (mirrors test_pr17_cursor_validation.py's
# test_verify_checklist_query_rejects_*_before_touching_the_database).
# ---------------------------------------------------------------------------


async def test_list_operators_rejects_cursor_with_non_uuid_id_before_touching_the_database():
    bad_cursor = _b64_json({"v": "สมชาย", "id": "not-a-uuid"})
    mock_db = AsyncMock()

    with pytest.raises(InvalidInputError) as exc_info:
        await user_crud.list_operators(mock_db, cursor=bad_cursor)

    assert exc_info.value.code == "INVALID_INPUT"
    # The count query and the paginated SELECT both go through db.execute --
    # neither may run once the cursor itself fails to validate, since a
    # count against the wrong (or no) row set would be a wasted, meaningless
    # query for a request that is about to be rejected anyway.
    mock_db.execute.assert_not_awaited()


async def test_list_operators_rejects_completely_malformed_cursor_before_touching_the_database():
    mock_db = AsyncMock()

    with pytest.raises(InvalidInputError):
        await user_crud.list_operators(mock_db, cursor="not-a-valid-cursor-at-all")

    mock_db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# API tests: GET /api/v1/report-options/operators
# ---------------------------------------------------------------------------


async def test_operator_options_valid_envelope_with_non_uuid_id_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cursor = _b64_json({"v": "สมชาย", "id": "not-a-uuid"})
    resp = await client.get(
        "/api/v1/report-options/operators", headers=admin, params={"cursor": cursor}
    )
    _assert_invalid_input_envelope(resp)


async def test_operator_options_invalid_base64_cursor_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/report-options/operators", headers=admin, params={"cursor": "%%%not-valid-base64%%%"}
    )
    _assert_invalid_input_envelope(resp)


async def test_operator_options_malformed_decoded_payload_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cursor = base64.urlsafe_b64encode(b'{"unexpected": "shape"}').decode()
    resp = await client.get(
        "/api/v1/report-options/operators", headers=admin, params={"cursor": cursor}
    )
    _assert_invalid_input_envelope(resp)


async def test_operator_options_cursor_missing_required_field_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cursor = base64.urlsafe_b64encode(json.dumps({"id": str(uuid.uuid4())}).encode()).decode()
    resp = await client.get(
        "/api/v1/report-options/operators", headers=admin, params={"cursor": cursor}
    )
    _assert_invalid_input_envelope(resp)


async def test_operator_options_unauthenticated_malformed_cursor_still_rejected_by_auth_first(
    client, seeded_users
):
    # Authorization is checked before the query layer ever runs regardless
    # of cursor content -- a malformed cursor must not leak a 400 to an
    # unauthenticated caller ahead of the existing 401 gate.
    cursor = _b64_json({"v": "สมชาย", "id": "not-a-uuid"})
    resp = await client.get("/api/v1/report-options/operators", params={"cursor": cursor})
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Regression: valid cursor pagination is unaffected by this fix.
# ---------------------------------------------------------------------------


async def test_operator_options_valid_cursor_round_trip_still_paginates(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/report-options/operators", headers=admin)
    assert resp.status_code == 200, resp.text

    resp2 = await client.get("/api/v1/report-options/operators", headers=admin, params={"limit": 1})
    assert resp2.status_code == 200, resp2.text
    next_cursor = resp2.json()["next_cursor"]
    if next_cursor:
        resp3 = await client.get(
            "/api/v1/report-options/operators", headers=admin, params={"limit": 1, "cursor": next_cursor}
        )
        assert resp3.status_code == 200, resp3.text
