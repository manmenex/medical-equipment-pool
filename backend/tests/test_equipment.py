import pytest

from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _auth_headers(client, seeded_users, role="admin"):
    identifier = f"{role.upper()}001"
    token = await login(client, identifier)
    return {"Authorization": f"Bearer {token}"}


async def test_create_and_get_equipment(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-0001", "equipment_name": "Infusion Pump"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "available"
    assert body["qr_code_value"] == "MEP:AST-0001"

    resp2 = await client.get(f"/api/v1/equipment/{body['id']}", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["asset_number"] == "AST-0001"


async def test_viewer_cannot_create_equipment(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "viewer")
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-0002", "equipment_name": "ECG"},
    )
    assert resp.status_code == 403


async def test_search_equipment_by_name(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-0003", "equipment_name": "Ventilator Pro"},
    )
    resp = await client.get("/api/v1/equipment", headers=headers, params={"q": "Ventilator"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(i["asset_number"] == "AST-0003" for i in items)


async def test_resolve_by_qr(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-0004", "equipment_name": "Defibrillator"},
    )
    resp = await client.get("/api/v1/equipment/by-qr/MEP:AST-0004", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["asset_number"] == "AST-0004"


async def test_get_by_qr_not_found(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    resp = await client.get("/api/v1/equipment/by-qr/MEP:NOPE", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "EQUIPMENT_NOT_FOUND"
