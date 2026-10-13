"""Roadmap PR25B -- read-only export API (outbox cursor + machine keys)."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.export import ExportEvent
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio

ITEM_NO = "ITEM-SECRET-777"
ASSET = "AST-PR25B-SECRET"


async def _make_key(client, admin, name="Nsmart Realtime"):
    resp = await client.post("/api/v1/export-keys", headers=admin, json={"name": name})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body, {"X-API-Key": body["key"]}


async def _equipment(client, admin, n):
    resp = await client.post(
        "/api/v1/equipment",
        headers=admin,
        json={"asset_number": f"{ASSET}-{n}", "equipment_name": "Infusion Pump", "item_no": f"{ITEM_NO}-{n}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _dispatch(client, staff, equipment_id, ward_id, **extra):
    payload = {"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand", **extra}
    resp = await client.post("/api/v1/borrow", headers=staff, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _receive(client, staff, tx_id, outcome="usable"):
    resp = await client.post(f"/api/v1/return/{tx_id}", headers=staff, json={"receipt_outcome": outcome})
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def ctx(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward = await _create_ward(client, admin, "W-EXP", "Ward Export")
    _, key = await _make_key(client, admin)
    return {"admin": admin, "staff": staff, "ward": ward, "key": key}


async def _poll(client, key, **params):
    resp = await client.get("/api/v1/export/events", headers=key, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_dispatch_and_receipt_events(client, ctx):
    eq = await _equipment(client, ctx["admin"], 1)
    tx = await _dispatch(client, ctx["staff"], eq["id"], ctx["ward"])
    await _receive(client, ctx["staff"], tx["id"], "defective")

    page = await _poll(client, ctx["key"])
    assert [e["event_type"] for e in page["events"]] == ["dispatch", "receipt"]
    assert [e["seq"] for e in page["events"]] == [1, 2]
    assert page["next_cursor"] == 2 and page["has_more"] is False
    d, r = page["events"]
    assert d["event_id"] != r["event_id"]
    assert d["transaction_id"] == r["transaction_id"] == tx["id"]
    assert d["ward"] == {"id": ctx["ward"], "code": "W-EXP", "name": "Ward Export"}
    assert d["dispatch_type"] == "on_demand" and d["receipt_outcome"] is None
    assert r["receipt_outcome"] == "defective"
    assert d["equipment"]["id"] == eq["id"] and d["equipment"]["name"] == "Infusion Pump"
    assert d["operator_name"] == "Test equipment_pool_staff"
    datetime.fromisoformat(d["event_time"])


async def test_no_forbidden_fields_in_payload(client, ctx):
    eq = await _equipment(client, ctx["admin"], 1)
    tx = await _dispatch(client, ctx["staff"], eq["id"], ctx["ward"], notes="free text note", phone_number="0812345678")
    await _receive(client, ctx["staff"], tx["id"])
    raw = json.dumps(await _poll(client, ctx["key"])).lower()
    for forbidden in (ITEM_NO.lower(), ASSET.lower(), "item_no", "asset_number", "serial", "notes",
                      "free text note", "0812345678", "phone", "borrower_name", "patient", '"hn"', "email"):
        assert forbidden not in raw, forbidden


async def test_receipt_on_old_transaction_is_a_new_event(client, ctx):
    eq = await _equipment(client, ctx["admin"], 1)
    old = await _dispatch(client, ctx["staff"], eq["id"], ctx["ward"])
    eq2 = await _equipment(client, ctx["admin"], 2)
    for _ in range(1):
        newer = await _dispatch(client, ctx["staff"], eq2["id"], ctx["ward"])
    cursor = (await _poll(client, ctx["key"]))["next_cursor"]
    assert cursor == 2

    await _receive(client, ctx["staff"], old["id"])  # receipt of the oldest transaction
    page = await _poll(client, ctx["key"], after=cursor)
    assert len(page["events"]) == 1
    event = page["events"][0]
    assert event["event_type"] == "receipt" and event["transaction_id"] == old["id"]
    assert event["seq"] == 3
    assert newer["id"] != old["id"]


async def test_pagination_is_deterministic_and_complete(client, ctx):
    ids = []
    for n in range(5):
        eq = await _equipment(client, ctx["admin"], n)
        tx = await _dispatch(client, ctx["staff"], eq["id"], ctx["ward"])
        await _receive(client, ctx["staff"], tx["id"])
    seen, after, pages = [], 0, 0
    while True:
        page = await _poll(client, ctx["key"], after=after, limit=3)
        pages += 1
        seen += [e["seq"] for e in page["events"]]
        ids += [e["event_id"] for e in page["events"]]
        after = page["next_cursor"]
        if not page["has_more"]:
            break
    assert seen == list(range(1, 11)) and pages == 4
    assert len(set(ids)) == 10
    # Replaying the same cursor gives byte-identical output (stable ids too).
    again = await _poll(client, ctx["key"], after=0, limit=3)
    assert [e["event_id"] for e in again["events"]] == ids[:3]


async def test_empty_page_keeps_cursor(client, ctx):
    page = await _poll(client, ctx["key"], after=0)
    assert page == {"events": [], "next_cursor": 0, "has_more": False}


async def test_page_size_bounds(client, ctx):
    for limit in (0, 501, -1):
        resp = await client.get("/api/v1/export/events", headers=ctx["key"], params={"limit": limit})
        assert resp.status_code == 422
    resp = await client.get("/api/v1/export/events", headers=ctx["key"], params={"after": -1})
    assert resp.status_code == 422


async def test_cursor_ahead_of_head_is_refused(client, ctx):
    eq = await _equipment(client, ctx["admin"], 1)
    await _dispatch(client, ctx["staff"], eq["id"], ctx["ward"])
    resp = await client.get("/api/v1/export/events", headers=ctx["key"], params={"after": 99})
    assert resp.status_code == 409 and resp.json()["code"] == "EXPORT_CURSOR_AHEAD"


async def test_start_from_now_and_from_instant(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 1)
    tx = await _dispatch(client, ctx["staff"], eq["id"], ctx["ward"])
    await _receive(client, ctx["staff"], tx["id"])

    now_cursor = (await client.get("/api/v1/export/cursor", headers=ctx["key"])).json()["cursor"]
    assert now_cursor == 2
    assert (await _poll(client, ctx["key"], after=now_cursor))["events"] == []

    eq2 = await _equipment(client, ctx["admin"], 2)
    await _dispatch(client, ctx["staff"], eq2["id"], ctx["ward"])
    assert [e["seq"] for e in (await _poll(client, ctx["key"], after=now_cursor))["events"]] == [3]

    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = await client.get("/api/v1/export/cursor", headers=ctx["key"], params={"at": future})
    assert resp.json()["cursor"] == 3  # nothing at/after: same as "now"
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    resp = await client.get("/api/v1/export/cursor", headers=ctx["key"], params={"at": past})
    assert resp.json()["cursor"] == 0  # everything is at/after
    # naive instants are read as UTC
    resp = await client.get("/api/v1/export/cursor", headers=ctx["key"], params={"at": "2000-01-01T00:00:00"})
    assert resp.json()["cursor"] == 0


async def test_failed_dispatch_emits_no_event(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 1)
    await _dispatch(client, ctx["staff"], eq["id"], ctx["ward"])
    again = await client.post(
        "/api/v1/borrow", headers=ctx["staff"],
        json={"equipment_id": eq["id"], "ward_id": ctx["ward"], "dispatch_type": "on_demand"},
    )
    assert again.status_code == 409
    seqs = (await db_session.execute(select(ExportEvent.seq).order_by(ExportEvent.seq))).scalars().all()
    assert list(seqs) == [1]


async def test_duplicate_receipt_emits_no_second_event(client, ctx):
    eq = await _equipment(client, ctx["admin"], 1)
    tx = await _dispatch(client, ctx["staff"], eq["id"], ctx["ward"])
    await _receive(client, ctx["staff"], tx["id"])
    dup = await client.post(f"/api/v1/return/{tx['id']}", headers=ctx["staff"], json={"receipt_outcome": "usable"})
    assert dup.status_code == 409
    assert len((await _poll(client, ctx["key"]))["events"]) == 2


# --- auth ------------------------------------------------------------------


async def test_missing_wrong_and_malformed_key_are_401(client, ctx):
    for headers in ({}, {"X-API-Key": "mepx_wrong"}, {"X-API-Key": "nonsense"}, {"X-API-Key": ""}):
        for path in ("/api/v1/export/events", "/api/v1/export/cursor"):
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 401, (path, headers)
            assert resp.json()["code"] == "NOT_AUTHENTICATED"
            assert resp.headers["www-authenticate"] == "ApiKey"


async def test_revoked_key_is_401_immediately(client, ctx):
    admin = ctx["admin"]
    body, key = await _make_key(client, admin, "second")
    assert (await client.get("/api/v1/export/events", headers=key)).status_code == 200
    revoked = await client.post(f"/api/v1/export-keys/{body['id']}/revoke", headers=admin)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
    assert (await client.get("/api/v1/export/events", headers=key)).status_code == 401
    # other keys are unaffected; revoking again is a no-op
    assert (await client.get("/api/v1/export/events", headers=ctx["key"])).status_code == 200
    assert (await client.post(f"/api/v1/export-keys/{body['id']}/revoke", headers=admin)).status_code == 200


async def test_key_cannot_reach_any_other_endpoint(client, ctx):
    key = ctx["key"]
    as_bearer = {"Authorization": f"Bearer {key['X-API-Key']}"}
    for headers in (key, as_bearer, {**key, **as_bearer}):
        for method, path in (
            ("get", "/api/v1/equipment"), ("get", "/api/v1/auth/me"), ("get", "/api/v1/transactions"),
            ("get", "/api/v1/export-keys"), ("post", "/api/v1/export-keys"), ("get", "/api/v1/users"),
            ("post", "/api/v1/borrow"),
        ):
            resp = await getattr(client, method)(path, headers=headers)
            assert resp.status_code == 401, (method, path, resp.status_code)


async def test_human_tokens_cannot_use_export_endpoints(client, ctx):
    for role in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        for path in ("/api/v1/export/events", "/api/v1/export/cursor"):
            assert (await client.get(path, headers=headers)).status_code == 401


async def test_export_is_read_only(client, ctx):
    for method in ("post", "put", "patch", "delete"):
        resp = await getattr(client, method)("/api/v1/export/events", headers=ctx["key"])
        assert resp.status_code == 405


async def test_key_management_is_administrator_only(client, ctx, seeded_users):
    for role in (ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        assert (await client.get("/api/v1/export-keys", headers=headers)).status_code == 403
        assert (await client.post("/api/v1/export-keys", headers=headers, json={"name": "x"})).status_code == 403
    assert (await client.post("/api/v1/export-keys", headers=ctx["admin"], json={"name": ""})).status_code == 422


async def test_key_is_hashed_at_rest_and_shown_once(client, ctx, db_session):
    from app.models.export import ExportApiKey

    body, _ = await _make_key(client, ctx["admin"], "hash-check")
    row = (await db_session.execute(select(ExportApiKey).where(ExportApiKey.name == "hash-check"))).scalar_one()
    assert body["key"] not in (row.key_hash, row.key_prefix) and len(row.key_hash) == 64
    assert body["key"].startswith("mepx_") and body["key_prefix"] == body["key"][:12]
    listed = (await client.get("/api/v1/export-keys", headers=ctx["admin"])).json()
    assert all("key" not in item and "key_hash" not in item for item in listed)
    assert "last_used_at" in listed[0]
    used = next(i for i in listed if i["id"] == body["id"])
    assert used["last_used_at"] is None
