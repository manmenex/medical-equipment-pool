import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.core.reporting_time import business_date_and_shift
from app.models.transaction import BorrowTransaction
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


# ---------------------------------------------------------------------------
# Roadmap PR16 Slice 2: dispatch_business_date/dispatch_shift/
# receipt_business_date/receipt_shift surface correctly on both GET
# /transactions and GET /transactions/{id}, for both open and closed
# transactions (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md §16 Slice 2
# acceptance criteria).
# ---------------------------------------------------------------------------


async def test_reporting_time_fields_present_on_open_transaction_via_list_and_detail(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR16-1")

    equipment = await _create_equipment(client, admin, "AST-PR16-0001")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")

    list_resp = await client.get(
        "/api/v1/transactions", headers=admin, params={"equipment_id": equipment["id"]}
    )
    assert list_resp.status_code == 200, list_resp.text
    (list_item,) = list_resp.json()["items"]
    assert list_item["dispatch_business_date"] is not None
    assert list_item["dispatch_shift"] in ("day", "night")
    assert list_item["receipt_business_date"] is None
    assert list_item["receipt_shift"] is None

    detail_resp = await client.get(f"/api/v1/transactions/{tx['id']}", headers=admin)
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["dispatch_business_date"] == list_item["dispatch_business_date"]
    assert detail["dispatch_shift"] == list_item["dispatch_shift"]
    assert detail["receipt_business_date"] is None
    assert detail["receipt_shift"] is None


async def test_reporting_time_fields_present_on_closed_transaction_via_list_and_detail(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR16-2")

    equipment = await _create_equipment(client, admin, "AST-PR16-0002")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
    await _receive(client, staff, tx["id"])

    list_resp = await client.get(
        "/api/v1/transactions", headers=admin, params={"equipment_id": equipment["id"]}
    )
    assert list_resp.status_code == 200, list_resp.text
    (list_item,) = list_resp.json()["items"]
    assert list_item["dispatch_business_date"] is not None
    assert list_item["dispatch_shift"] in ("day", "night")
    # Once received, receipt_business_date/receipt_shift must be populated
    # -- never None for a closed transaction.
    assert list_item["receipt_business_date"] is not None
    assert list_item["receipt_shift"] in ("day", "night")

    detail_resp = await client.get(f"/api/v1/transactions/{tx['id']}", headers=admin)
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["receipt_business_date"] == list_item["receipt_business_date"]
    assert detail["receipt_shift"] == list_item["receipt_shift"]


# ---------------------------------------------------------------------------
# Roadmap PR16 Slice 3: business_date_from/business_date_to/shift/event
# filtering on GET /transactions (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md
# §8/§9/§11, §16 Slice 3 acceptance criteria). `client`/`db_session` share the
# same `db_engine` (tests/conftest.py), so a transaction dispatched/received
# through the API can have its `borrowed_at`/`returned_at` forced to a known
# UTC instant afterward, to test the filter against known shift-boundary
# cases -- the API itself has no way to set these timestamps directly.
# ---------------------------------------------------------------------------

# A representative sample of the same instants test_reporting_time.py's
# _CASES uses: covers both shift transitions and, crucially, an instant
# whose Bangkok business_date differs from its raw UTC calendar date (the
# post-midnight portion of an overnight Night shift, per Owner Decision #1's
# shift_start_date anchor).
_NIGHT_POST_MIDNIGHT_UTC = datetime(2026, 7, 28, 0, 30, 0, tzinfo=timezone.utc)  # Bangkok 07:30, business_date 07-27
_DAY_START_UTC = datetime(2026, 7, 28, 1, 0, 0, tzinfo=timezone.utc)  # Bangkok 08:00:00 exactly, Day start
_NIGHT_START_UTC = datetime(2026, 7, 28, 13, 0, 0, tzinfo=timezone.utc)  # Bangkok 20:00:00 exactly, Night start


async def _force_timestamps(
    db_session, transaction_id: str, *, borrowed_at: datetime | None = None, returned_at: datetime | None = None
):
    values = {}
    if borrowed_at is not None:
        values["borrowed_at"] = borrowed_at
    if returned_at is not None:
        values["returned_at"] = returned_at
    await db_session.execute(
        update(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(transaction_id)).values(**values)
    )
    await db_session.commit()


async def test_business_date_from_and_to_are_both_inclusive(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR16-S3-1")

    equipment = await _create_equipment(client, admin, "AST-PR16-S3-0001")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
    await _force_timestamps(db_session, tx["id"], borrowed_at=_DAY_START_UTC)
    business_date, _ = business_date_and_shift(_DAY_START_UTC)

    # Exactly on both bounds (a single-day range) -- must match.
    resp = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "business_date_from": str(business_date),
            "business_date_to": str(business_date),
        },
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1

    # business_date_from inclusive: the row's own date as the lower bound.
    resp_from = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"equipment_id": equipment["id"], "business_date_from": str(business_date)},
    )
    assert len(resp_from.json()["items"]) == 1

    # business_date_to inclusive: the row's own date as the upper bound.
    resp_to = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"equipment_id": equipment["id"], "business_date_to": str(business_date)},
    )
    assert len(resp_to.json()["items"]) == 1

    # One day before/after the row's business_date -- must exclude it.
    resp_excluded = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "business_date_from": str(business_date + timedelta(days=1)),
        },
    )
    assert resp_excluded.json()["items"] == []


async def test_shift_filter_accepted_values_and_omitted_behavior(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR16-S3-2")

    day_eq = await _create_equipment(client, admin, "AST-PR16-S3-0002")
    night_eq = await _create_equipment(client, admin, "AST-PR16-S3-0003")
    day_tx = await _dispatch(client, staff, day_eq["id"], ward_id, dispatch_type="on_demand")
    night_tx = await _dispatch(client, staff, night_eq["id"], ward_id, dispatch_type="on_demand")
    await _force_timestamps(db_session, day_tx["id"], borrowed_at=_DAY_START_UTC)
    await _force_timestamps(db_session, night_tx["id"], borrowed_at=_NIGHT_START_UTC)

    resp_day = await client.get(
        "/api/v1/transactions", headers=admin, params={"ward_id": ward_id, "shift": "day"}
    )
    assert [i["equipment"]["id"] for i in resp_day.json()["items"]] == [day_eq["id"]]

    resp_night = await client.get(
        "/api/v1/transactions", headers=admin, params={"ward_id": ward_id, "shift": "night"}
    )
    assert [i["equipment"]["id"] for i in resp_night.json()["items"]] == [night_eq["id"]]

    # Omitted shift -- both rows returned, matching pre-Slice-3 behavior for
    # every other optional filter.
    resp_omitted = await client.get("/api/v1/transactions", headers=admin, params={"ward_id": ward_id})
    assert len(resp_omitted.json()["items"]) == 2


async def test_business_date_filter_uses_derived_business_date_not_raw_utc_timestamp(client, seeded_users, db_session):
    """PR16-H1 acceptance criterion: business_date_from/_to must never be
    satisfiable merely by the raw UTC calendar date -- _NIGHT_POST_MIDNIGHT_UTC
    is 2026-07-28 in UTC but business_date 2026-07-27 in Asia/Bangkok (the
    shift_start_date rollover), so the two filter bases must disagree here."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR16-S3-4")

    equipment = await _create_equipment(client, admin, "AST-PR16-S3-0004")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
    await _force_timestamps(db_session, tx["id"], borrowed_at=_NIGHT_POST_MIDNIGHT_UTC)
    business_date, _ = business_date_and_shift(_NIGHT_POST_MIDNIGHT_UTC)
    assert business_date != _NIGHT_POST_MIDNIGHT_UTC.date()  # sanity: the two bases really do disagree here

    # The derived business_date (2026-07-27) matches via business_date_from/_to.
    resp_business_date = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "business_date_from": str(business_date),
            "business_date_to": str(business_date),
        },
    )
    assert len(resp_business_date.json()["items"]) == 1

    # The raw UTC calendar date (2026-07-28) does NOT match business_date
    # filtering -- it is a different day under the Bangkok-derived rule.
    resp_raw_utc_date = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "business_date_from": str(_NIGHT_POST_MIDNIGHT_UTC.date()),
            "business_date_to": str(_NIGHT_POST_MIDNIGHT_UTC.date()),
        },
    )
    assert resp_raw_utc_date.json()["items"] == []

    # The existing, separate from_date/to_date raw-timestamp filter, by
    # contrast, DOES match the raw UTC calendar date -- confirming the two
    # filter bases are genuinely distinct, not accidentally aliased.
    resp_raw_filter = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "from_date": str(_NIGHT_POST_MIDNIGHT_UTC.date()),
            "to_date": str(_NIGHT_POST_MIDNIGHT_UTC.date()),
        },
    )
    assert len(resp_raw_filter.json()["items"]) == 1


async def test_event_dispatch_vs_receipt_selects_the_correct_column_pair(client, seeded_users, db_session):
    """PR16-H2 acceptance criterion: event=dispatch filters
    dispatch_business_date/dispatch_shift (borrowed_at); event=receipt
    filters receipt_business_date/receipt_shift (returned_at) -- the same
    business_date value must not match both bases when the two timestamps
    fall on different derived business dates."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR16-S3-5")

    equipment = await _create_equipment(client, admin, "AST-PR16-S3-0005")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
    await _receive(client, staff, tx["id"])
    await _force_timestamps(db_session, tx["id"], borrowed_at=_DAY_START_UTC, returned_at=_NIGHT_START_UTC)
    dispatch_business_date, _ = business_date_and_shift(_DAY_START_UTC)
    receipt_business_date, _ = business_date_and_shift(_NIGHT_START_UTC)

    resp_dispatch = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "event": "dispatch",
            "business_date_from": str(dispatch_business_date),
            "business_date_to": str(dispatch_business_date),
        },
    )
    assert len(resp_dispatch.json()["items"]) == 1

    resp_receipt = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "event": "receipt",
            "business_date_from": str(receipt_business_date),
            "business_date_to": str(receipt_business_date),
        },
    )
    assert len(resp_receipt.json()["items"]) == 1

    # The dispatch business_date does not satisfy an event=receipt filter
    # when the two derived dates genuinely differ.
    if dispatch_business_date != receipt_business_date:
        resp_mismatched = await client.get(
            "/api/v1/transactions",
            headers=admin,
            params={
                "equipment_id": equipment["id"],
                "event": "receipt",
                "business_date_from": str(dispatch_business_date),
                "business_date_to": str(dispatch_business_date),
            },
        )
        assert resp_mismatched.json()["items"] == []


async def test_open_transaction_excluded_from_receipt_event_filter(client, seeded_users, db_session):
    """§8's confirmed open-transaction rule: a transaction with
    returned_at IS NULL must never satisfy a non-null event=receipt filter
    -- silently excluded, not treated as an error."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR16-S3-6")

    equipment = await _create_equipment(client, admin, "AST-PR16-S3-0006")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
    await _force_timestamps(db_session, tx["id"], borrowed_at=_DAY_START_UTC)

    resp_business_date = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"equipment_id": equipment["id"], "event": "receipt", "business_date_from": "2000-01-01"},
    )
    assert resp_business_date.json()["items"] == []

    resp_shift = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"equipment_id": equipment["id"], "event": "receipt", "shift": "day"},
    )
    assert resp_shift.json()["items"] == []
    resp_shift_night = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"equipment_id": equipment["id"], "event": "receipt", "shift": "night"},
    )
    assert resp_shift_night.json()["items"] == []

    # event=dispatch on the same still-open transaction is unaffected.
    resp_dispatch = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"equipment_id": equipment["id"], "event": "dispatch", "shift": "day"},
    )
    assert len(resp_dispatch.json()["items"]) == 1


async def test_business_date_range_reversed_rejected_with_structured_400_distinct_from_from_date_check(
    client, seeded_users
):
    """A new, separate check from the existing from_date/to_date one (§8) --
    confirmed here by sending a valid from_date/to_date pair alongside a
    reversed business_date_from/business_date_to pair and asserting the
    business_date fields, not from_date/to_date, are named in the error."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "from_date": "2026-01-01",
            "to_date": "2026-01-02",
            "business_date_from": "2026-07-31",
            "business_date_to": "2026-07-01",
        },
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == "INVALID_INPUT"
    assert "business_date_from" in body["detail"]
    assert "business_date_to" in body["detail"]


async def test_equal_business_date_from_and_to_is_a_valid_single_day_range(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR16-S3-7")

    equipment = await _create_equipment(client, admin, "AST-PR16-S3-0007")
    tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
    await _force_timestamps(db_session, tx["id"], borrowed_at=_DAY_START_UTC)
    business_date, _ = business_date_and_shift(_DAY_START_UTC)

    resp = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={
            "equipment_id": equipment["id"],
            "business_date_from": str(business_date),
            "business_date_to": str(business_date),
        },
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1


async def test_invalid_shift_value_rejected_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/transactions", headers=admin, params={"shift": "afternoon"})
    assert resp.status_code == 422


async def test_invalid_event_value_rejected_not_500(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/transactions", headers=admin, params={"event": "cleaning"})
    assert resp.status_code == 422


async def test_business_date_and_shift_filters_leave_pagination_and_ordering_unchanged(
    client, seeded_users, db_session
):
    """Regression guard: adding business_date_from/_to/shift/event must not
    alter the existing (created_at DESC, id DESC) ordering or cursor
    pagination shape -- the new filter is additive, appended to the same
    `filters` list, never touching the ORDER BY/LIMIT clause."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR16-S3-8")

    created_ids = []
    for i in range(3):
        equipment = await _create_equipment(client, admin, f"AST-PR16-S3-010{i}")
        tx = await _dispatch(client, staff, equipment["id"], ward_id, dispatch_type="on_demand")
        await _force_timestamps(db_session, tx["id"], borrowed_at=_DAY_START_UTC)
        created_ids.append(tx["id"])

    resp_unfiltered = await client.get("/api/v1/transactions", headers=admin, params={"ward_id": ward_id})
    resp_filtered = await client.get(
        "/api/v1/transactions",
        headers=admin,
        params={"ward_id": ward_id, "shift": "day", "business_date_from": "2000-01-01"},
    )
    assert resp_unfiltered.status_code == resp_filtered.status_code == 200
    unfiltered_ids = [i["id"] for i in resp_unfiltered.json()["items"]]
    filtered_ids = [i["id"] for i in resp_filtered.json()["items"]]
    # Same set (all 3 rows satisfy the new filter) and, crucially, the exact
    # same order as the unfiltered query -- the (created_at DESC, id DESC)
    # ordering is untouched by the new filter, whatever it resolves to when
    # created_at ties (SQLite/PostgreSQL timestamp precision can make
    # same-millisecond dispatches tie on created_at, in which case id DESC
    # breaks the tie -- this test asserts the ordering is *unchanged* by the
    # new filter, not any particular absolute order).
    assert set(filtered_ids) == set(unfiltered_ids) == set(created_ids)
    assert filtered_ids == unfiltered_ids
    assert resp_unfiltered.json()["total"] == resp_filtered.json()["total"] == 3
