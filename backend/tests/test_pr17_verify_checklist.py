import pytest

from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Roadmap PR17 Slice 4 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
# §7.3(A)/§8/§10.3/§14/§17/§18 Owner Decision #1 resolved to interpretation
# A): API contract tests for GET /reports/equipment-verify-checklist -- a
# read-only, current-state equipment master/status listing, not a
# transaction/event report. Also asserts the existing Receive/Issue Report
# endpoints, TransactionOut, ReportTransactionOut, and the operator lookup
# endpoint remain unaffected by this slice (Existing Contract Protection).
# ---------------------------------------------------------------------------


async def _create_category(client, headers, name: str) -> str:
    resp = await client.post("/api/v1/categories", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_department(client, headers, code: str, name: str | None = None) -> str:
    resp = await client.post("/api/v1/departments", headers=headers, json={"code": code, "name": name or code})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_equipment(
    client, headers, asset_number: str, *, category_id: str | None = None, department_owner_id: str | None = None
):
    payload = {"asset_number": asset_number, "equipment_name": "Infusion Pump"}
    if category_id is not None:
        payload["category_id"] = category_id
    if department_owner_id is not None:
        payload["department_owner_id"] = department_owner_id
    resp = await client.post("/api/v1/equipment", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def test_verify_checklist_authorized_roles_succeed(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    category_id = await _create_category(client, admin, "VC-Cat-Auth")
    await _create_equipment(client, admin, "AST-PR17S4-0001", category_id=category_id)

    for role in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        resp = await client.get(
            "/api/v1/reports/equipment-verify-checklist", headers=headers, params={"equipment_category_id": category_id}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["asset_number"] == "AST-PR17S4-0001"


async def test_verify_checklist_unauthenticated_rejected_with_401(client, seeded_users):
    resp = await client.get("/api/v1/reports/equipment-verify-checklist")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Query semantics -- filters and current-state (not transaction-shaped)
# ---------------------------------------------------------------------------


async def test_verify_checklist_filters_by_equipment_category(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cat_a = await _create_category(client, admin, "VC-Cat-A")
    cat_b = await _create_category(client, admin, "VC-Cat-B")
    await _create_equipment(client, admin, "AST-PR17S4-0002", category_id=cat_a)
    await _create_equipment(client, admin, "AST-PR17S4-0003", category_id=cat_b)

    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist", headers=admin, params={"equipment_category_id": cat_a}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["asset_number"] == "AST-PR17S4-0002"


async def test_verify_checklist_filters_by_status(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    cat = await _create_category(client, admin, "VC-Cat-Status")
    eq = await _create_equipment(client, admin, "AST-PR17S4-0004", category_id=cat)
    await client.post(
        f"/api/v1/equipment/{eq['id']}/status",
        headers=staff,
        json={"status": "unavailable_defective", "reason": "test"},
    )

    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist",
        headers=admin,
        params={"equipment_category_id": cat, "status": "unavailable_defective"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["asset_number"] == "AST-PR17S4-0004"
    assert body["items"][0]["status"] == "unavailable_defective"

    resp2 = await client.get(
        "/api/v1/reports/equipment-verify-checklist",
        headers=admin,
        params={"equipment_category_id": cat, "status": "available_at_pool"},
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["total"] == 0


async def test_verify_checklist_filters_by_department(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cat = await _create_category(client, admin, "VC-Cat-Dept")
    dept_a = await _create_department(client, admin, "VC-Dept-A")
    dept_b = await _create_department(client, admin, "VC-Dept-B")
    await _create_equipment(client, admin, "AST-PR17S4-0005", category_id=cat, department_owner_id=dept_a)
    await _create_equipment(client, admin, "AST-PR17S4-0006", category_id=cat, department_owner_id=dept_b)

    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist",
        headers=admin,
        params={"equipment_category_id": cat, "department_id": dept_a},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["asset_number"] == "AST-PR17S4-0005"


async def test_verify_checklist_excludes_soft_deleted_equipment(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cat = await _create_category(client, admin, "VC-Cat-Deleted")
    eq = await _create_equipment(client, admin, "AST-PR17S4-0007", category_id=cat)

    resp = await client.delete(f"/api/v1/equipment/{eq['id']}", headers=admin)
    assert resp.status_code == 204, resp.text

    resp2 = await client.get(
        "/api/v1/reports/equipment-verify-checklist", headers=admin, params={"equipment_category_id": cat}
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["total"] == 0


async def test_verify_checklist_response_shape_matches_equipment_out(client, seeded_users):
    """§8/§10.3: response rows are EquipmentOut -- the exact same shape
    GET /equipment already returns, no new fields invented, and never
    item_no (See ADR-002/ADR-003)."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cat = await _create_category(client, admin, "VC-Cat-Shape")
    await _create_equipment(client, admin, "AST-PR17S4-0008", category_id=cat)

    checklist_resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist", headers=admin, params={"equipment_category_id": cat}
    )
    equipment_resp = await client.get("/api/v1/equipment", headers=admin, params={"category_id": cat})
    assert checklist_resp.status_code == 200, checklist_resp.text
    assert equipment_resp.status_code == 200, equipment_resp.text
    (checklist_item,) = checklist_resp.json()["items"]
    (equipment_item,) = equipment_resp.json()["items"]
    assert set(checklist_item.keys()) == set(equipment_item.keys())
    assert "item_no" not in checklist_item


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


# A genuine multi-page cursor walk (limit smaller than the row count,
# repeated "load more" calls, asserting no row repeats and every row is
# eventually seen) is intentionally NOT exercised against SQLite here.
# `TimestampMixin.created_at` uses `server_default=func.now()`, which
# SQLite resolves to `CURRENT_TIMESTAMP` -- a second-precision, offset-less
# TEXT literal. A cursor's own bind parameter is a tz-aware, microsecond-
# precision Python datetime, which SQLAlchemy's SQLite dialect renders as
# TEXT *with* a trailing "+00:00" offset. Comparing these two differently
# -formatted TEXT values is a lexicographic string comparison, not a true
# instant comparison: a row's own stored value (e.g. '2026-07-29
# 16:23:55') is a strict *prefix* of its own cursor's bind literal
# ('2026-07-29 16:23:55+00:00'), so SQLite's `created_at < cursor_dt`
# incorrectly evaluates True for that row against itself, and the row is
# never excluded from the next page. This is a pre-existing defect in the
# shared `created_at DESC, id DESC` cursor pattern every equipment/
# transaction list query in this codebase already uses (confirmed to
# equally affect the already-merged `equipment_crud.search()` and
# `transaction_crud.search()`, not something this slice introduces) --
# fixing `UTCDateTime`/`TimestampMixin` themselves is out of this narrow
# slice's scope. Real multi-page pagination evidence is instead given
# against PostgreSQL (whose `timestamptz` has no such textual-format
# ambiguity), in
# test_postgres_integration.py::test_verify_checklist_cursor_pagination_no_duplicates_no_missing_rows_on_postgres.
# The two tests below cover what SQLite *can* verify reliably: a page
# respects `limit` and reports `next_cursor` correctly at both the
# not-yet-exhausted and fully-exhausted boundaries, and the UUID-typed
# half of the cursor's own tie-break comparison (`Equipment.id <
# uuid.UUID(cursor_id)`, not `cast(..., String)`) is exercised whenever
# the query executes at all.


async def test_verify_checklist_pagination_first_page_respects_limit_and_reports_next_cursor(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cat = await _create_category(client, admin, "VC-Cat-Page")
    for i in range(3):
        await _create_equipment(client, admin, f"AST-PR17S4-P{i:02d}", category_id=cat)

    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist", headers=admin, params={"equipment_category_id": cat, "limit": 2}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["next_cursor"] is not None


async def test_verify_checklist_pagination_final_page_has_no_next_cursor(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    cat = await _create_category(client, admin, "VC-Cat-Page-Final")
    for i in range(3):
        await _create_equipment(client, admin, f"AST-PR17S4-F{i:02d}", category_id=cat)

    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist",
        headers=admin,
        params={"equipment_category_id": cat, "limit": 10},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 3
    assert body["total"] == 3
    assert body["next_cursor"] is None


async def test_verify_checklist_limit_zero_rejected_with_422(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/reports/equipment-verify-checklist", headers=admin, params={"limit": 0})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert any(err["field"].endswith("limit") for err in body["errors"])


async def test_verify_checklist_limit_negative_rejected_with_422(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/reports/equipment-verify-checklist", headers=admin, params={"limit": -1})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert any(err["field"].endswith("limit") for err in body["errors"])


# ---------------------------------------------------------------------------
# Existing Contract Protection: Receive/Issue reports and the operator
# lookup endpoint are unaffected by this slice.
# ---------------------------------------------------------------------------


async def test_receive_and_issue_reports_still_reachable_and_unaffected(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    receive_resp = await client.get("/api/v1/reports/receive", headers=admin)
    issue_resp = await client.get("/api/v1/reports/issue", headers=admin)
    operators_resp = await client.get("/api/v1/report-options/operators", headers=admin)
    assert receive_resp.status_code == 200, receive_resp.text
    assert issue_resp.status_code == 200, issue_resp.text
    assert operators_resp.status_code == 200, operators_resp.text
