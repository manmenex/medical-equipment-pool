import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import update

from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio

DAY_UTC = datetime(2026, 7, 28, 3, 0, 0, tzinfo=timezone.utc)  # Bangkok 10:00 -> day, 07-28
NIGHT_UTC = datetime(2026, 7, 28, 0, 30, 0, tzinfo=timezone.utc)  # Bangkok 07:30 -> night, 07-27

ALLOWED_KEYS = {
    "id",
    "kind",
    "event_at",
    "business_date",
    "shift",
    "ward",
    "operator",
    "equipment",
    "receipt_outcome",
    "close_reason",
    # Roadmap PR27/PR28 additions (contact name, checklist, outstanding cuffs).
    "ward_contact_name",
    "checklist_kind",
    "checks",
    "cuffs_outstanding",
    # Roadmap PR29: indicator only; the HN itself is never in this feed.
    "has_hn",
    "is_open",
    # D22: display-only keyer label.
    "keyer_label",
}


async def _eq(client, headers, asset, bcm):
    r = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": asset, "equipment_name": "Pump", "bcm_code": bcm},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _dispatch(client, headers, eq_id, ward_id):
    r = await client.post(
        "/api/v1/borrow",
        headers=headers,
        json={"equipment_id": eq_id, "ward_id": ward_id, "dispatch_type": "on_demand"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _force(db, tx_id, **values):
    await db.execute(update(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx_id)).values(**values))
    await db.commit()


async def test_auth_and_roles(client, seeded_users):
    assert (await client.get("/api/v1/monitor/events")).status_code == 401
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    assert (await client.get("/api/v1/monitor/events", headers=ro)).status_code == 403
    for role in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF):
        resp = await client.get("/api/v1/monitor/events", headers=await _auth_headers(client, role))
        assert resp.status_code == 200, resp.text


async def test_dispatch_and_receipt_events_filters_shift_and_keys(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    w1 = await _create_ward(client, admin, "W-M1", "Ward One")
    w2 = await _create_ward(client, admin, "W-M2", "Ward Two")
    e1 = await _eq(client, admin, "AST-M-1", "BCM-M-1")
    e2 = await _eq(client, admin, "AST-M-2", "BCM-M-2")
    t1 = await _dispatch(client, staff, e1["id"], w1)
    t2 = await _dispatch(client, staff, e2["id"], w2)
    await _force(db_session, t1["id"], borrowed_at=DAY_UTC)
    await _force(db_session, t2["id"], borrowed_at=NIGHT_UTC)
    r = await client.post(f"/api/v1/return/{t1['id']}", headers=staff, json={"receipt_outcome": "defective"})
    assert r.status_code == 200, r.text
    await _force(db_session, t1["id"], returned_at=DAY_UTC)

    resp = await client.get("/api/v1/monitor/events", headers=staff, params={"kind": "dispatch"})
    body = resp.json()
    assert body["total"] == 2
    # newest first: DAY_UTC (03:00) before NIGHT_UTC (00:30)
    assert [i["equipment"]["bcm_code"] for i in body["items"]] == ["BCM-M-1", "BCM-M-2"]
    assert [i["shift"] for i in body["items"]] == ["day", "night"]
    assert body["items"][1]["business_date"] == "2026-07-27"
    for item in body["items"]:
        assert set(item) == ALLOWED_KEYS
        assert "hn" not in {k.lower() for k in item}
        assert item["receipt_outcome"] is None
    assert body["items"][0]["ward"]["name"] == "Ward One"
    assert body["items"][0]["operator"]["full_name"]

    rec = (await client.get("/api/v1/monitor/events", headers=staff, params={"kind": "receipt"})).json()
    assert rec["total"] == 1
    assert rec["items"][0]["receipt_outcome"] == "defective"
    assert rec["items"][0]["kind"] == "receipt"

    f = (await client.get("/api/v1/monitor/events", headers=staff, params={"ward_id": w2})).json()
    assert [i["equipment"]["bcm_code"] for i in f["items"]] == ["BCM-M-2"]

    f = (await client.get("/api/v1/monitor/events", headers=staff, params={"q": "bcm-m-1"})).json()
    assert f["total"] == 1

    f = (
        await client.get(
            "/api/v1/monitor/events",
            headers=staff,
            params={"business_date_from": "2026-07-28", "business_date_to": "2026-07-28"},
        )
    ).json()
    assert [i["equipment"]["bcm_code"] for i in f["items"]] == ["BCM-M-1"]

    bad = await client.get(
        "/api/v1/monitor/events",
        headers=staff,
        params={"business_date_from": "2026-07-29", "business_date_to": "2026-07-28"},
    )
    assert bad.status_code == 400


async def test_pagination_and_bad_cursor(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    w = await _create_ward(client, admin, "W-MP", "Ward P")
    for n in range(3):
        e = await _eq(client, admin, f"AST-MP-{n}", f"BCM-MP-{n}")
        await _dispatch(client, staff, e["id"], w)
    seen = []
    cursor = None
    for _ in range(5):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/api/v1/monitor/events", headers=staff, params=params)).json()
        seen += [i["id"] for i in page["items"]]
        assert page["total"] == 3
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 3 and len(set(seen)) == 3
    bad = await client.get("/api/v1/monitor/events", headers=staff, params={"cursor": "###"})
    assert bad.status_code == 400


async def _one(client, admin, staff, db, n, at, w=None):
    w = w or await _create_ward(client, admin, f"W-B{n}", f"Ward B{n}")
    e = await _eq(client, admin, f"AST-B-{n}", f"BCM-B-{n}")
    t = await _dispatch(client, staff, e["id"], w)
    await _force(db, t["id"], borrowed_at=at)
    return t


async def test_exact_shift_boundaries_and_night_evening(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    # Bangkok local = UTC+7. (utc, expected shift, expected business_date)
    cases = [
        (datetime(2026, 7, 27, 0, 59, 59, tzinfo=timezone.utc), "night", "2026-07-26"),  # 07:59:59
        (datetime(2026, 7, 27, 1, 0, 0, tzinfo=timezone.utc), "day", "2026-07-27"),  # 08:00
        (datetime(2026, 7, 27, 12, 59, 59, tzinfo=timezone.utc), "day", "2026-07-27"),  # 19:59:59
        (datetime(2026, 7, 27, 13, 0, 0, tzinfo=timezone.utc), "night", "2026-07-27"),  # 20:00
        (datetime(2026, 7, 27, 16, 59, 0, tzinfo=timezone.utc), "night", "2026-07-27"),  # 23:59 local
    ]
    for n, (at, _, _) in enumerate(cases):
        await _one(client, admin, staff, db_session, n, at)
    body = (await client.get("/api/v1/monitor/events", headers=staff)).json()
    got = {i["event_at"][:19]: (i["shift"], i["business_date"]) for i in body["items"]}
    for at, shift, bd in cases:
        assert got[at.strftime("%Y-%m-%dT%H:%M:%S")] == (shift, bd)
    f = (
        await client.get(
            "/api/v1/monitor/events",
            headers=staff,
            params={"business_date_from": "2026-07-27", "business_date_to": "2026-07-27"},
        )
    ).json()
    assert f["total"] == 4
    assert "BCM-B-0" not in [i["equipment"]["bcm_code"] for i in f["items"]]


async def test_cursor_tiebreak_identical_timestamps(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    w = await _create_ward(client, admin, "W-TIE", "Tie")
    for n in range(5):
        await _one(client, admin, staff, db_session, 100 + n, DAY_UTC, w)
    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (await client.get("/api/v1/monitor/events", headers=staff, params=params)).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5 and len(set(seen)) == 5


async def test_receipt_operator_is_receiver_not_dispatcher(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    w = await _create_ward(client, admin, "W-OP", "Op")
    e = await _eq(client, admin, "AST-OP-1", "BCM-OP-1")
    t = await _dispatch(client, staff, e["id"], w)
    r = await client.post(f"/api/v1/return/{t['id']}", headers=admin, json={"receipt_outcome": "usable"})
    assert r.status_code == 200, r.text
    d = (await client.get("/api/v1/monitor/events", headers=staff, params={"kind": "dispatch"})).json()
    rc = (await client.get("/api/v1/monitor/events", headers=staff, params={"kind": "receipt"})).json()
    assert rc["items"][0]["operator"]["id"] != d["items"][0]["operator"]["id"]


async def test_keyer_label_and_checks_returned_for_synced_rows(client, seeded_users, db_session):
    """D22: keyer_label is exposed per event side; stored checks are returned (NULL stays null)."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    w = await _create_ward(client, admin, "W-KL", "Kl")
    e = await _eq(client, admin, "AST-KL-1", "BCM-KL-1")
    t = await _dispatch(client, staff, e["id"], w)
    chk = {"kind": "standard", "screen_ok": True, "charger_ok": True, "clamp_ok": False}
    await _force(db_session, t["id"], dispatch_keyer_label="BME Synthetic", dispatch_checks=chk)
    d = (await client.get("/api/v1/monitor/events", headers=staff, params={"kind": "dispatch"})).json()["items"][0]
    assert d["keyer_label"] == "BME Synthetic" and d["checks"] == chk
    r = await client.post(f"/api/v1/return/{t['id']}", headers=admin, json={"receipt_outcome": "usable"})
    assert r.status_code == 200, r.text
    rc = (await client.get("/api/v1/monitor/events", headers=staff, params={"kind": "receipt"})).json()["items"][0]
    assert rc["keyer_label"] is None and rc["checks"] is None  # genuinely NULL -> UI shows "-"
