from datetime import datetime, timedelta

import pytest

from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio


async def _create_equipment(client, headers, asset_number: str, name: str = "Infusion Pump"):
    resp = await client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": asset_number, "equipment_name": name}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _dispatch(
    client,
    headers,
    equipment_id: str,
    ward_id: str,
    *,
    dispatch_type: str,
    routine_round: str | None = None,
):
    payload = {"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": dispatch_type}
    if routine_round is not None:
        payload["routine_round"] = routine_round
    resp = await client.post("/api/v1/borrow", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _receive(client, headers, transaction_id: str):
    resp = await client.post(
        f"/api/v1/return/{transaction_id}", headers=headers, json={"receipt_outcome": "usable"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Roadmap PR13: dispatch_type / routine_round / date-range history filtering
# on GET /transactions (app/crud/transaction.py's search(), app/api/v1/
# transactions.py's list_transactions).
# ---------------------------------------------------------------------------


async def test_filter_by_dispatch_type_on_demand(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR13-1")

    on_demand_eq = await _create_equipment(client, admin, "AST-PR13-0001")
    routine_eq = await _create_equipment(client, admin, "AST-PR13-0002")
    await _dispatch(client, staff, on_demand_eq["id"], ward_id, dispatch_type="on_demand")
    await _dispatch(client, staff, routine_eq["id"], ward_id, dispatch_type="routine_round", routine_round="06:00")

    resp = await client.get("/api/v1/transactions", headers=admin, params={"dispatch_type": "on_demand"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["equipment"]["id"] == on_demand_eq["id"]
    assert body["items"][0]["dispatch_type"] == "on_demand"


async def test_filter_by_dispatch_type_routine_round(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR13-2")

    on_demand_eq = await _create_equipment(client, admin, "AST-PR13-0003")
    routine_eq = await _create_equipment(client, admin, "AST-PR13-0004")
    await _dispatch(client, staff, on_demand_eq["id"], ward_id, dispatch_type="on_demand")
    await _dispatch(client, staff, routine_eq["id"], ward_id, dispatch_type="routine_round", routine_round="11:00")

    resp = await client.get("/api/v1/transactions", headers=admin, params={"dispatch_type": "routine_round"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["equipment"]["id"] == routine_eq["id"]
    assert body["items"][0]["routine_round"] == "11:00"


async def test_filter_by_routine_round_value(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR13-3")

    eq_0600 = await _create_equipment(client, admin, "AST-PR13-0005")
    eq_1500 = await _create_equipment(client, admin, "AST-PR13-0006")
    await _dispatch(client, staff, eq_0600["id"], ward_id, dispatch_type="routine_round", routine_round="06:00")
    await _dispatch(client, staff, eq_1500["id"], ward_id, dispatch_type="routine_round", routine_round="15:00")

    resp = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"dispatch_type": "routine_round", "routine_round": "15:00"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["equipment"]["id"] == eq_1500["id"]


async def test_filter_by_date_range_includes_transactions_within_range(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR13-4")

    equipment = await _create_equipment(client, admin, "AST-PR13-0007")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")

    borrowed_date = datetime.fromisoformat(tx["borrowed_at"]).date()

    resp_in_range = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "from_date": str(borrowed_date - timedelta(days=1)),
            "to_date": str(borrowed_date + timedelta(days=1)),
        },
    )
    assert resp_in_range.status_code == 200, resp_in_range.text
    assert len(resp_in_range.json()["items"]) == 1

    resp_out_of_range = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "from_date": str(borrowed_date + timedelta(days=1)),
            "to_date": str(borrowed_date + timedelta(days=2)),
        },
    )
    assert resp_out_of_range.status_code == 200, resp_out_of_range.text
    assert resp_out_of_range.json()["items"] == []


async def test_filter_by_date_range_is_whole_day_inclusive_on_to_date(client, seeded_users):
    """to_date must include every transaction dispatched at any time during
    that calendar day, not just ones at or before midnight."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR13-5")

    equipment = await _create_equipment(client, admin, "AST-PR13-0008")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
    borrowed_date = datetime.fromisoformat(tx["borrowed_at"]).date()

    resp = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"equipment_id": equipment["id"], "from_date": str(borrowed_date), "to_date": str(borrowed_date)},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1


async def test_combined_dispatch_type_and_ward_filters(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_a = await _create_ward(client, admin, "W-PR13-6A")
    ward_b = await _create_ward(client, admin, "W-PR13-6B")

    eq_a = await _create_equipment(client, admin, "AST-PR13-0009")
    eq_b = await _create_equipment(client, admin, "AST-PR13-0010")
    await _dispatch(client, staff, eq_a["id"], ward_a, dispatch_type="on_demand")
    await _dispatch(client, staff, eq_b["id"], ward_b, dispatch_type="on_demand")

    resp = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"dispatch_type": "on_demand", "ward_id": ward_a},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["equipment"]["id"] == eq_a["id"]


async def test_dispatch_type_distinguishable_in_history_after_receipt(client, seeded_users):
    """Part H acceptance criterion: a completed on-demand dispatch must be
    distinguishable from a routine dispatch when viewed in history -- the
    field survives receipt/closing, not just while OPEN."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR13-7")

    equipment = await _create_equipment(client, admin, "AST-PR13-0011")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
    await _receive(client, staff, tx["id"])

    resp = await client.get(
        "/api/v1/transactions", headers=admin, params={"equipment_id": equipment["id"], "status": "closed"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["dispatch_type"] == "on_demand"
    assert body["items"][0]["routine_round"] is None


async def test_no_filters_returns_everything_unchanged(client, seeded_users):
    """Regression guard: all-new filter params are optional, so an
    unfiltered request must keep behaving exactly as before Roadmap PR13."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR13-8")

    equipment = await _create_equipment(client, admin, "AST-PR13-0012")
    await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")

    resp = await client.get(
        "/api/v1/transactions", headers=admin, params={"equipment_id": equipment["id"]}
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1


async def test_invalid_dispatch_type_value_rejected_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/transactions", headers=admin, params={"dispatch_type": "not-a-real-type"})
    assert resp.status_code == 422


async def test_invalid_date_value_rejected_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/transactions", headers=admin, params={"from_date": "not-a-date"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Review fix (correctness): date-range edge cases. The original
# `to_date + timedelta(days=1)` upper-bound arithmetic could raise
# OverflowError for `to_date=9999-12-31` (Python's date.max), an ordinary
# ISO date string a client can send -- that would have surfaced as an
# unhandled 500, not a clean validation response. The fix computes the
# upper bound as `to_date` at `time.max` instead of incrementing the date,
# which can never overflow, and the API layer now rejects a reversed range
# (from_date > to_date) outright with a 400 before it ever reaches
# transaction_crud.search().
# ---------------------------------------------------------------------------


async def test_to_date_at_date_max_does_not_raise_overflow_error(client, seeded_users):
    """Regression test: to_date=9999-12-31 (date.max) must not crash the
    server -- it is an ordinary, syntactically valid ISO date string."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/transactions", headers=admin, params={"to_date": "9999-12-31"})
    assert resp.status_code == 200, resp.text


async def test_from_date_at_date_min_does_not_raise(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/transactions", headers=admin, params={"from_date": "0001-01-01"})
    assert resp.status_code == 200, resp.text


async def test_reversed_date_range_rejected_with_structured_400(client, seeded_users):
    """from_date after to_date can never match anything -- rejected
    explicitly rather than silently returning an empty page."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"from_date": "2026-07-31", "to_date": "2026-07-01"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"
    assert "from_date" in body["detail"]
    assert "to_date" in body["detail"]


async def test_reversed_date_range_at_the_extreme_still_rejected_not_500(client, seeded_users):
    """Combines both edge cases: a reversed range where to_date is also
    date.max must still be a clean 400, never an OverflowError-driven 500."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"from_date": "9999-12-31", "to_date": "0001-01-01"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_equal_from_and_to_date_is_a_valid_single_day_range(client, seeded_users):
    """from_date == to_date is not a reversed range -- it is a valid,
    whole-day-inclusive single-day filter."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR13-9")

    equipment = await _create_equipment(client, admin, "AST-PR13-0013")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
    borrowed_date = datetime.fromisoformat(tx["borrowed_at"]).date()

    resp = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "from_date": str(borrowed_date),
            "to_date": str(borrowed_date),
        },
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1


async def test_omitted_dates_leave_behavior_unchanged(client, seeded_users):
    """Regression guard: from_date/to_date are independently optional --
    omitting both (the pre-PR13 request shape) must behave exactly as
    before, and omitting just one must not implicitly bound the other."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR13-10")

    equipment = await _create_equipment(client, admin, "AST-PR13-0014")
    await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")

    resp_no_dates = await client.get(
        "/api/v1/transactions", headers=admin, params={"equipment_id": equipment["id"]}
    )
    assert resp_no_dates.status_code == 200, resp_no_dates.text
    assert len(resp_no_dates.json()["items"]) == 1

    resp_from_only = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"equipment_id": equipment["id"], "from_date": "0001-01-01"},
    )
    assert resp_from_only.status_code == 200, resp_from_only.text
    assert len(resp_from_only.json()["items"]) == 1

    resp_to_only = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"equipment_id": equipment["id"], "to_date": "9999-12-31"},
    )
    assert resp_to_only.status_code == 200, resp_to_only.text
    assert len(resp_to_only.json()["items"]) == 1
