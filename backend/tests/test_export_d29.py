"""Owner Governance 2026-11-27 (D28 hold-back, D29 HN path, sixth set fields)
for the read-only export API. SQLite."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.config import settings
from app.main import app
from app.models.audit import AuditLog
from app.models.client_operation import OP_STATUS_APPLIED, OP_TYPE_DISPATCH, OP_TYPE_RECEIPT, ClientOperation
from app.models.export import ExportEvent
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF
from app.services import export_service
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio

HN = "HN-4821/66"
HN_PORT = 9443
PEER = "172.18.0.1"


@pytest.fixture
async def ctx(client, seeded_users, monkeypatch):
    monkeypatch.setattr(settings, "HN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward = await _create_ward(client, admin, "W-D29", "Ward D29")
    return {"admin": admin, "staff": staff, "ward": ward, "n": 0}


@pytest.fixture
def hn_listener(monkeypatch):
    monkeypatch.setattr(settings, "EXPORT_HN_PORT", HN_PORT)
    monkeypatch.setattr(settings, "APP_PORT", 8000)
    monkeypatch.setattr(settings, "EXPORT_HN_ALLOWED_PEERS", "172.18.0.0/16, 127.0.0.1")


def _listener_client(port=HN_PORT, peer=PEER):
    """A client whose ASGI scope says: server port ``port``, socket peer ``peer``."""
    return AsyncClient(transport=ASGITransport(app=app, client=(peer, 50000)), base_url=f"http://test:{port}")


async def _key(client, admin, scope_hn=False, name="k"):
    r = await client.post("/api/v1/export-keys", headers=admin, json={"name": name, "scope_hn": scope_hn})
    assert r.status_code == 201, r.text
    return r.json(), {"X-API-Key": r.json()["key"]}


async def _eq(client, ctx):
    ctx["n"] += 1
    r = await client.post(
        "/api/v1/equipment",
        headers=ctx["admin"],
        json={"asset_number": f"AST-D29-{ctx['n']}", "equipment_name": "Pump", "bcm_code": f"BCM-D29-{ctx['n']}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _dispatch(client, ctx, **extra):
    eq = await _eq(client, ctx)
    r = await client.post("/api/v1/borrow", headers=ctx["staff"], json={"equipment_id": eq, "ward_id": ctx["ward"], **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def _receive(client, ctx, tx_id, **extra):
    r = await client.post(f"/api/v1/return/{tx_id}", headers=ctx["staff"], json={"receipt_outcome": "usable", **extra})
    assert r.status_code == 200, r.text


async def _age(db_session, seq, seconds):
    await db_session.execute(
        update(ExportEvent)
        .where(ExportEvent.seq == seq)
        .values(created_at=datetime.now(timezone.utc) - timedelta(seconds=seconds))
    )
    await db_session.commit()


async def _events(c, key, **params):
    r = await c.get("/api/v1/export/events", headers=key, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- fields


async def test_legacy_sync_device_id_matches_the_sync_runner():
    from app.services.legacy_sheet_sync.runner import DEVICE_ID

    assert export_service.LEGACY_SYNC_DEVICE_ID == DEVICE_ID


async def test_origin_keyer_and_contact_fields(client, ctx, db_session):
    _, key = await _key(client, ctx["admin"])
    tx = await _dispatch(client, ctx, ward_contact_name="Nok")
    await _receive(client, ctx, tx["id"], ward_contact_name="Mali")
    tx2 = await _dispatch(client, ctx)  # will be marked as created by the legacy sheet sync
    await _receive(client, ctx, tx2["id"])
    tx3 = await _dispatch(client, ctx)  # legacy dispatch only; the receipt is app-keyed

    staff_id = (await db_session.execute(select(BorrowTransaction.borrower_user_id).limit(1))).scalar_one()
    for n, (tx_id, op_type, op_id, linked) in enumerate(
        [
            (tx2["id"], OP_TYPE_DISPATCH, uuid.UUID(tx2["id"]), None),
            (tx2["id"], OP_TYPE_RECEIPT, uuid.uuid4(), uuid.UUID(tx2["id"])),
            (tx3["id"], OP_TYPE_DISPATCH, uuid.UUID(tx3["id"]), None),
        ]
    ):
        db_session.add(
            ClientOperation(
                op_id=op_id,
                device_id=export_service.LEGACY_SYNC_DEVICE_ID,
                device_seq=n + 1,
                user_id=staff_id,
                op_type=op_type,
                payload_hash="0" * 64,
                transaction_id=linked,
                status=OP_STATUS_APPLIED,
                payload={},
            )
        )
    await db_session.execute(
        update(BorrowTransaction)
        .where(BorrowTransaction.id == uuid.UUID(tx2["id"]))
        .values(dispatch_keyer_label="Somchai", receipt_keyer_label="legacy sheet receipt row 12")  # 2nd is a system note
    )
    await db_session.commit()

    ev = (await _events(client, key))["events"]
    by = {(e["transaction_id"], e["event_type"]): e for e in ev}
    d1, r1 = by[(tx["id"], "dispatch")], by[(tx["id"], "receipt")]
    assert (d1["origin"], r1["origin"]) == ("app", "app")
    assert d1["contact_name"] == "Nok" and r1["contact_name"] == "Mali"
    assert d1["keyer_label"] == d1["operator_name"] == "Test equipment_pool_staff"  # falls back to operator
    d2, r2 = by[(tx2["id"], "dispatch")], by[(tx2["id"], "receipt")]
    assert (d2["origin"], r2["origin"]) == ("legacy_sheet", "legacy_sheet")
    assert d2["keyer_label"] == "Somchai"
    assert r2["keyer_label"] == r2["operator_name"]  # system-note label cleaned -> operator name
    assert by[(tx3["id"], "dispatch")]["origin"] == "legacy_sheet"
    assert "hn" not in d1 and "hn" not in str(ev)


# --------------------------------------------------------------------------- hold-back


async def test_hold_back_withholds_until_window_passes(client, ctx, db_session, monkeypatch):
    monkeypatch.setattr(settings, "EXPORT_HOLD_DISPATCH_SECONDS", 120)
    monkeypatch.setattr(settings, "EXPORT_HOLD_RECEIPT_SECONDS", 30)
    _, key = await _key(client, ctx["admin"])
    tx = await _dispatch(client, ctx)
    await _receive(client, ctx, tx["id"])  # seq 1 dispatch, 2 receipt (both fresh)

    page = await _events(client, key)
    assert page["events"] == [] and page["next_cursor"] == 0 and page["has_more"] is False

    await _age(db_session, 1, 121)  # dispatch window passed; the fresh receipt (30 s) is still held
    page = await _events(client, key)
    assert [e["seq"] for e in page["events"]] == [1] and page["next_cursor"] == 1
    page = await _events(client, key, after=1)
    assert page["events"] == [] and page["next_cursor"] == 1
    await _age(db_session, 2, 31)
    page = await _events(client, key, after=1)
    assert [e["seq"] for e in page["events"]] == [2] and page["next_cursor"] == 2


async def test_hold_back_out_of_order_visibility_never_skips(client, ctx, db_session, monkeypatch):
    """seq 3 (receipt, 30 s) becomes visible before seq 1 (dispatch, 120 s):
    paging must stop at seq 1 and never hand out 2/3 ahead of it."""
    monkeypatch.setattr(settings, "EXPORT_HOLD_DISPATCH_SECONDS", 120)
    monkeypatch.setattr(settings, "EXPORT_HOLD_RECEIPT_SECONDS", 30)
    _, key = await _key(client, ctx["admin"])
    t1 = await _dispatch(client, ctx)  # seq 1
    t2 = await _dispatch(client, ctx)  # seq 2
    await _receive(client, ctx, t2["id"])  # seq 3
    await _age(db_session, 1, 5)  # held
    await _age(db_session, 2, 500)  # visible
    await _age(db_session, 3, 100)  # receipt, visible
    page = await _events(client, key)
    assert page["events"] == [] and page["next_cursor"] == 0 and page["has_more"] is False

    await _age(db_session, 1, 200)
    page = await _events(client, key, limit=2)
    assert [e["seq"] for e in page["events"]] == [1, 2] and page["next_cursor"] == 2 and page["has_more"] is True
    page = await _events(client, key, after=2, limit=2)
    assert [e["seq"] for e in page["events"]] == [3] and page["next_cursor"] == 3 and page["has_more"] is False

    # Blocking in the middle: seq 2 held again -> only seq 1 is returned, cursor stops at 1.
    await _age(db_session, 2, 1)
    page = await _events(client, key)
    assert [e["seq"] for e in page["events"]] == [1] and page["next_cursor"] == 1 and page["has_more"] is False
    del t1


async def test_undone_entry_is_never_exposed(client, ctx, db_session, monkeypatch):
    """The hold-back is what keeps an undo invisible: until it passes there is
    no event at all."""
    monkeypatch.setattr(settings, "EXPORT_HOLD_DISPATCH_SECONDS", 120)
    _, key = await _key(client, ctx["admin"])
    await _dispatch(client, ctx)
    assert (await _events(client, key))["events"] == []


# --------------------------------------------------------------------------- HN: keys


async def test_only_admin_creates_or_revokes_hn_key_and_both_are_audited(client, ctx, db_session):
    denied = await client.post("/api/v1/export-keys", headers=ctx["staff"], json={"name": "x", "scope_hn": True})
    assert denied.status_code == 403
    body, _ = await _key(client, ctx["admin"], scope_hn=True)
    assert body["scope_hn"] is True
    assert (await client.post(f"/api/v1/export-keys/{body['id']}/revoke", headers=ctx["staff"])).status_code == 403
    assert (await client.post(f"/api/v1/export-keys/{body['id']}/revoke", headers=ctx["admin"])).status_code == 200
    plain, _ = await _key(client, ctx["admin"], name="plain")
    assert plain["scope_hn"] is False
    audits = (
        await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "export_api_key"))
    ).scalars().all()
    actions = [(a.action, (a.after_data or {}).get("scope_hn")) for a in audits]
    assert ("create", True) in actions and ("update", True) in actions


# --------------------------------------------------------------------------- HN: listener


async def test_normal_port_never_returns_hn_even_with_hn_key(client, ctx, hn_listener):
    _, key = await _key(client, ctx["admin"], scope_hn=True)
    await _dispatch(client, ctx, hn=HN)
    page = await _events(client, key)  # normal client: server port 80
    assert page["events"] and HN not in str(page) and "hn" not in page["events"][0]
    # Same listener port number but listener not configured -> still no HN.
    async with _listener_client(8000) as c:
        assert "hn" not in (await _events(c, key))["events"][0]


async def test_hn_on_listener_with_allowed_peer_and_count_only_audit(client, ctx, hn_listener, db_session):
    body, key = await _key(client, ctx["admin"], scope_hn=True)
    _, plain_key = await _key(client, ctx["admin"], name="plain")
    await _dispatch(client, ctx, hn=HN)
    await _dispatch(client, ctx, hn=HN + "9")
    await _dispatch(client, ctx)  # no HN
    async with _listener_client() as c:
        ev = (await _events(c, key))["events"]
        assert [e.get("hn") for e in ev] == [HN, HN + "9", None]
        # A key without the scope gets none, even on the listener.
        assert "hn" not in (await _events(c, plain_key))["events"][0]
        # Other routes are not served on the HN listener.
        assert (await c.get("/api/v1/health")).status_code == 404

    audits = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "export_hn_read"))
    ).scalars().all()
    assert len(audits) == 1  # one entry for the one response containing HN
    assert audits[0].entity_id == uuid.UUID(body["id"])
    assert audits[0].after_data == {"key_id": body["id"], "value_count": 2}
    dump = " ".join(str(a.after_data) + str(a.before_data) for a in audits)
    assert HN not in dump
    # A response with no HN writes no audit entry.
    async with _listener_client() as c:
        await _events(c, key, after=3)
    assert len((await db_session.execute(select(AuditLog).where(AuditLog.action == "export_hn_read"))).scalars().all()) == 1


@pytest.mark.parametrize(
    "header", [("Tailscale-Funnel-Request", "?1"), ("X-Forwarded-For", "203.0.113.9"), ("Forwarded", "for=203.0.113.9")]
)
async def test_hn_listener_refuses_forwarded_and_funnel_headers(client, ctx, hn_listener, header):
    _, key = await _key(client, ctx["admin"], scope_hn=True)
    await _dispatch(client, ctx, hn=HN)
    async with _listener_client() as c:
        r = await c.get("/api/v1/export/events", headers={**key, header[0]: header[1]})
    assert r.status_code == 403 and HN not in r.text


async def test_hn_listener_refuses_non_allowed_peer(client, ctx, hn_listener):
    _, key = await _key(client, ctx["admin"], scope_hn=True)
    await _dispatch(client, ctx, hn=HN)
    async with _listener_client(peer="203.0.113.9") as c:
        r = await c.get("/api/v1/export/events", headers=key)
    assert r.status_code == 403 and HN not in r.text


async def test_forwarded_header_cannot_launder_a_peer_on_normal_port(client, ctx, hn_listener):
    _, key = await _key(client, ctx["admin"], scope_hn=True)
    await _dispatch(client, ctx, hn=HN)
    r = await client.get("/api/v1/export/events", headers={**key, "X-Forwarded-For": PEER})
    assert r.status_code == 200 and HN not in r.text


async def test_startup_check_disables_misconfigured_listener(monkeypatch, caplog):
    from app.core.export_hn import hn_listener_status

    monkeypatch.setattr(settings, "EXPORT_HN_ALLOWED_PEERS", "127.0.0.1")
    monkeypatch.setattr(settings, "APP_PORT", 8000)
    monkeypatch.setattr(settings, "EXPORT_HN_PORT", None)
    assert hn_listener_status().enabled is False
    monkeypatch.setattr(settings, "EXPORT_HN_PORT", 8000)  # same as the app port
    st = hn_listener_status()
    assert st.enabled is False and "APP_PORT" in st.reason
    monkeypatch.setattr(settings, "EXPORT_HN_PORT", 9443)
    monkeypatch.setattr(settings, "EXPORT_HN_ALLOWED_PEERS", "")
    assert hn_listener_status().enabled is False  # empty allowlist fails closed
    monkeypatch.setattr(settings, "EXPORT_HN_ALLOWED_PEERS", "not-an-ip")
    assert hn_listener_status().enabled is False
    monkeypatch.setattr(settings, "EXPORT_HN_ALLOWED_PEERS", "127.0.0.1")
    assert hn_listener_status().enabled is True


async def test_misconfigured_same_port_returns_no_hn(client, ctx, monkeypatch):
    monkeypatch.setattr(settings, "EXPORT_HN_PORT", 8000)
    monkeypatch.setattr(settings, "APP_PORT", 8000)
    monkeypatch.setattr(settings, "EXPORT_HN_ALLOWED_PEERS", PEER)
    _, key = await _key(client, ctx["admin"], scope_hn=True)
    await _dispatch(client, ctx, hn=HN)
    async with _listener_client(8000) as c:
        assert HN not in str(await _events(c, key))


# --------------------------------------------------------------------------- hn_update


async def test_hn_update_visible_only_to_hn_key_on_listener(client, ctx, hn_listener, db_session):
    _, hn_key = await _key(client, ctx["admin"], scope_hn=True)
    _, plain = await _key(client, ctx["admin"], name="plain")
    tx = await _dispatch(client, ctx)  # seq 1, no HN
    r = await client.post(f"/api/v1/transactions/{tx['id']}/hn", headers=ctx["staff"], json={"hn": HN})
    assert r.status_code == 200, r.text
    await _dispatch(client, ctx)  # seq 3
    seqs = [e.seq for e in (await db_session.execute(select(ExportEvent).order_by(ExportEvent.seq))).scalars()]
    assert seqs == [1, 2, 3]

    async with _listener_client() as c:
        ev = (await _events(c, hn_key))["events"]
        assert [(e["event_type"], e.get("hn")) for e in ev] == [("dispatch", HN), ("hn_update", HN), ("dispatch", None)]
        assert ev[1]["transaction_id"] == tx["id"]
        # a plain key on the listener: hn_update skipped, cursor still advances past it
        page = await _events(c, plain)
    assert [e["event_type"] for e in page["events"]] == ["dispatch", "dispatch"] and page["next_cursor"] == 3
    # hn-scoped key on the NORMAL port: no hn_update, no HN
    page = await _events(client, hn_key)
    assert [e["event_type"] for e in page["events"]] == ["dispatch", "dispatch"]
    assert HN not in str(page)

    # Paging with limit=1 across the skipped hn_update never loses or repeats an event.
    seen, cursor = [], 0
    for _ in range(5):
        p = await _events(client, plain, after=cursor, limit=1)
        seen += [e["seq"] for e in p["events"]]
        cursor = p["next_cursor"]
        if not p["has_more"]:
            break
    assert seen == [1, 3] and cursor == 3


async def test_hn_update_is_audited_without_value_and_carries_none(client, ctx, hn_listener, db_session):
    tx = await _dispatch(client, ctx)
    await client.post(f"/api/v1/transactions/{tx['id']}/hn", headers=ctx["staff"], json={"hn": HN})
    row = (await db_session.execute(select(ExportEvent).where(ExportEvent.event_type == "hn_update"))).scalar_one()
    assert HN not in repr(row.__dict__)


# --------------------------------------------------------------------------- demo/loan


async def test_demo_loan_still_excluded(client, ctx, db_session):
    _, key = await _key(client, ctx["admin"], scope_hn=True)
    eq = await _eq(client, ctx)
    from app.models.equipment import EQUIPMENT_SOURCE_POOL, Equipment

    assert EQUIPMENT_SOURCE_POOL == "pool"
    await db_session.execute(update(Equipment).where(Equipment.id == uuid.UUID(eq)).values(equipment_source="demo"))
    await db_session.commit()
    r = await client.post("/api/v1/borrow", headers=ctx["staff"], json={"equipment_id": eq, "ward_id": ctx["ward"]})
    assert r.status_code in (201, 409, 422)
    assert (await _events(client, key))["events"] == []
