import pytest

from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Roadmap PR17 Slice 2 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §8/§10/
# §11/§14/§17): API contract tests for GET /reports/receive, GET
# /reports/issue, GET /report-options/operators, and regression tests
# proving TransactionOut/GET /transactions/GET /transactions/{id} are
# unaffected by the new ReportTransactionOut schema.
# ---------------------------------------------------------------------------


async def _create_equipment(client, headers, asset_number: str, *, category_id: str | None = None):
    payload = {"asset_number": asset_number, "equipment_name": "Infusion Pump"}
    if category_id is not None:
        payload["category_id"] = category_id
    resp = await client.post("/api/v1/equipment", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_category(client, headers, name: str) -> str:
    resp = await client.post("/api/v1/categories", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _dispatch(client, headers, equipment_id: str, ward_id: str):
    resp = await client.post(
        "/api/v1/borrow",
        headers=headers,
        json={"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _receive(client, headers, transaction_id: str, *, receipt_outcome: str = "usable"):
    resp = await client.post(
        f"/api/v1/return/{transaction_id}", headers=headers, json={"receipt_outcome": receipt_outcome}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# GET /reports/receive
# ---------------------------------------------------------------------------


async def test_receive_report_authorized_roles_succeed(client, seeded_users):
    ward_id = await _create_ward(client, await _auth_headers(client, ROLE_ADMINISTRATOR), "W-PR17S2-1")
    for role in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        resp = await client.get("/api/v1/reports/receive", headers=headers, params={"ward_id": ward_id})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0


async def test_receive_report_unauthenticated_rejected_with_401(client, seeded_users):
    resp = await client.get("/api/v1/reports/receive")
    assert resp.status_code == 401, resp.text


async def test_receive_report_excludes_open_transaction(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-2")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0001")
    await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get("/api/v1/reports/receive", headers=admin, params={"ward_id": ward_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_receive_report_includes_closed_transaction_with_operator_display_names(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-3")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0002")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, admin, tx["id"])

    resp = await client.get("/api/v1/reports/receive", headers=admin, params={"ward_id": ward_id})
    assert resp.status_code == 200, resp.text
    (item,) = resp.json()["items"]
    assert item["id"] == tx["id"]
    assert item["dispatch_operator_display_name"] == "Test equipment_pool_staff"
    assert item["receipt_operator_display_name"] == "Test administrator"


async def test_receive_report_includes_defective_receipt(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-4")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0003")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, staff, tx["id"], receipt_outcome="defective")

    resp = await client.get("/api/v1/reports/receive", headers=admin, params={"ward_id": ward_id})
    (item,) = resp.json()["items"]
    assert item["receipt_outcome"] == "defective"


async def test_receive_report_category_filter_excludes_open_transaction(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-5")
    category_id = await _create_category(client, admin, "Cat PR17S2-5")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0004", category_id=category_id)
    await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get(
        "/api/v1/reports/receive", headers=admin, params={"equipment_category_id": category_id}
    )
    assert resp.json()["items"] == []


async def test_receive_report_reversed_business_date_range_rejected_with_400(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/receive",
        headers=admin,
        params={"business_date_from": "2026-07-31", "business_date_to": "2026-07-01"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# GET /reports/issue
# ---------------------------------------------------------------------------


async def test_issue_report_authorized_roles_succeed(client, seeded_users):
    for role in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        resp = await client.get("/api/v1/reports/issue", headers=headers)
        assert resp.status_code == 200, resp.text


async def test_issue_report_unauthenticated_rejected_with_401(client, seeded_users):
    resp = await client.get("/api/v1/reports/issue")
    assert resp.status_code == 401, resp.text


async def test_issue_report_includes_both_open_and_closed(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-6")
    open_eq = await _create_equipment(client, admin, "AST-PR17S2-0005")
    open_tx = await _dispatch(client, staff, open_eq["id"], ward_id)
    closed_eq = await _create_equipment(client, admin, "AST-PR17S2-0006")
    closed_tx = await _dispatch(client, staff, closed_eq["id"], ward_id)
    await _receive(client, staff, closed_tx["id"])

    resp = await client.get("/api/v1/reports/issue", headers=admin, params={"ward_id": ward_id})
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert ids == {open_tx["id"], closed_tx["id"]}


async def test_issue_report_dispatch_type_filter(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-7")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0007")
    resp = await client.post(
        "/api/v1/borrow",
        headers=staff,
        json={
            "equipment_id": eq["id"],
            "ward_id": ward_id,
            "dispatch_type": "routine_round",
            "routine_round": "06:00",
        },
    )
    assert resp.status_code == 201, resp.text
    tx = resp.json()

    resp_match = await client.get(
        "/api/v1/reports/issue", headers=admin, params={"ward_id": ward_id, "dispatch_type": "routine_round"}
    )
    assert [i["id"] for i in resp_match.json()["items"]] == [tx["id"]]

    resp_no_match = await client.get(
        "/api/v1/reports/issue", headers=admin, params={"ward_id": ward_id, "dispatch_type": "on_demand"}
    )
    assert resp_no_match.json()["items"] == []


async def test_issue_report_reversed_business_date_range_rejected_with_400(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/issue",
        headers=admin,
        params={"business_date_from": "2026-07-31", "business_date_to": "2026-07-01"},
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# API/schema boundary regression (PR17-H5): GET /transactions and GET
# /transactions/{id} must never expose the two report-only operator-display
# fields, whether the row involved has ever appeared on a report or not.
# ---------------------------------------------------------------------------


async def test_get_transactions_list_never_exposes_operator_display_fields(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-8")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0008")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, admin, tx["id"])

    resp = await client.get("/api/v1/transactions", headers=admin, params={"equipment_id": eq["id"]})
    assert resp.status_code == 200, resp.text
    (item,) = resp.json()["items"]
    assert "dispatch_operator_display_name" not in item
    assert "receipt_operator_display_name" not in item


async def test_get_transaction_detail_never_exposes_operator_display_fields(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-9")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0009")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, admin, tx["id"])

    resp = await client.get(f"/api/v1/transactions/{tx['id']}", headers=admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "dispatch_operator_display_name" not in body
    assert "receipt_operator_display_name" not in body


async def test_receive_report_returns_report_transaction_out_positive(client, seeded_users):
    """Positive counterpart of the negative tests above: the report
    endpoints themselves DO return both operator-display fields,
    correctly populated."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-10")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0010")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, admin, tx["id"])

    resp = await client.get("/api/v1/reports/receive", headers=admin, params={"ward_id": ward_id})
    (item,) = resp.json()["items"]
    assert item["dispatch_operator_display_name"] == "Test equipment_pool_staff"
    assert item["receipt_operator_display_name"] == "Test administrator"


# ---------------------------------------------------------------------------
# GET /report-options/operators
# ---------------------------------------------------------------------------


async def test_operator_lookup_authorized_roles_succeed(client, seeded_users):
    for role in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        resp = await client.get("/api/v1/report-options/operators", headers=headers)
        assert resp.status_code == 200, resp.text


async def test_operator_lookup_unauthenticated_rejected_with_401(client, seeded_users):
    resp = await client.get("/api/v1/report-options/operators")
    assert resp.status_code == 401, resp.text


async def test_operator_lookup_excludes_unrelated_user(client, seeded_users):
    """A Read Only account -- which can never dispatch/receive
    (EQUIPMENT_POOL_OPERATION_ROLES excludes it) -- must never appear,
    regardless of role membership (§10.4's Source / population rule)."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-11")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0011")
    await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get("/api/v1/report-options/operators", headers=admin)
    assert resp.status_code == 200, resp.text
    names = {item["display_name"] for item in resp.json()["items"]}
    assert "Test read_only" not in names
    assert "Test equipment_pool_staff" in names


async def test_operator_lookup_dispatch_only_and_dispatch_plus_receipt_both_appear_once(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-12")

    # staff dispatches tx1, never received -> staff referenced only via
    # borrower_user_id for this row.
    dispatch_only_eq = await _create_equipment(client, admin, "AST-PR17S2-0012")
    await _dispatch(client, staff, dispatch_only_eq["id"], ward_id)

    # admin dispatches tx2; staff receives it -> admin referenced via
    # borrower_user_id, staff referenced again via received_by_user_id
    # (the same operator appearing via both columns must still be a
    # single row in the response, never duplicated).
    both_eq = await _create_equipment(client, admin, "AST-PR17S2-0013")
    tx2 = await _dispatch(client, admin, both_eq["id"], ward_id)
    await _receive(client, staff, tx2["id"])

    resp = await client.get("/api/v1/report-options/operators", headers=admin)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    names = [item["display_name"] for item in items]
    assert names.count("Test equipment_pool_staff") == 1
    assert names.count("Test administrator") == 1


async def test_operator_lookup_inactive_operator_remains_listed(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-13")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0014")
    await _dispatch(client, staff, eq["id"], ward_id)

    staff_id = seeded_users[ROLE_EQUIPMENT_POOL_STAFF].id
    patch_resp = await client.patch(f"/api/v1/users/{staff_id}", headers=admin, json={"is_active": False})
    assert patch_resp.status_code == 200, patch_resp.text

    resp = await client.get("/api/v1/report-options/operators", headers=admin)
    assert resp.status_code == 200, resp.text
    (item,) = [i for i in resp.json()["items"] if i["display_name"] == "Test equipment_pool_staff"]
    assert item["is_active"] is False


async def test_operator_lookup_bounded_and_paginated(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-14")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0015")
    await _dispatch(client, staff, eq["id"], ward_id)
    eq2 = await _create_equipment(client, admin, "AST-PR17S2-0016")
    await _dispatch(client, admin, eq2["id"], ward_id)

    resp = await client.get("/api/v1/report-options/operators", headers=admin, params={"limit": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["total"] == 2
    assert body["next_cursor"] is not None

    resp_page_2 = await client.get(
        "/api/v1/report-options/operators", headers=admin, params={"limit": 1, "cursor": body["next_cursor"]}
    )
    assert resp_page_2.status_code == 200, resp_page_2.text
    body_2 = resp_page_2.json()
    assert len(body_2["items"]) == 1
    assert body_2["next_cursor"] is None
    assert body["items"][0]["id"] != body_2["items"][0]["id"]


async def test_operator_lookup_q_filters_by_name(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-15")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0017")
    await _dispatch(client, staff, eq["id"], ward_id)
    eq2 = await _create_equipment(client, admin, "AST-PR17S2-0018")
    await _dispatch(client, admin, eq2["id"], ward_id)

    resp = await client.get(
        "/api/v1/report-options/operators", headers=admin, params={"q": "equipment_pool_staff"}
    )
    assert resp.status_code == 200, resp.text
    names = {item["display_name"] for item in resp.json()["items"]}
    assert names == {"Test equipment_pool_staff"}


async def test_operator_lookup_response_excludes_sensitive_fields(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S2-16")
    eq = await _create_equipment(client, admin, "AST-PR17S2-0019")
    await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get("/api/v1/report-options/operators", headers=admin)
    assert resp.status_code == 200, resp.text
    (item,) = resp.json()["items"]
    assert set(item.keys()) == {"id", "display_name", "is_active"}


# ---------------------------------------------------------------------------
# PR66-H1 fix: GET /reports/receive, GET /reports/issue, and
# GET /report-options/operators must reject an invalid page size (limit=0,
# limit<0) with a 422 before the
# query layer ever runs, via plain FastAPI/Pydantic query validation
# (ge=1, le=200) -- not a domain-layer check. The 422 envelope's
# "code": "VALIDATION_ERROR" (app/main.py's RequestValidationError handler)
# is emitted only for request validation that never reached the route
# body/domain layer, distinct from the app's own DomainError envelope
# (e.g. "code": "INVALID_INPUT") a query-layer rejection would produce --
# asserting that shape is what proves validation happened before query
# execution in this black-box API test suite.
# ---------------------------------------------------------------------------


async def _assert_limit_rejected_before_query_layer(resp):
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert any(err["field"].endswith("limit") for err in body["errors"])


async def test_receive_report_limit_zero_rejected_with_422(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/reports/receive", headers=admin, params={"limit": 0})
    await _assert_limit_rejected_before_query_layer(resp)


async def test_receive_report_limit_negative_rejected_with_422(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/reports/receive", headers=admin, params={"limit": -1})
    await _assert_limit_rejected_before_query_layer(resp)


async def test_issue_report_limit_zero_rejected_with_422(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/reports/issue", headers=admin, params={"limit": 0})
    await _assert_limit_rejected_before_query_layer(resp)


async def test_issue_report_limit_negative_rejected_with_422(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/reports/issue", headers=admin, params={"limit": -1})
    await _assert_limit_rejected_before_query_layer(resp)


async def test_operator_lookup_limit_zero_rejected_with_422(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/report-options/operators", headers=admin, params={"limit": 0})
    await _assert_limit_rejected_before_query_layer(resp)


async def test_operator_lookup_limit_negative_rejected_with_422(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/report-options/operators", headers=admin, params={"limit": -1})
    await _assert_limit_rejected_before_query_layer(resp)
