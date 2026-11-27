"""Owner Governance 2026-11-27 (D28): export API compensating (correction)
events, withdrawn-in-window originals, re-receive, HN exclusion. SQLite."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from app.core.config import settings
from app.models.export import ExportEvent
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward
from tests.test_export_d29 import HN, _key, _listener_client, hn_listener  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def ctx(client, seeded_users, monkeypatch):
    monkeypatch.setattr(settings, "HN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "EXPORT_HOLD_DISPATCH_SECONDS", 120)
    monkeypatch.setattr(settings, "EXPORT_HOLD_RECEIPT_SECONDS", 30)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    eqs = []
    for n in (1, 2):
        r = await client.post(
            "/api/v1/equipment",
            headers=admin,
            json={"asset_number": f"AST-XC-{n}", "equipment_name": "Pump", "bcm_code": f"BCM-XC-{n}"},
        )
        eqs.append(r.json()["id"])
    return {
        "admin": admin,
        "staff": staff,
        "eq1": eqs[0],
        "eq2": eqs[1],
        "ward_a": await _create_ward(client, admin, "W-XCA", "Ward A"),
        "ward_b": await _create_ward(client, admin, "W-XCB", "Ward B"),
    }


async def _dispatch(client, ctx, eq="eq1", **extra):
    r = await client.post(
        "/api/v1/borrow",
        headers=ctx["staff"],
        json={"equipment_id": ctx[eq], "ward_id": ctx["ward_a"], "dispatch_type": "on_demand", **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _receive(client, ctx, tx_id):
    r = await client.post(f"/api/v1/return/{tx_id}", headers=ctx["staff"], json={"receipt_outcome": "usable"})
    assert r.status_code == 200, r.text


async def _age_all(db_session):
    await db_session.execute(update(ExportEvent).values(created_at=datetime.now(timezone.utc) - timedelta(hours=1)))
    await db_session.commit()


async def _events(client, key, c=None):
    r = await (c or client).get("/api/v1/export/events", headers=key, params={"after": 0})
    assert r.status_code == 200, r.text
    return r.json()["events"]


async def _act(client, ctx, tx_id, action, body):
    r = await client.post(f"/api/v1/transactions/{tx_id}/{action}", headers=ctx["admin"], json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def test_void_dispatch_after_visible_emits_one_correction_receipt_without_hn(client, ctx, db_session, hn_listener):
    _, key = await _key(client, ctx["admin"], scope_hn=True)
    tx = await _dispatch(client, ctx, hn=HN)
    await _age_all(db_session)
    async with _listener_client() as hc:
        [orig] = await _events(client, key, hc)
        assert orig["hn"] == HN  # HN-scoped key on the HN listener sees the dispatch HN
        await _act(client, ctx, tx["id"], "void", {"reason": "wrong ward"})
        evs = await _events(client, key, hc)
    assert [e["event_type"] for e in evs] == ["dispatch", "receipt"]
    disp, corr = evs
    assert disp["transaction_status"] == "voided" and disp["correction"] is False
    assert corr["correction"] is True and corr["corrects_event_id"] == orig["event_id"]
    assert corr["transaction_id"] == tx["id"] and corr["seq"] > disp["seq"]
    assert corr.get("hn") is None
    assert HN not in str(corr) and HN not in str(disp)  # a voided dispatch no longer exposes HN


async def test_void_receipt_after_visible_emits_correction_dispatch_and_rereceive_emits_receipt(client, ctx, db_session):
    _, key = await _key(client, ctx["admin"])
    tx = await _dispatch(client, ctx)
    await _receive(client, ctx, tx["id"])
    await _age_all(db_session)
    await _act(client, ctx, tx["id"], "void", {"reason": "not returned"})
    evs = await _events(client, key)
    assert [(e["event_type"], e["correction"]) for e in evs] == [
        ("dispatch", False),
        ("receipt", False),
        ("dispatch", True),
    ]
    assert evs[2]["corrects_event_id"] == evs[1]["event_id"]
    await _receive(client, ctx, tx["id"])  # re-receive must emit, not be swallowed or crash
    await _age_all(db_session)
    evs = await _events(client, key)
    assert len(evs) == 4 and (evs[-1]["event_type"], evs[-1]["correction"]) == ("receipt", False)


async def test_change_device_after_visible_gives_correction_plus_new_dispatch(client, ctx, db_session):
    _, key = await _key(client, ctx["admin"])
    tx = await _dispatch(client, ctx)
    await _age_all(db_session)
    await _act(client, ctx, tx["id"], "change-device", {"reason": "wrong pump", "equipment_id": ctx["eq2"]})
    await _age_all(db_session)
    evs = await _events(client, key)
    assert [(e["event_type"], e["correction"], e["equipment"]["id"]) for e in evs] == [
        ("dispatch", False, ctx["eq1"]),
        ("receipt", True, ctx["eq1"]),
        ("dispatch", False, ctx["eq2"]),
    ]


async def test_switch_action_after_visible(client, ctx, db_session):
    _, key = await _key(client, ctx["admin"])
    tx = await _dispatch(client, ctx)
    await _receive(client, ctx, tx["id"])
    await _age_all(db_session)
    await _act(client, ctx, tx["id"], "switch-action", {"reason": "was a dispatch", "ward_id": ctx["ward_b"]})
    await _age_all(db_session)
    kinds = [(e["event_type"], e["correction"]) for e in await _events(client, key)]
    # receipt voided -> compensating dispatch; the corrected dispatch follows normally.
    assert kinds[:3] == [("dispatch", False), ("receipt", False), ("dispatch", True)]
    assert kinds[-1] == ("dispatch", False) and len(kinds) == 4


async def test_undo_within_window_exposes_nothing_ever(client, ctx, db_session):
    _, key = await _key(client, ctx["admin"])
    tx = await _dispatch(client, ctx)
    r = await client.post(f"/api/v1/transactions/{tx['id']}/undo", headers=ctx["staff"])
    assert r.status_code == 200, r.text
    assert await _events(client, key) == []
    await _age_all(db_session)
    assert await _events(client, key) == []
    assert (await db_session.execute(select(ExportEvent))).scalar_one().withdrawn is True


async def test_receipt_undo_within_window_exposes_no_receipt_or_correction(client, ctx, db_session):
    _, key = await _key(client, ctx["admin"])
    tx = await _dispatch(client, ctx)
    await _age_all(db_session)
    await _receive(client, ctx, tx["id"])
    r = await client.post(f"/api/v1/transactions/{tx['id']}/undo", headers=ctx["staff"])
    assert r.status_code == 200, r.text
    await _age_all(db_session)
    assert [(e["event_type"], e["correction"]) for e in await _events(client, key)] == [("dispatch", False)]


async def test_corrections_follow_the_cursor_without_hold_back(client, ctx, db_session):
    _, key = await _key(client, ctx["admin"])
    tx = await _dispatch(client, ctx)
    await _age_all(db_session)
    first = (await client.get("/api/v1/export/events", headers=key, params={"after": 0})).json()
    await _act(client, ctx, tx["id"], "void", {"reason": "oops"})
    page = (await client.get("/api/v1/export/events", headers=key, params={"after": first["next_cursor"]})).json()
    assert [(e["event_type"], e["correction"]) for e in page["events"]] == [("receipt", True)]


async def _age_seq(db_session, seq, seconds):
    await db_session.execute(
        update(ExportEvent).where(ExportEvent.seq == seq).values(created_at=datetime.now(timezone.utc) - timedelta(seconds=seconds))
    )
    await db_session.commit()


async def test_void_inside_safety_margin_corrects_instead_of_withdrawing(client, ctx, db_session):
    """Dispatch event is 115 s old (hold 120 s): not yet visible, but within 10 s
    of becoming so -- a reader could see it before this commit, so emit a correction."""
    _, key = await _key(client, ctx["admin"])
    tx = await _dispatch(client, ctx)
    await _age_seq(db_session, 1, 115)
    await _act(client, ctx, tx["id"], "void", {"reason": "late"})
    row = (await db_session.execute(select(ExportEvent).where(ExportEvent.seq == 1))).scalar_one()
    assert row.withdrawn is False
    await _age_seq(db_session, 1, 3600)
    assert [(e["event_type"], e["correction"]) for e in await _events(client, key)] == [("dispatch", False), ("receipt", True)]


async def test_correction_waits_behind_older_held_back_event_then_delivers_in_seq_order(client, ctx, db_session):
    _, key = await _key(client, ctx["admin"])
    await _dispatch(client, ctx, eq="eq1")  # seq 1, still held back
    tx2 = await _dispatch(client, ctx, eq="eq2")  # seq 2
    await _age_seq(db_session, 2, 3600)
    await _act(client, ctx, tx2["id"], "void", {"reason": "oops"})  # correction seq 3
    assert await _events(client, key) == []  # cursor blocked behind seq 1
    await _age_seq(db_session, 1, 3600)
    assert [e["seq"] for e in await _events(client, key)] == [1, 2, 3]


async def test_retried_normal_emit_is_rejected_but_reemit_after_void_is_allowed(client, ctx, db_session):
    from sqlalchemy.exc import IntegrityError

    from app.models.export import EVENT_TYPE_DISPATCH
    from app.services import export_service

    tx = await _dispatch(client, ctx)
    tx_id = uuid.UUID(tx["id"])
    with pytest.raises(IntegrityError):  # duplicate normal dispatch event (same generation)
        await export_service.record_event(
            db_session, transaction_id=tx_id, event_type=EVENT_TYPE_DISPATCH, event_at=datetime.now(timezone.utc)
        )
    await db_session.rollback()
