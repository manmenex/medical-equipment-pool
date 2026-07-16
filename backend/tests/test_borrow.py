import pytest

from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _auth_headers(client, role="admin"):
    identifier = f"{role.upper()}001"
    token = await login(client, identifier)
    return {"Authorization": f"Bearer {token}"}


async def _create_equipment(client, headers, asset_number="AST-1001", name="Infusion Pump"):
    resp = await client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": asset_number, "equipment_name": name}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_borrow_then_return_flow(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    nurse_headers = await _auth_headers(client, "ward_nurse")

    equipment = await _create_equipment(client, admin_headers)

    borrow_resp = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Nurse Somying"},
    )
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx = borrow_resp.json()
    assert tx["equipment"]["status"] == "borrowed"

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp.json()["status"] == "borrowed"

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"condition": "available"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert return_resp.json()["status"] == "returned"

    check_resp2 = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp2.json()["status"] == "available"


async def test_cannot_borrow_unavailable_equipment(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    nurse_headers = await _auth_headers(client, "ward_nurse")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-1002")

    first = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Nurse A"},
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Nurse B"},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "EQUIPMENT_NOT_AVAILABLE"


async def test_unique_active_borrow_db_constraint(db_session):
    """The DB-level partial unique index (idx_tx_one_active_borrow) is the real guard
    against a double-borrow race — two concurrent requests both passing the
    Available check would otherwise both insert a 'borrowed' row. This exercises
    that constraint directly at the model layer, independent of HTTP concurrency
    (which SQLite's single test connection can't safely simulate)."""
    from sqlalchemy.exc import IntegrityError

    from app.models.equipment import Equipment
    from app.models.transaction import BorrowTransaction
    from app.services.qr_service import build_qr_value

    equipment = Equipment(
        asset_number="AST-1003", equipment_name="Ventilator", qr_code_value=build_qr_value("AST-1003")
    )
    db_session.add(equipment)
    await db_session.flush()

    db_session.add(
        BorrowTransaction(transaction_no="TX-TEST-0001", equipment_id=equipment.id, borrower_name="Nurse A")
    )
    await db_session.flush()

    db_session.add(
        BorrowTransaction(transaction_no="TX-TEST-0002", equipment_id=equipment.id, borrower_name="Nurse B")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_viewer_cannot_borrow(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    viewer_headers = await _auth_headers(client, "viewer")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-1004")

    resp = await client.post(
        "/api/v1/borrow",
        headers=viewer_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Someone"},
    )
    assert resp.status_code == 403
