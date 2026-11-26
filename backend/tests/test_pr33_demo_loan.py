"""Roadmap PR33 (Owner Governance 2026-11-26, D14): demo/loan equipment.

Batch registration (dry run + all-or-nothing commit), serial number stored as
BCM Code for demo/loan only, return to owner, dispatch block, export-API
exclusion, dashboard source filter, monitor/report/snapshot source fields."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit import AuditLog
from app.models.equipment import Equipment
from app.models.export import ExportEvent
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.services import daily_report_service
from app.services.identifiers import normalize_serial_as_bcm_code
from app.core.exceptions import InvalidInputError
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio

BATCH = "/api/v1/equipment/demo-loan-batch"


@pytest.fixture
async def ctx(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    ward = await _create_ward(client, admin, "W-33", "Ward 33")
    cat = await client.post("/api/v1/categories", headers=admin, json={"name": "Infusion Pump 33"})
    assert cat.status_code == 201, cat.text
    return {"admin": admin, "staff": staff, "ro": ro, "ward": ward, "cat": cat.json()["id"]}


def _body(ctx, serials, *, source="demo", dry_run=False, **shared_extra):
    items = [s if isinstance(s, dict) else {"serial_number": s} for s in serials]
    return {
        "shared": {
            "category_id": ctx["cat"],
            "brand": "Acme",
            "model": "X1",
            "equipment_source": source,
            "owner_company": "Acme Co.",
            **shared_extra,
        },
        "items": items,
        "dry_run": dry_run,
    }


async def _register(client, ctx, serials, **kw):
    resp = await client.post(BATCH, headers=ctx["admin"], json=_body(ctx, serials, **kw))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _pool_equipment(client, ctx, n):
    r = await client.post(
        "/api/v1/equipment",
        headers=ctx["admin"],
        json={"asset_number": f"AST-33-{n}", "equipment_name": "Pool Pump", "bcm_code": f"BCM33{n}"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _dispatch(client, ctx, equipment_id):
    return await client.post(
        "/api/v1/borrow",
        headers=ctx["staff"],
        json={"equipment_id": equipment_id, "ward_id": ctx["ward"], "dispatch_type": "on_demand"},
    )


# --- identifier normalization ----------------------------------------------


async def test_serial_normalization_rules():
    assert normalize_serial_as_bcm_code("  sn-001/a_b.c ") == "SN-001/A_B.C"
    for bad in ("", "   ", "SN 001", "SN#1", "SNก", "X" * 65):
        with pytest.raises(InvalidInputError):
            normalize_serial_as_bcm_code(bad)
    assert len(normalize_serial_as_bcm_code("X" * 64)) == 64


# --- batch: auth, dry run, commit ------------------------------------------


async def test_batch_is_admin_only(client, ctx):
    body = _body(ctx, ["SN-A"])
    assert (await client.post(BATCH, json=body)).status_code == 401
    for role in ("staff", "ro"):
        assert (await client.post(BATCH, headers=ctx[role], json=body)).status_code == 403


async def test_dry_run_reports_per_row_errors_and_writes_nothing(client, ctx, db_session):
    pool = await _pool_equipment(client, ctx, 1)
    existing = await _register(client, ctx, ["EXIST-1"])
    assert existing["committed"] is True
    out = await _register(
        client,
        ctx,
        ["new-1", "NEW-1", " ", "bad serial", "EXIST-1", pool["bcm_code"], "ok-2"],
        dry_run=True,
    )
    assert out["dry_run"] is True and out["valid"] is False and out["committed"] is False
    rows = {r["index"]: r for r in out["rows"]}
    assert rows[0]["errors"] == [] and rows[0]["serial_number"] == "NEW-1"
    assert rows[1]["errors"] == ["duplicate_in_batch"]
    assert rows[2]["errors"] == ["blank"]
    assert rows[3]["errors"] == ["invalid_serial"]
    assert rows[4]["errors"] == ["duplicate_in_db"]
    # A serial can never collide with a pool BCM Code either.
    assert rows[5]["errors"] == ["duplicate_in_db"]
    assert rows[6]["errors"] == []
    db_session.expire_all()
    assert (await db_session.execute(select(func.count()).select_from(Equipment))).scalar_one() == 2  # pool + EXIST-1


async def test_dry_run_valid_batch_writes_nothing(client, ctx, db_session):
    out = await _register(client, ctx, ["A-1", "A-2"], dry_run=True)
    assert out["valid"] is True and out["committed"] is False and out["created_count"] == 0
    assert (await db_session.execute(select(func.count()).select_from(Equipment))).scalar_one() == 0


async def test_commit_creates_rows_with_metadata_and_audit(client, ctx, db_session):
    due = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    out = await _register(
        client,
        ctx,
        [{"serial_number": " sn-100 ", "has_charger": False, "has_clamp": True}, {"serial_number": "SN-101"}],
        source="loan",
        due_back_date=due,
    )
    assert out["valid"] and out["committed"] and out["created_count"] == 2
    first, second = out["created"]
    assert first["bcm_code"] == "SN-100" and first["equipment_source"] == "loan"
    assert first["owner_company"] == "Acme Co." and first["due_back_date"] == due
    assert first["has_charger"] is False and first["has_clamp"] is True
    assert second["has_charger"] is True and second["has_clamp"] is True  # defaults
    assert first["equipment_name"] == "Acme X1" and first["status"] == "available_at_pool"
    assert first["returned_to_owner_at"] is None
    db_session.expire_all()
    audits = (
        await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "equipment", AuditLog.action == "create"))
    ).scalars().all()
    assert len(audits) == 2

    got = await client.get(f"/api/v1/equipment/{first['id']}", headers=ctx["staff"])
    assert got.json()["equipment_source"] == "loan"


async def test_commit_with_any_row_error_is_all_or_nothing(client, ctx, db_session):
    out = await _register(client, ctx, ["GOOD-1", "GOOD-1"])
    assert out["valid"] is False and out["committed"] is False and out["created_count"] == 0
    assert (await db_session.execute(select(func.count()).select_from(Equipment))).scalar_one() == 0


async def test_duplicate_in_db_blocks_recommit(client, ctx):
    assert (await _register(client, ctx, ["DUP-1"]))["committed"] is True
    again = await _register(client, ctx, ["dup-1", "FRESH-1"])
    assert again["committed"] is False
    assert again["rows"][0]["errors"] == ["duplicate_in_db"]
    assert again["rows"][1]["errors"] == []


async def test_batch_request_validation(client, ctx):
    bad_source = _body(ctx, ["A"], source="pool")
    assert (await client.post(BATCH, headers=ctx["admin"], json=bad_source)).status_code == 422
    no_owner = _body(ctx, ["A"], owner_company="  ")
    assert (await client.post(BATCH, headers=ctx["admin"], json=no_owner)).status_code == 422
    empty = _body(ctx, [])
    assert (await client.post(BATCH, headers=ctx["admin"], json=empty)).status_code == 422
    missing_cat = _body(ctx, ["A"])
    missing_cat["shared"]["category_id"] = "00000000-0000-0000-0000-000000000001"
    assert (await client.post(BATCH, headers=ctx["admin"], json=missing_cat)).status_code == 400


async def test_pool_bcm_rules_unchanged(client, ctx):
    # A pool device still gets the canonical BCM form; a demo serial is only uppercased.
    pool = await client.post(
        "/api/v1/equipment", headers=ctx["admin"], json={"asset_number": "AST-33-P", "equipment_name": "P", "bcm_code": "bcm0042"}
    )
    assert pool.json()["bcm_code"] == "BCM0042"
    assert pool.json()["equipment_source"] == "pool"
    demo = (await _register(client, ctx, ["abc123"]))["created"][0]
    assert demo["bcm_code"] == "ABC123"
    # Updating a demo device's serial uses the serial rules, not the BCM prefix rule.
    upd = await client.patch(f"/api/v1/equipment/{demo['id']}", headers=ctx["admin"], json={"bcm_code": "xyz-9"})
    assert upd.status_code == 200 and upd.json()["bcm_code"] == "XYZ-9"
    bad = await client.patch(f"/api/v1/equipment/{demo['id']}", headers=ctx["admin"], json={"bcm_code": "has space"})
    assert bad.status_code == 400
    clash = await client.patch(f"/api/v1/equipment/{demo['id']}", headers=ctx["admin"], json={"bcm_code": "BCM0042"})
    assert clash.status_code == 409


# --- listing / search / dashboard ------------------------------------------


async def test_list_filter_by_source_and_bcm_search(client, ctx):
    await _pool_equipment(client, ctx, 2)
    await _register(client, ctx, ["SN-D1"], source="demo")
    await _register(client, ctx, ["SN-L1"], source="loan")
    for source, expected in (("pool", 1), ("demo", 1), ("loan", 1)):
        resp = await client.get("/api/v1/equipment", headers=ctx["staff"], params={"source": source})
        assert resp.json()["total"] == expected, source
        assert all(i["equipment_source"] == source for i in resp.json()["items"])
    assert (await client.get("/api/v1/equipment", headers=ctx["staff"])).json()["total"] == 3
    assert (await client.get("/api/v1/equipment", headers=ctx["staff"], params={"source": "bogus"})).status_code == 422
    found = await client.get("/api/v1/equipment/search/bcm", headers=ctx["staff"], params={"q": "SN-D"})
    assert [r["bcm_code"] for r in found.json()] == ["SN-D1"]


async def test_dashboard_source_filter(client, ctx):
    await _pool_equipment(client, ctx, 3)
    await _register(client, ctx, ["D-1", "D-2"], source="demo")
    await _register(client, ctx, ["L-1"], source="loan")

    async def total(source=None):
        params = {"source": source} if source else {}
        resp = await client.get("/api/v1/dashboard/summary", headers=ctx["staff"], params=params)
        assert resp.status_code == 200, resp.text
        assert set(resp.json()) == {
            "total", "available_at_pool", "issued_to_ward", "unavailable_defective", "decommissioned"
        }
        return resp.json()["total"]

    assert await total() == 4
    assert await total("all") == 4
    assert await total("pool") == 1
    assert await total("demo") == 2
    assert await total("loan") == 1
    bad = await client.get("/api/v1/dashboard/summary", headers=ctx["staff"], params={"source": "x"})
    assert bad.status_code == 422


# --- return to owner -------------------------------------------------------


async def test_return_to_owner_rules_audit_and_exclusions(client, ctx, db_session):
    created = (await _register(client, ctx, ["R-1", "R-2"]))["created"]
    eq = created[0]["id"]
    url = f"/api/v1/equipment/{eq}/return-to-owner"
    assert (await client.post(url, headers=ctx["staff"])).status_code == 403
    assert (await client.post(url)).status_code == 401

    resp = await client.post(url, headers=ctx["admin"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["returned_to_owner_at"] is not None and body["status"] == "available_at_pool"
    assert (await client.post(url, headers=ctx["admin"])).status_code == 409  # already returned

    db_session.expire_all()
    row = (await db_session.execute(select(Equipment).where(Equipment.bcm_code == "R-1"))).scalar_one()
    assert row.returned_to_owner_by_user_id is not None and row.version == 2
    audits = (await db_session.execute(select(AuditLog).where(AuditLog.action == "return_to_owner"))).scalars().all()
    assert len(audits) == 1 and audits[0].entity_id == row.id

    # Leaves lists, pickers and dashboard counts by default; history/detail kept.
    listed = await client.get("/api/v1/equipment", headers=ctx["staff"])
    assert [i["bcm_code"] for i in listed.json()["items"]] == ["R-2"]
    with_returned = await client.get("/api/v1/equipment", headers=ctx["admin"], params={"include_returned": "true"})
    assert with_returned.json()["total"] == 2
    assert (await client.get("/api/v1/equipment/search/bcm", headers=ctx["staff"], params={"q": "R-"})).json() == [
        {"id": created[1]["id"], "bcm_code": "R-2"}
    ]
    summary = await client.get("/api/v1/dashboard/summary", headers=ctx["staff"])
    assert summary.json()["total"] == 1 and summary.json()["available_at_pool"] == 1
    assert (await client.get(f"/api/v1/equipment/{eq}", headers=ctx["staff"])).status_code == 200


async def test_return_to_owner_blocks_dispatch_with_distinct_code(client, ctx, db_session):
    eq = (await _register(client, ctx, ["B-1"]))["created"][0]["id"]
    assert (await client.post(f"/api/v1/equipment/{eq}/return-to-owner", headers=ctx["admin"])).status_code == 200

    check = await client.get(f"/api/v1/equipment/{eq}/dispatch-check", headers=ctx["staff"])
    assert check.status_code == 200
    assert check.json()["dispatchable"] is False and check.json()["warning"] == "returned_to_owner"
    assert check.json()["returned_to_owner_at"] is not None

    resp = await _dispatch(client, ctx, eq)
    assert resp.status_code == 409 and resp.json()["code"] == "EQUIPMENT_RETURNED_TO_OWNER"
    # Even with an acknowledgement it is never dispatchable.
    ack = await client.post(
        "/api/v1/borrow",
        headers=ctx["staff"],
        json={"equipment_id": eq, "ward_id": ctx["ward"], "dispatch_type": "on_demand", "acknowledge_status_warning": True},
    )
    assert ack.status_code == 409 and ack.json()["code"] == "EQUIPMENT_RETURNED_TO_OWNER"


async def test_return_to_owner_requires_available_demo_loan(client, ctx):
    pool = await _pool_equipment(client, ctx, 4)
    r = await client.post(f"/api/v1/equipment/{pool['id']}/return-to-owner", headers=ctx["admin"])
    assert r.status_code == 400  # pool devices are never "returned to owner"

    out = (await _register(client, ctx, ["OUT-1", "DEF-1"]))["created"]
    assert (await _dispatch(client, ctx, out[0]["id"])).status_code == 201
    issued = await client.post(f"/api/v1/equipment/{out[0]['id']}/return-to-owner", headers=ctx["admin"])
    assert issued.status_code == 409  # issued to ward

    mark = await client.post(
        f"/api/v1/equipment/{out[1]['id']}/status", headers=ctx["admin"], json={"status": "unavailable_defective"}
    )
    assert mark.status_code == 200
    defective = await client.post(f"/api/v1/equipment/{out[1]['id']}/return-to-owner", headers=ctx["admin"])
    assert defective.status_code == 409

    missing = await client.post(
        "/api/v1/equipment/00000000-0000-0000-0000-000000000009/return-to-owner", headers=ctx["admin"]
    )
    assert missing.status_code == 404


# --- normal flow, export exclusion, monitor, reports, snapshot --------------


async def test_demo_device_uses_normal_dispatch_receipt_and_is_excluded_from_export_api(client, ctx, db_session):
    key = (await client.post("/api/v1/export-keys", headers=ctx["admin"], json={"name": "Nsmart"})).json()
    headers = {"X-API-Key": key["key"]}
    pool = await _pool_equipment(client, ctx, 5)
    demo = (await _register(client, ctx, ["EXP-1"]))["created"][0]

    tx_pool = (await _dispatch(client, ctx, pool["id"])).json()
    tx_demo_resp = await _dispatch(client, ctx, demo["id"])
    assert tx_demo_resp.status_code == 201, tx_demo_resp.text
    tx_demo = tx_demo_resp.json()
    assert tx_demo["equipment"]["equipment_source"] == "demo" and tx_demo["equipment"]["bcm_code"] == "EXP-1"
    for tx in (tx_pool, tx_demo):
        r = await client.post(f"/api/v1/return/{tx['id']}", headers=ctx["staff"], json={"receipt_outcome": "usable"})
        assert r.status_code == 200, r.text

    events = (await client.get("/api/v1/export/events", headers=headers)).json()["events"]
    assert len(events) == 2  # pool dispatch + pool receipt only
    assert {e["transaction_id"] if "transaction_id" in e else None for e in events} <= {None, tx_pool["id"]}
    db_session.expire_all()
    assert (await db_session.execute(select(func.count()).select_from(ExportEvent))).scalar_one() == 2
    # Seqs stay gap-free: demo events never consume a number.
    assert [e["seq"] for e in events] == [1, 2]


async def test_query_events_excludes_demo_events_even_if_present(client, ctx, db_session):
    """Defense in depth: even a pre-existing export event row for a demo
    device (e.g. recorded before this PR changed the device's source) is never
    returned."""
    from app.models.export import EVENT_TYPE_DISPATCH
    from app.services import export_service

    demo = (await _register(client, ctx, ["EXP-2"]))["created"][0]
    tx = (await _dispatch(client, ctx, demo["id"])).json()
    import uuid as _uuid

    db_session.add(
        ExportEvent(
            seq=await export_service._next_seq(db_session),
            event_id=_uuid.uuid4(),
            event_type=EVENT_TYPE_DISPATCH,
            transaction_id=_uuid.UUID(tx["id"]),
            event_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    events, _ = await export_service.query_events(db_session, after=0, limit=50)
    assert events == []


async def test_monitor_events_carry_source_badge_fields(client, ctx):
    pool = await _pool_equipment(client, ctx, 6)
    demo = (await _register(client, ctx, ["MON-1"], source="loan"))["created"][0]
    await _dispatch(client, ctx, pool["id"])
    await _dispatch(client, ctx, demo["id"])
    items = (await client.get("/api/v1/monitor/events", headers=ctx["staff"])).json()["items"]
    by_code = {i["equipment"]["bcm_code"]: i["equipment"] for i in items}
    assert by_code["MON-1"]["equipment_source"] == "loan"
    assert by_code["BCM336"]["equipment_source"] == "pool"


async def test_issue_report_rows_and_export_label_demo_devices(client, ctx):
    demo = (await _register(client, ctx, ["REP-1"]))["created"][0]
    await _dispatch(client, ctx, demo["id"])
    rows = (await client.get("/api/v1/reports/issue", headers=ctx["admin"])).json()["items"]
    assert rows[0]["equipment"]["equipment_source"] == "demo"
    assert rows[0]["equipment"]["bcm_code"] == "REP-1"

    from app.services.equipment_badge import badge_text, with_badge

    assert badge_text("demo") == "DEMO" and badge_text("loan") == "ยืม" and badge_text("pool") is None
    assert with_badge("Pump", "loan") == "[ยืม] Pump" and with_badge("Pump", "pool") == "Pump"


async def test_verify_checklist_excludes_returned_and_shows_source(client, ctx):
    created = (await _register(client, ctx, ["V-1", "V-2"]))["created"]
    await client.post(f"/api/v1/equipment/{created[0]['id']}/return-to-owner", headers=ctx["admin"])
    resp = await client.get("/api/v1/reports/equipment-verify-checklist", headers=ctx["admin"])
    assert [i["bcm_code"] for i in resp.json()["items"]] == ["V-2"]
    assert resp.json()["items"][0]["equipment_source"] == "demo"


async def test_daily_report_events_carry_source(client, ctx, db_session):
    demo = (await _register(client, ctx, ["DAY-1"]))["created"][0]
    await _dispatch(client, ctx, demo["id"])
    now = datetime.now(timezone.utc)
    events = await daily_report_service._load_events(db_session, now - timedelta(hours=1), now + timedelta(hours=1))
    assert [(e.bcm_code, e.source) for e in events] == [("DAY-1", "demo")]


async def test_offline_snapshot_equipment_rows_have_source_and_returned_flag(client, ctx):
    created = (await _register(client, ctx, ["SNAP-1"]))["created"][0]
    await client.post(f"/api/v1/equipment/{created['id']}/return-to-owner", headers=ctx["admin"])
    resp = await client.get("/api/v1/sync/snapshot", headers=ctx["staff"], params={"section": "equipment"})
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["equipment_source"] == "demo" and item["returned_to_owner"] is True
    assert "item_no" not in item and "serial_number" not in item
