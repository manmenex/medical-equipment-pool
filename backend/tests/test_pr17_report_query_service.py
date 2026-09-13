import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.core.reporting_time import business_date_and_shift
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF
from app.services import report_query_service
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Roadmap PR17 Slice 1 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §7.1/
# §7.2/§8/§11/§17): report-domain and query-semantics tests for
# app.services.report_query_service.search_receive_report/search_issue_report
# and the additive transaction_crud.search() capabilities they use
# (equipment_category_id join, operator_id filter, require_receipt
# predicate). No HTTP report endpoint exists yet (that is Slice 2) -- these
# tests call the report query functions directly against `db_session`, the
# same pattern test_transaction_search.py already uses for forcing known
# timestamps.
# ---------------------------------------------------------------------------

_DAY_START_UTC = datetime(2026, 7, 28, 1, 0, 0, tzinfo=timezone.utc)  # Bangkok 08:00:00, Day start
_NIGHT_START_UTC = datetime(2026, 7, 28, 13, 0, 0, tzinfo=timezone.utc)  # Bangkok 20:00:00, Night start
_NIGHT_POST_MIDNIGHT_UTC = datetime(2026, 7, 28, 0, 30, 0, tzinfo=timezone.utc)  # Bangkok 07:30, business_date 07-27


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


async def _force_created_at(db_session, transaction_id: str, created_at: datetime):
    """`created_at` is DB-generated (`server_default=func.now()`), so
    ordering/pagination tests that need deterministic, strictly-distinct
    values (rather than relying on real wall-clock gaps between rapid
    successive test requests, which SQLite's second-resolution
    CURRENT_TIMESTAMP can tie) force it explicitly, exactly like
    `_force_timestamps` above already does for `borrowed_at`/`returned_at`."""
    await db_session.execute(
        update(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(transaction_id)).values(
            created_at=created_at
        )
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Receive Report -- canonical eligibility (§7.1), including the five
# PR17-H1 scenarios: unconditional exclusion of OPEN transactions, in
# combination with every other filter (or none at all).
# ---------------------------------------------------------------------------


async def test_receive_report_excludes_open_transaction_with_no_filters(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-1")

    open_eq = await _create_equipment(client, admin, "AST-PR17S1-0001")
    await _dispatch(client, staff, open_eq["id"], ward_id)

    rows, _, total = await report_query_service.search_receive_report(db_session, ward_id=uuid.UUID(ward_id))
    assert rows == []
    assert total == 0


async def test_receive_report_includes_closed_transaction_with_no_filters(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-2")

    closed_eq = await _create_equipment(client, admin, "AST-PR17S1-0002")
    tx = await _dispatch(client, staff, closed_eq["id"], ward_id)
    await _receive(client, staff, tx["id"])

    rows, _, total = await report_query_service.search_receive_report(db_session, ward_id=uuid.UUID(ward_id))
    assert total == 1
    assert [str(r.id) for r in rows] == [tx["id"]]
    assert rows[0].returned_at is not None


async def test_receive_report_includes_defective_receipt(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-3")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0003")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, staff, tx["id"], receipt_outcome="defective")

    rows, _, total = await report_query_service.search_receive_report(db_session, ward_id=uuid.UUID(ward_id))
    assert total == 1
    assert rows[0].receipt_outcome.value == "defective"


async def test_receive_report_excludes_open_transaction_with_ward_filter(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-4")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0004")
    await _dispatch(client, staff, eq["id"], ward_id)

    rows, _, total = await report_query_service.search_receive_report(db_session, ward_id=uuid.UUID(ward_id))
    assert rows == []
    assert total == 0


async def test_receive_report_excludes_open_transaction_with_category_filter(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-5")
    category_id = await _create_category(client, admin, "Infusion Pumps PR17S1-5")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0005", category_id=category_id)
    await _dispatch(client, staff, eq["id"], ward_id)

    rows, _, total = await report_query_service.search_receive_report(
        db_session, equipment_category_id=uuid.UUID(category_id)
    )
    assert rows == []
    assert total == 0


async def test_receive_report_excludes_open_transaction_with_operator_filter(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-6")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0006")
    await _dispatch(client, staff, eq["id"], ward_id)
    staff_user_id = seeded_users[ROLE_EQUIPMENT_POOL_STAFF].id

    # operator_id resolves against received_by_user_id for the Receive
    # Report (event="receipt", §9/§11) -- the OPEN transaction has no
    # received_by_user_id at all yet, so it must not match regardless.
    rows, _, total = await report_query_service.search_receive_report(db_session, operator_id=staff_user_id)
    assert rows == []
    assert total == 0


async def test_receive_report_excludes_open_transaction_with_date_filter(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-7")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0007")
    await _dispatch(client, staff, eq["id"], ward_id)

    rows, _, total = await report_query_service.search_receive_report(
        db_session, ward_id=uuid.UUID(ward_id), business_date_from=date(2000, 1, 1)
    )
    assert rows == []
    assert total == 0


async def test_receive_report_excludes_open_transaction_with_shift_filter(client, seeded_users, db_session):
    from app.core.reporting_time import Shift

    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-8")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0008")
    await _dispatch(client, staff, eq["id"], ward_id)

    rows, _, total = await report_query_service.search_receive_report(
        db_session, ward_id=uuid.UUID(ward_id), shift=Shift.DAY
    )
    assert rows == []
    assert total == 0


async def test_receive_report_count_query_and_result_query_apply_identical_eligibility(
    client, seeded_users, db_session
):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-9")

    closed_ids = []
    for i in range(3):
        eq = await _create_equipment(client, admin, f"AST-PR17S1-009{i}")
        tx = await _dispatch(client, staff, eq["id"], ward_id)
        await _receive(client, staff, tx["id"])
        await _force_created_at(db_session, tx["id"], _DAY_START_UTC + timedelta(seconds=i))
        closed_ids.append(tx["id"])
    open_eq = await _create_equipment(client, admin, "AST-PR17S1-0099")
    await _dispatch(client, staff, open_eq["id"], ward_id)

    rows, next_cursor, total = await report_query_service.search_receive_report(
        db_session, ward_id=uuid.UUID(ward_id), limit=2
    )
    # total reflects the full eligible set (3 CLOSED), not the page size,
    # and never counts the still-OPEN fourth transaction.
    assert total == 3
    assert len(rows) == 2
    assert next_cursor is not None

    rows_page_2, next_cursor_2, total_2 = await report_query_service.search_receive_report(
        db_session, ward_id=uuid.UUID(ward_id), limit=2, cursor=next_cursor
    )
    assert total_2 == 3
    assert len(rows_page_2) == 1
    assert next_cursor_2 is None
    assert {str(r.id) for r in rows} | {str(r.id) for r in rows_page_2} == set(closed_ids)


async def test_receive_report_boundary_timestamps_follow_business_date_and_shift_rules(
    client, seeded_users, db_session
):
    """§7.1's receipt eligibility is combined with business_date/shift
    derived from `returned_at` (the receipt event, §5) -- not `borrowed_at`.
    """
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-10")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0010")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, staff, tx["id"])
    await _force_timestamps(db_session, tx["id"], borrowed_at=_DAY_START_UTC, returned_at=_NIGHT_START_UTC)
    receipt_business_date, receipt_shift = business_date_and_shift(_NIGHT_START_UTC)

    rows, _, total = await report_query_service.search_receive_report(
        db_session,
        ward_id=uuid.UUID(ward_id),
        business_date_from=receipt_business_date,
        business_date_to=receipt_business_date,
        shift=receipt_shift,
    )
    assert total == 1
    assert [str(r.id) for r in rows] == [tx["id"]]

    # The dispatch-side business_date (a different derived day, per the
    # forced timestamps above) must not satisfy the Receive Report's
    # receipt-side filter.
    dispatch_business_date, _ = business_date_and_shift(_DAY_START_UTC)
    if dispatch_business_date != receipt_business_date:
        rows_mismatched, _, total_mismatched = await report_query_service.search_receive_report(
            db_session,
            ward_id=uuid.UUID(ward_id),
            business_date_from=dispatch_business_date,
            business_date_to=dispatch_business_date,
        )
        assert rows_mismatched == []
        assert total_mismatched == 0


# ---------------------------------------------------------------------------
# Issue Report -- canonical eligibility (§7.2): dispatch-side basis, both
# OPEN and CLOSED transactions eligible.
# ---------------------------------------------------------------------------


async def test_issue_report_includes_open_transaction(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-11")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0011")
    tx = await _dispatch(client, staff, eq["id"], ward_id)

    rows, _, total = await report_query_service.search_issue_report(db_session, ward_id=uuid.UUID(ward_id))
    assert total == 1
    assert [str(r.id) for r in rows] == [tx["id"]]
    assert rows[0].returned_at is None


async def test_issue_report_includes_issued_but_not_returned_transaction_alongside_closed(
    client, seeded_users, db_session
):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-12")

    open_eq = await _create_equipment(client, admin, "AST-PR17S1-0012")
    open_tx = await _dispatch(client, staff, open_eq["id"], ward_id)
    closed_eq = await _create_equipment(client, admin, "AST-PR17S1-0013")
    closed_tx = await _dispatch(client, staff, closed_eq["id"], ward_id)
    await _receive(client, staff, closed_tx["id"])

    rows, _, total = await report_query_service.search_issue_report(db_session, ward_id=uuid.UUID(ward_id))
    assert total == 2
    assert {str(r.id) for r in rows} == {open_tx["id"], closed_tx["id"]}


async def test_issue_report_date_filter_uses_dispatch_side_semantics(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-14")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0014")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, staff, tx["id"])
    await _force_timestamps(db_session, tx["id"], borrowed_at=_DAY_START_UTC, returned_at=_NIGHT_START_UTC)
    dispatch_business_date, _ = business_date_and_shift(_DAY_START_UTC)
    receipt_business_date, _ = business_date_and_shift(_NIGHT_START_UTC)

    rows, _, total = await report_query_service.search_issue_report(
        db_session,
        ward_id=uuid.UUID(ward_id),
        business_date_from=dispatch_business_date,
        business_date_to=dispatch_business_date,
    )
    assert total == 1
    assert [str(r.id) for r in rows] == [tx["id"]]

    if dispatch_business_date != receipt_business_date:
        rows_mismatched, _, total_mismatched = await report_query_service.search_issue_report(
            db_session,
            ward_id=uuid.UUID(ward_id),
            business_date_from=receipt_business_date,
            business_date_to=receipt_business_date,
        )
        assert rows_mismatched == []
        assert total_mismatched == 0


async def test_issue_report_shift_filter_uses_dispatch_side_semantics(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-15")

    day_eq = await _create_equipment(client, admin, "AST-PR17S1-0015")
    night_eq = await _create_equipment(client, admin, "AST-PR17S1-0016")
    day_tx = await _dispatch(client, staff, day_eq["id"], ward_id)
    night_tx = await _dispatch(client, staff, night_eq["id"], ward_id)
    await _force_timestamps(db_session, day_tx["id"], borrowed_at=_DAY_START_UTC)
    await _force_timestamps(db_session, night_tx["id"], borrowed_at=_NIGHT_START_UTC)

    from app.core.reporting_time import Shift

    rows_day, _, total_day = await report_query_service.search_issue_report(
        db_session, ward_id=uuid.UUID(ward_id), shift=Shift.DAY
    )
    assert [str(r.id) for r in rows_day] == [day_tx["id"]]
    assert total_day == 1

    rows_night, _, total_night = await report_query_service.search_issue_report(
        db_session, ward_id=uuid.UUID(ward_id), shift=Shift.NIGHT
    )
    assert [str(r.id) for r in rows_night] == [night_tx["id"]]
    assert total_night == 1


async def test_issue_report_receipt_side_timestamp_does_not_replace_dispatch_side_semantics(
    client, seeded_users, db_session
):
    """Forcing returned_at to fall on a business_date/shift that never
    matches borrowed_at's own derived value must not leak into the Issue
    Report's dispatch-side filter -- receipt timing is irrelevant to §7.2."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-17")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0017")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, staff, tx["id"])
    await _force_timestamps(
        db_session, tx["id"], borrowed_at=_DAY_START_UTC, returned_at=_NIGHT_POST_MIDNIGHT_UTC
    )
    dispatch_business_date, dispatch_shift = business_date_and_shift(_DAY_START_UTC)
    receipt_business_date, _ = business_date_and_shift(_NIGHT_POST_MIDNIGHT_UTC)
    assert dispatch_business_date != receipt_business_date  # sanity: genuinely different derived days

    rows, _, total = await report_query_service.search_issue_report(
        db_session,
        ward_id=uuid.UUID(ward_id),
        business_date_from=dispatch_business_date,
        business_date_to=dispatch_business_date,
        shift=dispatch_shift,
    )
    assert total == 1
    assert [str(r.id) for r in rows] == [tx["id"]]


async def test_issue_report_operator_id_resolves_against_borrower_user_id(client, seeded_users, db_session):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin_headers, "W-PR17S1-18")

    staff_eq = await _create_equipment(client, admin_headers, "AST-PR17S1-0018")
    staff_tx = await _dispatch(client, staff_headers, staff_eq["id"], ward_id)
    admin_eq = await _create_equipment(client, admin_headers, "AST-PR17S1-0019")
    admin_tx = await _dispatch(client, admin_headers, admin_eq["id"], ward_id)

    staff_user_id = seeded_users[ROLE_EQUIPMENT_POOL_STAFF].id
    rows, _, total = await report_query_service.search_issue_report(
        db_session, ward_id=uuid.UUID(ward_id), operator_id=staff_user_id
    )
    assert total == 1
    assert [str(r.id) for r in rows] == [staff_tx["id"]]
    assert admin_tx["id"] not in [str(r.id) for r in rows]


# ---------------------------------------------------------------------------
# Pagination / ordering -- deterministic (created_at DESC, id DESC), no
# duplicate or missing rows across cursor pages (§7.2/§10.1/§17 Slice 1).
# ---------------------------------------------------------------------------


async def test_issue_report_ordering_is_created_at_desc_id_desc(client, seeded_users, db_session):
    """`created_at` is DB-generated at insert time (`server_default=
    func.now()`); rapid successive test requests can otherwise tie at
    SQLite's second-level resolution, so each row's `created_at` is forced
    to a distinct, strictly increasing instant here to exercise the real
    ordering contract deterministically, independent of wall-clock timing."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-20")

    created_ids = []
    for i in range(4):
        eq = await _create_equipment(client, admin, f"AST-PR17S1-020{i}")
        tx = await _dispatch(client, staff, eq["id"], ward_id)
        await _force_created_at(db_session, tx["id"], _DAY_START_UTC + timedelta(seconds=i))
        created_ids.append(tx["id"])

    rows, _, total = await report_query_service.search_issue_report(db_session, ward_id=uuid.UUID(ward_id))
    assert total == 4
    # created_at DESC, id DESC -- most-recently-dispatched first, the exact
    # reverse of creation order (matching GET /transactions's existing
    # contract, unchanged by this design, §7.2/§10.1).
    assert [str(r.id) for r in rows] == list(reversed(created_ids))


async def test_issue_report_cursor_pagination_no_duplicates_no_missing_rows(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-21")

    created_ids = []
    for i in range(5):
        eq = await _create_equipment(client, admin, f"AST-PR17S1-021{i}")
        tx = await _dispatch(client, staff, eq["id"], ward_id)
        await _force_created_at(db_session, tx["id"], _DAY_START_UTC + timedelta(seconds=i))
        created_ids.append(tx["id"])

    seen: list[str] = []
    cursor = None
    for _ in range(10):  # generous upper bound on page count; loop breaks on next_cursor is None
        rows, next_cursor, total = await report_query_service.search_issue_report(
            db_session, ward_id=uuid.UUID(ward_id), limit=2, cursor=cursor
        )
        assert total == 5
        seen.extend(str(r.id) for r in rows)
        if next_cursor is None:
            break
        cursor = next_cursor

    assert len(seen) == len(set(seen)) == 5  # no duplicates
    assert set(seen) == set(created_ids)  # no missing rows
    assert seen == list(reversed(created_ids))  # deterministic order preserved across pages


async def test_issue_report_filter_and_cursor_predicates_compose_correctly(client, seeded_users, db_session):
    """A filter (ward_id) combined with cursor pagination must apply both
    predicates together, not just one -- a transaction from a different
    ward must never leak into a filtered, paginated result."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_a = await _create_ward(client, admin, "W-PR17S1-22A")
    ward_b = await _create_ward(client, admin, "W-PR17S1-22B")

    ward_a_ids = []
    for i in range(3):
        eq = await _create_equipment(client, admin, f"AST-PR17S1-022A{i}")
        tx = await _dispatch(client, staff, eq["id"], ward_a)
        await _force_created_at(db_session, tx["id"], _DAY_START_UTC + timedelta(seconds=i))
        ward_a_ids.append(tx["id"])
    other_eq = await _create_equipment(client, admin, "AST-PR17S1-022B")
    await _dispatch(client, staff, other_eq["id"], ward_b)

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        rows, next_cursor, total = await report_query_service.search_issue_report(
            db_session, ward_id=uuid.UUID(ward_a), limit=2, cursor=cursor
        )
        assert total == 3
        seen.extend(str(r.id) for r in rows)
        if next_cursor is None:
            break
        cursor = next_cursor

    assert set(seen) == set(ward_a_ids)
    assert len(seen) == 3


# ---------------------------------------------------------------------------
# Existing-contract regression protection (§20/§21): GET /transactions must
# remain byte-for-byte unaffected -- it never sets equipment_category_id/
# operator_id/require_receipt, so an OPEN transaction must still appear in
# an unfiltered listing exactly as before this Slice.
# ---------------------------------------------------------------------------


async def test_get_transactions_endpoint_still_returns_open_transactions_unaffected(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR17S1-23")

    eq = await _create_equipment(client, admin, "AST-PR17S1-0023")
    tx = await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get("/api/v1/transactions", headers=admin, params={"equipment_id": eq["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == tx["id"]
