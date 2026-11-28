"""Owner Governance 2026-11-27 (D28): undo / void / change device / switch
action, their guards, the restore rules and the exclusion of voided rows.
SQLite; the migration is proved in test_d28_postgres.py."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from app.core.config import get_settings
from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.equipment import Equipment, EquipmentStatus
from app.models.transaction import CLOSE_REASON_REDISPATCH, BorrowTransaction, ReceiptOutcome, TransactionStatus
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY, Role, User
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import cached_password_hash
from tests.conftest import create_ward as _create_ward
from tests.conftest import login
from tests.test_pr25e_b2_sync_ops import dispatch_op

pytestmark = pytest.mark.asyncio

HN = "HN-3402/66"  # greppable marker, valid under the HN format rule
STD_OK = {"kind": "standard", "screen_ok": True, "charger_ok": True, "clamp_ok": False}


@pytest.fixture
def hn_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", Fernet.generate_key().decode())


async def _equipment(client, admin, n):
    resp = await client.post(
        "/api/v1/equipment", headers=admin, json={"asset_number": f"AST-D28-{n}", "equipment_name": "Pump"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
async def ctx(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    readonly = await _auth_headers(client, ROLE_READ_ONLY)
    role = (await db_session.execute(select(Role).where(Role.name == ROLE_EQUIPMENT_POOL_STAFF))).scalar_one()
    other = User(
        employee_code="STAFF002",
        full_name="Other Staff",
        email="staff2@mep-hospital-test.dev",
        password_hash=cached_password_hash("Password@123"),
        role_id=role.id,
    )
    db_session.add(other)
    await db_session.commit()
    other_headers = {"Authorization": f"Bearer {await login(client, 'STAFF002')}"}
    return {
        "admin": admin,
        "staff": staff,
        "other": other_headers,
        "ro": readonly,
        "ward_a": await _create_ward(client, admin, "W-D28A", "Ward Alpha"),
        "ward_b": await _create_ward(client, admin, "W-D28B", "Ward Beta"),
        "eq1": await _equipment(client, admin, 1),
        "eq2": await _equipment(client, admin, 2),
    }


async def _dispatch(client, headers, eq, ward, **extra):
    resp = await client.post(
        "/api/v1/borrow",
        headers=headers,
        json={"equipment_id": eq, "ward_id": ward, "dispatch_type": "on_demand", **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _receive(client, headers, tx_id, outcome="usable", **extra):
    resp = await client.post(
        f"/api/v1/return/{tx_id}", headers=headers, json={"receipt_outcome": outcome, **extra}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _post(client, headers, tx_id, action, body=None):
    return await client.post(f"/api/v1/transactions/{tx_id}/{action}", headers=headers, json=body)


async def _tx(db, tx_id):
    q = select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(str(tx_id))).execution_options(populate_existing=True)
    return (await db.execute(q)).scalar_one()


async def _eq_status(db, eq_id):
    q = select(Equipment).where(Equipment.id == uuid.UUID(eq_id)).execution_options(populate_existing=True)
    return (await db.execute(q)).scalar_one().status


async def _audits(db, action):
    q = select(AuditLog).where(AuditLog.action == action).execution_options(populate_existing=True)
    return list((await db.execute(q)).scalars().all())


async def _age(db, tx_id, **cols):
    """Rewrite timestamps (e.g. created_at) to simulate elapsed time."""
    await db.execute(update(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx_id)).values(**cols))
    await db.commit()


def _long_ago(**delta):
    return datetime.now(timezone.utc) - timedelta(**delta)


# ----------------------------------------------------------------- undo


async def test_undo_dispatch_within_window(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    resp = await _post(client, ctx["staff"], tx["id"], "undo")
    assert resp.status_code == 200, resp.text
    assert resp.json()["transaction"]["status"] == "voided"
    row = await _tx(db_session, tx["id"])
    assert row.status == TransactionStatus.VOIDED and row.void_reason == "เลิกทำ"
    assert row.voided_at is not None and row.voided_by_user_id == row.borrower_user_id
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.AVAILABLE_AT_POOL
    [audit] = await _audits(db_session, "transaction_undo")
    assert str(audit.entity_id) == tx["id"] and audit.after_data["reason"] == "เลิกทำ"
    assert audit.before_data["status"] == "open"


async def test_undo_receipt_reopens_transaction(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _receive(client, ctx["staff"], tx["id"], ward_contact_name="Somchai", receipt_checks=STD_OK, notes="n1")
    resp = await _post(client, ctx["staff"], tx["id"], "undo")
    assert resp.status_code == 200, resp.text
    row = await _tx(db_session, tx["id"])
    assert row.status == TransactionStatus.OPEN and row.returned_at is None
    assert row.condition_on_return is None and row.received_by_user_id is None
    assert row.receipt_contact_name is None and row.receipt_checks is None and row.receipt_saved_at is None
    assert row.notes is None  # the "[Return]" note went with the receipt
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.ISSUED_TO_WARD
    [audit] = await _audits(db_session, "transaction_undo")
    # The voided receipt stays in the audit before-image.
    assert audit.before_data["receipt_outcome"] == "usable" and audit.before_data["returned_at"]
    assert audit.before_data["receipt_contact_name"] == "Somchai"
    assert audit.before_data["receipt_checks"]["charger_ok"] is True


async def test_undo_window_expired_dispatch_and_receipt(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _age(db_session, tx["id"], created_at=_long_ago(seconds=125))
    resp = await _post(client, ctx["staff"], tx["id"], "undo")
    assert resp.status_code == 409 and resp.json()["code"] == "UNDO_WINDOW_EXPIRED"
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.OPEN

    # Just inside the 120 s dispatch window still works for another device.
    tx2 = await _dispatch(client, ctx["staff"], ctx["eq2"], ctx["ward_a"])
    await _age(db_session, tx2["id"], created_at=_long_ago(seconds=100))
    assert (await _post(client, ctx["staff"], tx2["id"], "undo")).status_code == 200

    # Receipt: 30 s.
    await _receive(client, ctx["staff"], tx["id"])
    await _age(db_session, tx["id"], receipt_saved_at=_long_ago(seconds=45))
    resp = await _post(client, ctx["staff"], tx["id"], "undo")
    assert resp.status_code == 409 and resp.json()["code"] == "UNDO_WINDOW_EXPIRED"
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.CLOSED
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.AVAILABLE_AT_POOL


async def test_undo_window_uses_save_time_not_business_time(client, ctx, db_session):
    """A backdated (legacy/offline) event time must not close the undo window."""
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _age(db_session, tx["id"], borrowed_at=_long_ago(days=3))
    assert (await _post(client, ctx["staff"], tx["id"], "undo")).status_code == 200
    # ... and undo is not limited by the shift (the event is 3 days old).
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.VOIDED


async def test_undo_legacy_receipt_without_save_time_is_refused(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _receive(client, ctx["staff"], tx["id"])
    await _age(db_session, tx["id"], receipt_saved_at=None)
    resp = await _post(client, ctx["staff"], tx["id"], "undo")
    assert resp.status_code == 409 and resp.json()["code"] == "UNDO_WINDOW_EXPIRED"


async def test_undo_only_by_the_saving_operator(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    for who in ("other", "admin", "ro"):
        resp = await _post(client, ctx[who], tx["id"], "undo")
        assert resp.status_code == 403, (who, resp.text)
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.OPEN
    assert not await _audits(db_session, "transaction_undo")


# ----------------------------------------------------------------- void


async def test_void_requires_reason(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    for body in ({}, {"reason": ""}, {"reason": "   "}):
        resp = await _post(client, ctx["staff"], tx["id"], "void", body)
        assert resp.status_code == 422, resp.text
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.OPEN


async def test_void_dispatch_restores_prior_state(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    row = await _tx(db_session, tx["id"])
    assert row.prior_equipment_status == "available_at_pool" and row.closed_by_redispatch_transaction_id is None
    resp = await _post(client, ctx["staff"], tx["id"], "void", {"reason": "wrong ward typed"})
    assert resp.status_code == 200, resp.text
    row = await _tx(db_session, tx["id"])
    assert row.status == TransactionStatus.VOIDED and row.void_reason == "wrong ward typed"
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.AVAILABLE_AT_POOL
    [audit] = await _audits(db_session, "transaction_void")
    assert audit.after_data["reason"] == "wrong ward typed"
    assert audit.after_data["equipment_status_restored_to"] == "available_at_pool"


async def test_void_dispatch_of_defective_device_restores_defective(client, ctx, db_session):
    await client.post(f"/api/v1/equipment/{ctx['eq1']}/status", headers=ctx["admin"], json={"status": "unavailable_defective"})
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"], acknowledge_status_warning=True)
    assert (await _tx(db_session, tx["id"])).prior_equipment_status == "unavailable_defective"
    assert (await _post(client, ctx["staff"], tx["id"], "void", {"reason": "x"})).status_code == 200
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.UNAVAILABLE_DEFECTIVE


async def test_void_redispatch_reopens_the_closed_transaction(client, ctx, db_session):
    first = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    second = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_b"], acknowledge_status_warning=True)
    row2 = await _tx(db_session, second["id"])
    assert str(row2.closed_by_redispatch_transaction_id) == first["id"]
    assert row2.prior_equipment_status == "issued_to_ward"
    assert (await _tx(db_session, first["id"])).status == TransactionStatus.CLOSED

    resp = await _post(client, ctx["staff"], second["id"], "void", {"reason": "dispatched twice"})
    assert resp.status_code == 200, resp.text
    row1 = await _tx(db_session, first["id"])
    assert row1.status == TransactionStatus.OPEN and row1.close_reason is None
    assert (await _tx(db_session, second["id"])).status == TransactionStatus.VOIDED
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.ISSUED_TO_WARD
    # The reopened transaction is again the device's latest and can be received.
    await _receive(client, ctx["staff"], first["id"])
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.AVAILABLE_AT_POOL


async def test_void_legacy_dispatch_without_stored_prior_state_goes_to_pool(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _age(db_session, tx["id"], prior_equipment_status=None, closed_by_redispatch_transaction_id=None)
    assert (await _post(client, ctx["admin"], tx["id"], "void", {"reason": "legacy"})).status_code == 200
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.AVAILABLE_AT_POOL


@pytest.mark.parametrize("outcome, expected", [("usable", EquipmentStatus.AVAILABLE_AT_POOL), ("defective", EquipmentStatus.UNAVAILABLE_DEFECTIVE)])
async def test_void_receipt_reopens_and_device_back_to_ward(client, ctx, db_session, outcome, expected):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _receive(client, ctx["staff"], tx["id"], outcome)
    assert await _eq_status(db_session, ctx["eq1"]) == expected
    resp = await _post(client, ctx["staff"], tx["id"], "void", {"reason": "not received"})
    assert resp.status_code == 200, resp.text
    row = await _tx(db_session, tx["id"])
    assert row.status == TransactionStatus.OPEN and row.returned_at is None and row.condition_on_return is None
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.ISSUED_TO_WARD
    [audit] = await _audits(db_session, "transaction_void")
    assert audit.before_data["receipt_outcome"] == outcome
    # Receivable again.
    await _receive(client, ctx["staff"], tx["id"])


# ----------------------------------------------------------------- guards


async def test_only_the_latest_transaction_can_be_corrected(client, ctx, db_session):
    first = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _receive(client, ctx["staff"], first["id"])
    second = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_b"])
    for body_action in ("void",):
        resp = await _post(client, ctx["admin"], first["id"], body_action, {"reason": "r"})
        assert resp.status_code == 409 and resp.json()["code"] == "CORRECTION_NOT_LATEST"
    # Closed by re-dispatch (no receipt) is superseded too.
    redisp = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"], acknowledge_status_warning=True)
    resp = await _post(client, ctx["admin"], second["id"], "void", {"reason": "r"})
    assert resp.status_code == 409 and resp.json()["code"] == "CORRECTION_NOT_LATEST"
    assert (await _post(client, ctx["admin"], redisp["id"], "void", {"reason": "r"})).status_code == 200
    # Once the latest is voided the previous one (reopened) is latest again.
    assert (await _post(client, ctx["admin"], second["id"], "void", {"reason": "r"})).status_code == 200


async def test_state_guard_refuses_when_device_state_changed(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _receive(client, ctx["staff"], tx["id"], "usable")
    resp = await client.post(
        f"/api/v1/equipment/{ctx['eq1']}/status", headers=ctx["admin"], json={"status": "unavailable_defective"}
    )
    assert resp.status_code == 200, resp.text
    resp = await _post(client, ctx["admin"], tx["id"], "void", {"reason": "r"})
    assert resp.status_code == 409 and resp.json()["code"] == "CORRECTION_STATE_CHANGED"
    row = await _tx(db_session, tx["id"])
    assert row.status == TransactionStatus.CLOSED and row.returned_at is not None
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.UNAVAILABLE_DEFECTIVE
    assert not await _audits(db_session, "transaction_void")
    # Undo follows the same guard.
    assert (await _post(client, ctx["staff"], tx["id"], "undo")).status_code == 409


async def test_permission_matrix(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    body = {"reason": "r"}
    assert (await _post(client, ctx["ro"], tx["id"], "void", body)).status_code == 403
    resp = await _post(client, ctx["other"], tx["id"], "void", body)  # someone else's entry
    assert resp.status_code == 403 and resp.json()["code"] == "CORRECTION_NOT_PERMITTED"
    # Own entry but from an earlier shift/day: staff refused, administrator allowed.
    await _age(db_session, tx["id"], borrowed_at=_long_ago(days=2))
    resp = await _post(client, ctx["staff"], tx["id"], "void", body)
    assert resp.status_code == 403 and resp.json()["code"] == "CORRECTION_NOT_PERMITTED"
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.OPEN
    assert (await _post(client, ctx["admin"], tx["id"], "void", body)).status_code == 200
    assert len(await _audits(db_session, "transaction_void")) == 1


async def test_staff_may_correct_own_entry_in_same_shift(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    assert (await _post(client, ctx["staff"], tx["id"], "void", {"reason": "r"})).status_code == 200


async def test_read_only_denied_every_action(client, ctx):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    bodies = {
        "undo": None,
        "void": {"reason": "r"},
        "change-device": {"reason": "r", "equipment_id": ctx["eq2"]},
        "switch-action": {"reason": "r", "ward_id": ctx["ward_b"]},
    }
    for action, body in bodies.items():
        assert (await _post(client, ctx["ro"], tx["id"], action, body)).status_code == 403, action


# ----------------------------------------------------------------- change device


async def test_change_device_dispatch_keeps_every_field_and_moves_hn(client, ctx, db_session, hn_key):
    tx = await _dispatch(
        client, ctx["staff"], ctx["eq1"], ctx["ward_a"], hn=HN, ward_contact_name="Nurse Ploy", dispatch_checks=STD_OK,
        notes="urgent",
    )
    await _age(db_session, tx["id"], dispatch_keyer_label="BME-Lek", borrowed_at=_long_ago(minutes=7))
    old = await _tx(db_session, tx["id"])
    old_borrowed_at, old_operator = old.borrowed_at, old.borrower_user_id

    resp = await _post(client, ctx["staff"], tx["id"], "change-device", {"reason": "scanned wrong pump", "equipment_id": ctx["eq2"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transaction"]["status"] == "voided" and body["new_transaction"]["status"] == "open"
    assert HN not in resp.text

    voided = await _tx(db_session, tx["id"])
    new = await _tx(db_session, body["new_transaction"]["id"])
    assert voided.status == TransactionStatus.VOIDED and voided.corrected_by_transaction_id == new.id
    assert voided.void_reason == "scanned wrong pump" and voided.voided_by_user_id is not None
    # Same time, ward, contact, keyer label, checks, operator, notes.
    assert new.borrowed_at == old_borrowed_at and str(new.ward_id) == ctx["ward_a"]
    assert new.dispatch_contact_name == "Nurse Ploy" and new.dispatch_keyer_label == "BME-Lek"
    assert new.dispatch_checks["charger_ok"] is True and new.dispatch_checks["clamp_ok"] is False
    assert new.borrower_user_id == old_operator and new.notes == "urgent"
    assert str(new.equipment_id) == ctx["eq2"]
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.AVAILABLE_AT_POOL
    assert await _eq_status(db_session, ctx["eq2"]) == EquipmentStatus.ISSUED_TO_WARD
    # HN moved server-side: cleared on the voided row, present on the new one.
    assert voided.has_hn is False and new.has_hn is True
    assert voided.hn_recorded is False and new.hn_recorded is True  # D31
    cipher = (await db_session.execute(select(BorrowTransaction.hn_ciphertext).where(BorrowTransaction.id == voided.id))).scalar_one()
    assert cipher is None
    reveal = await client.post(f"/api/v1/transactions/{new.id}/reveal-hn", headers=ctx["staff"])
    assert reveal.status_code == 200 and reveal.json()["hn"] == HN
    # No HN (or ciphertext) in any audit row.
    for row in (await db_session.execute(select(AuditLog).execution_options(populate_existing=True))).scalars().all():
        dumped = json.dumps([row.before_data, row.after_data], default=str)
        assert HN not in dumped and "gAAAA" not in dumped, row.action
    [audit] = await _audits(db_session, "transaction_change_device")
    assert audit.after_data["new_transaction_id"] == str(new.id) and audit.after_data["hn_moved"] is True


async def test_change_device_is_atomic_when_the_new_device_fails(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    # eq2 is out at a ward already: normal D8 rules demand an acknowledgement.
    other = await _dispatch(client, ctx["staff"], ctx["eq2"], ctx["ward_b"])
    resp = await _post(client, ctx["staff"], tx["id"], "change-device", {"reason": "r", "equipment_id": ctx["eq2"]})
    assert resp.status_code == 409 and resp.json()["code"] == "DISPATCH_STATUS_WARNING"
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.OPEN
    assert (await _tx(db_session, other["id"])).status == TransactionStatus.OPEN
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.ISSUED_TO_WARD
    assert not await _audits(db_session, "transaction_change_device")
    # Same device is rejected too.
    resp = await _post(client, ctx["staff"], tx["id"], "change-device", {"reason": "r", "equipment_id": ctx["eq1"]})
    assert resp.status_code == 400
    # With the acknowledgement it follows D8 (closes eq2's open transaction).
    resp = await _post(
        client, ctx["staff"], tx["id"], "change-device",
        {"reason": "r", "equipment_id": ctx["eq2"], "acknowledge_status_warning": True},
    )
    assert resp.status_code == 200, resp.text
    assert (await _tx(db_session, other["id"])).status == TransactionStatus.CLOSED


async def test_change_device_receipt(client, ctx, db_session):
    a = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    b = await _dispatch(client, ctx["staff"], ctx["eq2"], ctx["ward_a"])
    await _receive(client, ctx["staff"], a["id"], "defective", ward_contact_name="Nurse Ploy")
    old_returned = (await _tx(db_session, a["id"])).returned_at
    resp = await _post(client, ctx["staff"], a["id"], "change-device", {"reason": "wrong pump", "equipment_id": ctx["eq2"]})
    assert resp.status_code == 200, resp.text
    # The wrong device's receipt is voided (reopened); the right device is received at the same time.
    assert (await _tx(db_session, a["id"])).status == TransactionStatus.OPEN
    new = await _tx(db_session, b["id"])
    assert new.status == TransactionStatus.CLOSED and new.returned_at == old_returned
    assert new.condition_on_return == "defective" and new.receipt_contact_name == "Nurse Ploy"
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.ISSUED_TO_WARD
    assert await _eq_status(db_session, ctx["eq2"]) == EquipmentStatus.UNAVAILABLE_DEFECTIVE


# ----------------------------------------------------------------- switch action


async def test_switch_dispatch_to_receipt(client, ctx, db_session):
    first = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    wrong = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_b"], acknowledge_status_warning=True)
    wrong_at = (await _tx(db_session, wrong["id"])).borrowed_at
    resp = await _post(client, ctx["staff"], wrong["id"], "switch-action", {"reason": "it was a return", "outcome": "defective"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transaction"]["status"] == "voided" and body["new_transaction"]["id"] == first["id"]
    voided = await _tx(db_session, wrong["id"])
    received = await _tx(db_session, first["id"])
    assert voided.corrected_by_transaction_id == received.id
    assert received.status == TransactionStatus.CLOSED and received.close_reason is None
    assert received.returned_at == wrong_at and received.condition_on_return == "defective"
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.UNAVAILABLE_DEFECTIVE
    assert len(await _audits(db_session, "transaction_switch_action")) == 1


async def test_switch_dispatch_to_receipt_needs_a_prior_open_transaction(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    resp = await _post(client, ctx["staff"], tx["id"], "switch-action", {"reason": "r"})
    assert resp.status_code == 409 and resp.json()["code"] == "SWITCH_ACTION_NOT_AVAILABLE"
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.OPEN
    assert not await _audits(db_session, "transaction_switch_action")


async def test_switch_receipt_to_dispatch(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _receive(client, ctx["staff"], tx["id"], ward_contact_name="Nurse Ploy")
    received_at = (await _tx(db_session, tx["id"])).returned_at
    resp = await _post(client, ctx["staff"], tx["id"], "switch-action", {"reason": "it was a dispatch"})
    assert resp.status_code == 400  # a ward is required for this direction
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.CLOSED
    resp = await _post(client, ctx["staff"], tx["id"], "switch-action", {"reason": "it was a dispatch", "ward_id": ctx["ward_b"]})
    assert resp.status_code == 200, resp.text
    new = await _tx(db_session, resp.json()["new_transaction"]["id"])
    assert new.status == TransactionStatus.OPEN and str(new.ward_id) == ctx["ward_b"]
    assert new.borrowed_at == received_at and new.dispatch_contact_name == "Nurse Ploy"
    assert str(new.closed_by_redispatch_transaction_id) == tx["id"]
    old = await _tx(db_session, tx["id"])  # reopened, then closed by D8 re-dispatch
    assert old.status == TransactionStatus.CLOSED and old.close_reason == CLOSE_REASON_REDISPATCH
    assert old.returned_at is None
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.ISSUED_TO_WARD


# ----------------------------------------------------------------- exclusion


async def test_voided_rows_are_excluded_from_reports_standby_monitor_dashboard(client, ctx, db_session):
    from app.services import daily_report_service, dashboard_service, report_query_service, standby_summary_service

    keep = await _dispatch(client, ctx["staff"], ctx["eq2"], ctx["ward_a"])
    gone = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _receive(client, ctx["staff"], gone["id"])
    # Void the receipt then the dispatch (both rows leave every count).
    assert (await _post(client, ctx["staff"], gone["id"], "void", {"reason": "r"})).status_code == 200
    assert (await _post(client, ctx["staff"], gone["id"], "void", {"reason": "r"})).status_code == 200
    assert (await _tx(db_session, gone["id"])).status == TransactionStatus.VOIDED

    # transactions list/search counts
    listing = (await client.get("/api/v1/transactions", headers=ctx["staff"])).json()
    assert listing["total"] == 1 and [i["id"] for i in listing["items"]] == [keep["id"]]
    assert (await client.get("/api/v1/transactions", headers=ctx["staff"], params={"status": "open"})).json()["total"] == 1
    # report queries
    _, _, issue_total = await report_query_service.search_issue_report(db_session)
    _, _, receive_total = await report_query_service.search_receive_report(db_session)
    assert (issue_total, receive_total) == (1, 0)
    # monitor
    for kind in ("dispatch", "receipt"):
        mon = (await client.get("/api/v1/monitor/events", headers=ctx["staff"], params={"kind": kind})).json()
        assert gone["id"] not in json.dumps(mon)
    assert (await client.get("/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "dispatch"})).json()["total"] == 1
    # daily report events
    start = datetime.now(timezone.utc) - timedelta(days=2)
    events = await daily_report_service._load_events(db_session, start, datetime.now(timezone.utc) + timedelta(days=1))
    assert {str(e.transaction_id) for e in events} == {keep["id"]}
    # standby summary: only the live open dispatch is open at the cut-off
    eq_ids = {uuid.UUID(ctx["eq1"]), uuid.UUID(ctx["eq2"])}
    open_txs = await standby_summary_service._open_at_cutoff(db_session, eq_ids, datetime.now(timezone.utc))
    assert [str(t.id) for t in open_txs] == [keep["id"]]
    # dashboard
    trend = await dashboard_service.get_borrow_trend(db_session, days=2)
    assert sum(r["count"] for r in trend) == 1
    top = await dashboard_service.get_top_borrowed(db_session)
    assert [t["equipment_id"] for t in top] == [ctx["eq2"]]
    # CSV report export
    csv_resp = await client.get("/api/v1/reports/export", headers=ctx["staff"], params={"format": "csv"})
    assert csv_resp.status_code == 200
    assert csv_resp.text.count("TX-") == 1


async def test_equipment_history_lists_voided_rows_marked_voided(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    assert (await _post(client, ctx["staff"], tx["id"], "void", {"reason": "slip"})).status_code == 200
    hist = (await client.get("/api/v1/transactions", headers=ctx["staff"], params={"equipment_id": ctx["eq1"]})).json()
    assert [(i["id"], i["status"], i["void_reason"]) for i in hist["items"]] == [(tx["id"], "voided", "slip")]
    assert (await client.get("/api/v1/transactions", headers=ctx["staff"], params={"status": "voided"})).json()["total"] == 1


async def test_voided_transaction_cannot_be_received_or_corrected_again(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _post(client, ctx["staff"], tx["id"], "void", {"reason": "r"})
    resp = await client.post(f"/api/v1/return/{tx['id']}", headers=ctx["staff"], json={"receipt_outcome": "usable"})
    assert resp.status_code == 409 and resp.json()["code"] == "TRANSACTION_VOIDED"
    resp = await _post(client, ctx["admin"], tx["id"], "void", {"reason": "r"})
    assert resp.status_code == 409 and resp.json()["code"] == "TRANSACTION_VOIDED"
    # A new dispatch of the device works (a voided row is neither open nor in the way).
    await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])


# ----------------------------------------------------------------- legacy sync ledger


async def test_voided_sync_dispatch_ledger_entry_stays_applied(client, ctx, db_session):
    me = (await client.get("/api/v1/auth/me", headers=ctx["staff"])).json()["id"]
    op = dispatch_op(me, ctx["eq1"], ctx["ward_a"])
    res = await client.post("/api/v1/sync/operations", headers=ctx["staff"], json={"operations": [op]})
    assert res.json()["results"][0]["result"] == "applied"
    assert (await _post(client, ctx["admin"], op["op_id"], "void", {"reason": "sheet row was wrong"})).status_code == 200

    db_session.expire_all()
    ledger = (await db_session.execute(select(ClientOperation))).scalar_one()
    assert ledger.status == "applied" and str(ledger.transaction_id) == op["op_id"]
    # Replaying the same operation does not re-apply it.
    res = await client.post("/api/v1/sync/operations", headers=ctx["staff"], json={"operations": [op]})
    assert res.json()["results"][0]["result"] == "duplicate"
    count = len((await db_session.execute(select(BorrowTransaction))).scalars().all())
    assert count == 1
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.AVAILABLE_AT_POOL


# ----------------------------------------------------------------- review fixes


@pytest.mark.parametrize("action, body", [("void", {"reason": "legacy"}), ("undo", None)])
async def test_void_or_undo_legacy_redispatch_reopens_predecessor(client, ctx, db_session, action, body):
    first = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    second = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_b"], acknowledge_status_warning=True)
    await _age(db_session, second["id"], prior_equipment_status=None, closed_by_redispatch_transaction_id=None)
    resp = await _post(client, ctx["staff"], second["id"], action, body)
    assert resp.status_code == 200, resp.text
    assert (await _tx(db_session, first["id"])).status == TransactionStatus.OPEN
    assert (await _tx(db_session, second["id"])).status == TransactionStatus.VOIDED
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.ISSUED_TO_WARD


async def test_void_issued_prior_with_unidentifiable_predecessor_is_refused(client, ctx, db_session):
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    await _age(db_session, tx["id"], prior_equipment_status="issued_to_ward", closed_by_redispatch_transaction_id=None)
    resp = await _post(client, ctx["admin"], tx["id"], "void", {"reason": "r"})
    assert resp.status_code == 409, resp.text
    assert (await _tx(db_session, tx["id"])).status == TransactionStatus.OPEN
    assert await _eq_status(db_session, ctx["eq1"]) == EquipmentStatus.ISSUED_TO_WARD
    assert not await _audits(db_session, "transaction_void")


async def test_return_note_split_and_change_device_carries_receipt_note(client, ctx, db_session):
    a = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"], notes="see [Return] policy")
    b = await _dispatch(client, ctx["staff"], ctx["eq2"], ctx["ward_a"])
    await _receive(client, ctx["staff"], a["id"], notes="cracked case")
    assert (await _tx(db_session, a["id"])).notes == "see [Return] policy\n[Return] cracked case"
    resp = await _post(client, ctx["staff"], a["id"], "change-device", {"reason": "wrong pump", "equipment_id": ctx["eq2"]})
    assert resp.status_code == 200, resp.text
    assert (await _tx(db_session, a["id"])).notes == "see [Return] policy"  # dispatch note intact
    assert "cracked case" in (await _tx(db_session, b["id"])).notes
    c = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"], notes="x [Return] y", acknowledge_status_warning=True)
    await _receive(client, ctx["staff"], c["id"])
    assert (await _post(client, ctx["staff"], c["id"], "void", {"reason": "r"})).status_code == 200
    assert (await _tx(db_session, c["id"])).notes == "x [Return] y"


async def test_legacy_sync_receipt_is_not_undoable(client, ctx, db_session):
    from app.services import borrow_service
    from app.services.legacy_sheet_sync import runner

    assert runner.USER_AGENT == borrow_service.LEGACY_SYNC_USER_AGENT
    tx = await _dispatch(client, ctx["staff"], ctx["eq1"], ctx["ward_a"])
    staff_id = (await _tx(db_session, tx["id"])).borrower_user_id
    await borrow_service.return_equipment(
        db_session, transaction_id=uuid.UUID(tx["id"]), receipt_outcome=ReceiptOutcome.USABLE,
        notes=None, received_by_user_id=staff_id, ip_address=None, user_agent=runner.USER_AGENT,
    )
    assert (await _tx(db_session, tx["id"])).receipt_saved_at is None
    resp = await _post(client, ctx["staff"], tx["id"], "undo")
    assert resp.status_code == 409 and resp.json()["code"] == "UNDO_WINDOW_EXPIRED"
