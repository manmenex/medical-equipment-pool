import base64
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import InvalidInputError
from app.crud import equipment as equipment_crud
from app.models.user import ROLE_ADMINISTRATOR
from app.utils.pagination import decode_alpha_cursor, decode_cursor
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# PR68 Incremental Fix, Blocker 3: a malformed client-supplied cursor must
# return the repository-standard structured client error (400
# INVALID_INPUT, the same DomainError envelope already used for the
# business_date_from > business_date_to check on these same report
# endpoints -- app/main.py's domain_error_handler), never an uncaught
# exception reaching the generic 500 handler.
#
# The fix lives at the shared layer both `decode_cursor` (equipment/
# transaction cursors) and `decode_alpha_cursor` (the operator lookup's
# cursor) already go through (app/utils/pagination.py), plus the one
# further parsing step `equipment_crud.list_for_verify_checklist` performs
# itself (the decoded `id` field must be a valid UUID). Unit tests below
# exercise the parsing functions directly; API tests below exercise the
# full HTTP contract for the new Equipment Verify Checklist endpoint this
# PR adds; regression tests confirm no existing cursor-consuming endpoint
# regresses.
# ---------------------------------------------------------------------------


def _b64_json(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


# ---------------------------------------------------------------------------
# Unit tests: app/utils/pagination.py's decode_cursor / decode_alpha_cursor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malformed_cursor",
    [
        "",  # empty string
        "not-base64-at-all!!!",  # invalid Base64 alphabet
        base64.urlsafe_b64encode(b"not json at all").decode(),  # valid Base64, invalid JSON
        _b64_json({"t": "2026-07-30T00:00:00+00:00"}),  # missing "id"
        _b64_json({"id": "op-1"}),  # missing "t"
        _b64_json({"t": "not-a-real-timestamp", "id": "op-1"}),  # unparseable timestamp
        _b64_json({"t": 12345, "id": "op-1"}),  # wrong type for "t"
    ],
)
async def test_decode_cursor_rejects_malformed_input_with_invalid_input_error(malformed_cursor):
    with pytest.raises(InvalidInputError) as exc_info:
        decode_cursor(malformed_cursor)
    assert exc_info.value.code == "INVALID_INPUT"
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    "malformed_cursor",
    [
        "",
        "not-base64-at-all!!!",
        base64.urlsafe_b64encode(b"not json at all").decode(),
        _b64_json({"v": "สมชาย"}),  # missing "id"
        _b64_json({"id": "op-1"}),  # missing "v"
    ],
)
async def test_decode_alpha_cursor_rejects_malformed_input_with_invalid_input_error(malformed_cursor):
    with pytest.raises(InvalidInputError) as exc_info:
        decode_alpha_cursor(malformed_cursor)
    assert exc_info.value.code == "INVALID_INPUT"
    assert exc_info.value.status_code == 400


async def test_decode_cursor_accepts_a_well_formed_cursor():
    cursor = _b64_json({"t": "2026-07-30T00:00:00+00:00", "id": "eq-1"})
    dt, id_ = decode_cursor(cursor)
    assert id_ == "eq-1"
    assert dt.year == 2026


# ---------------------------------------------------------------------------
# Unit test: list_for_verify_checklist's own further parsing (id must be a
# valid UUID) also raises InvalidInputError, and the query layer (the
# actual database call) is never reached for a malformed cursor.
# ---------------------------------------------------------------------------


async def test_verify_checklist_query_rejects_cursor_with_invalid_uuid_before_touching_the_database():
    bad_cursor = _b64_json({"t": "2026-07-30T00:00:00+00:00", "id": "not-a-uuid"})
    mock_db = AsyncMock()

    with pytest.raises(InvalidInputError) as exc_info:
        await equipment_crud.list_for_verify_checklist(mock_db, cursor=bad_cursor)

    assert exc_info.value.code == "INVALID_INPUT"
    # The count query and the paginated SELECT both go through db.execute --
    # neither may run once the cursor itself fails to parse, since a count
    # against the wrong (or no) row set would be a wasted, meaningless
    # query for a request that is about to be rejected anyway.
    mock_db.execute.assert_not_awaited()


async def test_verify_checklist_query_rejects_completely_malformed_cursor_before_touching_the_database():
    mock_db = AsyncMock()

    with pytest.raises(InvalidInputError):
        await equipment_crud.list_for_verify_checklist(mock_db, cursor="not-a-valid-cursor-at-all")

    mock_db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# API tests: GET /reports/equipment-verify-checklist
# ---------------------------------------------------------------------------


def _assert_invalid_input_envelope(resp):
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"
    assert body["status"] == 400
    assert isinstance(body["detail"], str)
    # No internal exception details, type names, or traceback text leak
    # into the client-facing envelope.
    assert "Traceback" not in body["detail"]
    assert "traceback" not in body
    assert set(body.keys()) == {"detail", "code", "status"}


async def test_verify_checklist_completely_invalid_cursor_text_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist", headers=admin, params={"cursor": "%%%not-valid-base64%%%"}
    )
    _assert_invalid_input_envelope(resp)


async def test_verify_checklist_decodable_cursor_with_malformed_payload_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cursor = base64.urlsafe_b64encode(b'{"unexpected": "shape"}').decode()
    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist", headers=admin, params={"cursor": cursor}
    )
    _assert_invalid_input_envelope(resp)


async def test_verify_checklist_cursor_with_invalid_uuid_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cursor = _b64_json({"t": "2026-07-30T00:00:00+00:00", "id": "not-a-uuid"})
    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist", headers=admin, params={"cursor": cursor}
    )
    _assert_invalid_input_envelope(resp)


async def test_verify_checklist_cursor_with_invalid_timestamp_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cursor = _b64_json({"t": "definitely-not-a-timestamp", "id": str(uuid.uuid4())})
    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist", headers=admin, params={"cursor": cursor}
    )
    _assert_invalid_input_envelope(resp)


async def test_verify_checklist_cursor_missing_required_fields_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cursor = base64.urlsafe_b64encode(json.dumps({"id": str(uuid.uuid4())}).encode()).decode()
    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist", headers=admin, params={"cursor": cursor}
    )
    _assert_invalid_input_envelope(resp)


async def test_verify_checklist_unauthenticated_malformed_cursor_still_rejected_by_auth_first(client, seeded_users):
    # Authorization is checked before the query layer ever runs regardless
    # of cursor content -- a malformed cursor must not leak a 400 to an
    # unauthenticated caller ahead of the existing 401 gate.
    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist", params={"cursor": "%%%not-valid-base64%%%"}
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Regression: existing Receive/Issue/operator-lookup endpoints and their
# valid-cursor behavior are unaffected by the shared decode_cursor/
# decode_alpha_cursor fix.
# ---------------------------------------------------------------------------


async def test_receive_report_malformed_cursor_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/receive", headers=admin, params={"cursor": "%%%not-valid-base64%%%"}
    )
    _assert_invalid_input_envelope(resp)


async def test_issue_report_malformed_cursor_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/issue", headers=admin, params={"cursor": "%%%not-valid-base64%%%"}
    )
    _assert_invalid_input_envelope(resp)


async def test_operator_options_malformed_cursor_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/report-options/operators", headers=admin, params={"cursor": "%%%not-valid-base64%%%"}
    )
    _assert_invalid_input_envelope(resp)


async def test_equipment_list_malformed_cursor_returns_400_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/equipment", headers=admin, params={"cursor": "%%%not-valid-base64%%%"})
    _assert_invalid_input_envelope(resp)


async def test_receive_report_reachable_with_no_cursor_after_the_fix(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    ward_id = await _create_ward(client, admin, "W-CURSORFIX-1")
    resp = await client.get("/api/v1/reports/receive", headers=admin, params={"ward_id": ward_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


async def test_operator_options_reachable_and_paginates_correctly_after_the_fix(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/report-options/operators", headers=admin)
    assert resp.status_code == 200, resp.text

    # A real, valid cursor round-trip (encode -> decode) must still work --
    # the fix only rejects malformed input, it never rejects a cursor this
    # same API itself produced.
    resp2 = await client.get("/api/v1/report-options/operators", headers=admin, params={"limit": 1})
    assert resp2.status_code == 200, resp2.text
    next_cursor = resp2.json()["next_cursor"]
    if next_cursor:
        resp3 = await client.get(
            "/api/v1/report-options/operators", headers=admin, params={"limit": 1, "cursor": next_cursor}
        )
        assert resp3.status_code == 200, resp3.text


async def test_equipment_list_reachable_with_no_cursor_after_the_fix(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/equipment", headers=admin)
    assert resp.status_code == 200, resp.text
