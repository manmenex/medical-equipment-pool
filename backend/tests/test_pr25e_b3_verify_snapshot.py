"""Roadmap PR25E slice B3: verify, snapshot, status, stats."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.equipment import Equipment
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.services import sync_snapshot_service as snap
from tests.conftest import auth_headers as _auth_headers
from tests.test_pr25e_b2_sync_ops import _equipment, _send, _user, _ward, dispatch_op, receipt_op

pytestmark = pytest.mark.asyncio
V, S, ST, SN = "/api/v1/sync/verify", "/api/v1/sync/snapshot", "/api/v1/sync/status", "/api/v1/sync/stats"


@pytest.fixture
async def ctx(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    return {
        "admin": admin, "staff": staff, "ro": ro,
        "staff_id": await _user(client, staff), "admin_id": await _user(client, admin),
        "ward": await _ward(client, admin), "eq": await _equipment(client, admin),
    }


# ---- verify ----
async def test_verify_known_unknown_and_other_user(client, ctx):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    await _send(client, ctx["staff"], op)
    ghost = str(uuid.uuid4())
    r = await client.post(V, headers=ctx["staff"], json={"op_ids": [op["op_id"], ghost, ghost]})
    assert r.status_code == 200
    assert r.json() == {"checked": 2, "unknown_op_ids": [ghost]}
    # another user cannot learn the op exists: it looks unknown to them
    r = await client.post(V, headers=ctx["admin"], json={"op_ids": [op["op_id"]]})
    assert r.json()["unknown_op_ids"] == [op["op_id"]]
    assert set(r.json()) == {"checked", "unknown_op_ids"}


async def test_verify_bounds_and_roles(client, ctx):
    ids = [str(uuid.uuid4()) for _ in range(1001)]
    assert (await client.post(V, headers=ctx["staff"], json={"op_ids": ids})).status_code == 422
    assert (await client.post(V, headers=ctx["staff"], json={"op_ids": []})).status_code == 422
    assert (await client.post(V, headers=ctx["staff"], json={"op_ids": ids[:1000]})).status_code == 200
    assert (await client.post(V, headers=ctx["staff"], json={"op_ids": ids[:1], "x": 1})).status_code == 422
    assert (await client.post(V, headers=ctx["ro"], json={"op_ids": ids[:1]})).status_code == 403
    assert (await client.post(V, json={"op_ids": ids[:1]})).status_code == 401


async def test_verify_audit_counts_only(client, ctx, db_session):
    ghost = str(uuid.uuid4())
    await client.post(V, headers=ctx["staff"], json={"op_ids": [ghost]})
    log = (await db_session.execute(select(AuditLog).where(AuditLog.action == "sync_verify"))).scalar_one()
    assert log.after_data == {"checked": 1, "unknown": 1} and ghost not in str(log.after_data)


# ---- snapshot ----
async def _seed_ref(client, ctx, db_session):
    h = ctx["admin"]
    dep = (await client.post("/api/v1/departments", headers=h, json={"code": "D1", "name": "Dept", "phone": "111"})).json()
    w = await client.post("/api/v1/wards", headers=h, json={"code": "W9", "name": "W9", "department_id": dep["id"], "phone": "222"})
    assert w.status_code == 201, w.text
    loc = await client.post("/api/v1/locations", headers=h, json={"name": "Loc"})
    return dep, w.json(), loc


async def test_snapshot_allow_list_and_no_forbidden_fields(client, ctx, db_session):
    r = await client.post(
        "/api/v1/equipment", headers=ctx["admin"],
        json={"asset_number": "AST-SECRET-9", "equipment_name": "Vent", "bcm_code": "BCM-1", "item_no": "ITEM-SECRET-7", "serial_number": "SN-SECRET"},
    )
    assert r.status_code == 201, r.text
    await _seed_ref(client, ctx, db_session)
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    await _send(client, ctx["staff"], op)
    for section, fields in snap.SECTION_FIELDS.items():
        resp = await client.get(S, headers=ctx["staff"], params={"section": section})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["items"], section
        for item in body["items"]:
            assert tuple(item) == fields
        text = resp.text
        for secret in ("ITEM-SECRET-7", "AST-SECRET-9", "SN-SECRET", "item_no", "asset_number", "serial_number", "qr_code"):
            assert secret not in text, (section, secret)
    eq = (await client.get(S, headers=ctx["staff"], params={"section": "equipment"})).json()["items"]
    assert any(i["bcm_code"] == "BCM-1" for i in eq)
    wards = (await client.get(S, headers=ctx["staff"], params={"section": "wards"})).json()["items"]
    assert any(i["phone"] == "222" for i in wards)
    deps = (await client.get(S, headers=ctx["staff"], params={"section": "departments"})).json()["items"]
    assert deps[0]["phone"] == "111"
    open_tx = (await client.get(S, headers=ctx["staff"], params={"section": "open_transactions"})).json()["items"]
    assert [t["id"] for t in open_tx] == [op["op_id"]]


async def test_snapshot_pagination_and_validation(client, ctx):
    for i in range(5):
        await _ward(client, ctx["admin"], code=f"WP{i}")
    seen, cursor = [], None
    while True:
        params = {"section": "wards", "limit": 2, **({"cursor": cursor} if cursor else {})}
        body = (await client.get(S, headers=ctx["ro"], params=params)).json()
        assert len(body["items"]) <= 2
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 6 and seen == sorted(seen)
    assert (await client.get(S, headers=ctx["ro"], params={"section": "users"})).status_code == 400
    assert (await client.get(S, headers=ctx["ro"], params={"section": "wards", "cursor": "zzz"})).status_code == 400
    assert (await client.get(S, headers=ctx["ro"], params={"section": "wards", "limit": 501})).status_code == 422
    assert (await client.get(S, params={"section": "wards"})).status_code == 401


async def test_snapshot_equipment_cursor_pages(client, ctx, db_session):
    for i in range(3):
        await _equipment(client, ctx["admin"], n=10 + i)
    # SQLite's CURRENT_TIMESTAMP default has no fractional part, which does not
    # compare equal to the driver's bound datetime text; PostgreSQL has no such
    # quirk. Store explicit timestamps (two share a value to exercise the id
    # tie-break) so the test is about the cursor logic, not the SQLite format.
    base = datetime(2026, 10, 13, 8, 0, 0, tzinfo=timezone.utc)
    ids = [r for r in (await db_session.execute(select(Equipment.id).order_by(Equipment.id))).scalars()]
    for n, eid in enumerate(ids):
        await db_session.execute(update(Equipment).where(Equipment.id == eid).values(updated_at=base + timedelta(seconds=n // 2)))
    await db_session.commit()
    seen, cursor = [], None
    while True:
        params = {"section": "equipment", "limit": 2, **({"cursor": cursor} if cursor else {})}
        body = (await client.get(S, headers=ctx["staff"], params=params)).json()
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 4, (seen, body)


async def test_snapshot_etag_304(client, ctx):
    r = await client.get(S, headers=ctx["staff"], params={"section": "wards"})
    etag = r.headers["etag"]
    r2 = await client.get(S, headers={**ctx["staff"], "If-None-Match": etag}, params={"section": "wards"})
    assert r2.status_code == 304 and r2.content == b"" and r2.headers["etag"] == etag
    await _ward(client, ctx["admin"], code="W-NEW")
    r3 = await client.get(S, headers={**ctx["staff"], "If-None-Match": etag}, params={"section": "wards"})
    assert r3.status_code == 200 and r3.headers["etag"] != etag


# ---- status / stats ----
async def test_status_admin_only_and_counts(client, ctx, db_session):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    await _send(client, ctx["staff"], op)
    await client.post(V, headers=ctx["staff"], json={"op_ids": [str(uuid.uuid4())]})
    await client.post(V, headers=ctx["staff"], json={"op_ids": [op["op_id"]]})
    for h in (ctx["staff"], ctx["ro"]):
        assert (await client.get(ST, headers=h)).status_code == 403
    assert (await client.get(ST)).status_code == 401
    b = (await client.get(ST, headers=ctx["admin"])).json()
    assert b["ops_by_status"]["applied"] == 1 and b["unresolved_conflicts"] == 0
    assert b["oldest_unresolved_conflict_age_s"] is None
    assert b["verify_calls"] == 2 and b["verify_calls_with_unknown"] == 1
    # an unresolved conflict shows count and age
    await db_session.execute(
        update(ClientOperation).values(status="conflict", received_at=datetime.now(timezone.utc) - timedelta(hours=3))
    )
    await db_session.commit()
    b = (await client.get(ST, headers=ctx["admin"])).json()
    assert b["unresolved_conflicts"] == 1 and b["oldest_unresolved_conflict_age_s"] >= 3 * 3600 - 5


async def test_stats_admin_only_aggregates_only(client, ctx, db_session):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    await _send(client, ctx["staff"], op)
    await db_session.execute(
        update(ClientOperation).values(
            occurred_at=datetime.now(timezone.utc) - timedelta(hours=2), clock_offset_ms=-4000, offset_age_s=30, time_flag="clamped_old"
        )
    )
    await db_session.commit()
    for h in (ctx["staff"], ctx["ro"]):
        assert (await client.get(SN, headers=h)).status_code == 403
    r = await client.get(SN, headers=ctx["admin"])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["volume"]["total_ops"] == 1 and b["volume"]["recorded_offline"] == 1
    assert b["volume"]["by_status"]["applied"] == 1
    assert b["clock_skew"]["abs_clock_offset_ms_histogram"]["<=5000"] == 1
    assert b["clock_skew"]["offset_age_s_histogram"]["<=60"] == 1
    assert b["clock_skew"]["time_flag_counts"] == {"clamped_old": 1}
    text = r.text
    for banned in ("payload", op["op_id"], ctx["eq"], ctx["ward"], "op_id", "device_id"):
        assert banned not in text


async def test_stats_range_validation(client, ctx):
    bad = await client.get(SN, headers=ctx["admin"], params={"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"})
    assert bad.status_code == 400
    wide = await client.get(SN, headers=ctx["admin"], params={"from": "2020-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"})
    assert wide.status_code == 400
    empty = await client.get(SN, headers=ctx["admin"])
    assert empty.json()["volume"]["total_ops"] == 0 and empty.json()["volume"]["conflicts_per_1000_ops"] is None
