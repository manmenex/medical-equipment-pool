import uuid

import pytest
from sqlalchemy import select

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


# ---------------------------------------------------------------------------
# Regression: PATCH /equipment/{id} and POST /equipment/{id}/status used to
# return a spurious 500 (MissingGreenlet) after the mutation and its audit
# row had already committed successfully — see app/models/equipment.py's
# Equipment.__mapper_args__ (eager_defaults=True) for the fix. These tests
# use the plain `client` fixture (default ASGITransport, application
# exceptions NOT suppressed) so a regression fails loudly as an error, not
# a quietly-tolerated 500.
# ---------------------------------------------------------------------------


async def test_update_equipment_returns_200_with_updated_values(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "FIX-UPD-0001", "equipment_name": "Old Name"},
    )
    assert create_resp.status_code == 201, create_resp.text
    equipment_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/equipment/{equipment_id}",
        headers=headers,
        json={"equipment_name": "New Name"},
    )
    assert update_resp.status_code == 200, update_resp.text
    body = update_resp.json()
    assert body["equipment_name"] == "New Name"
    assert body["id"] == equipment_id
    # updated_at must be present and populated without a lazy load.
    assert body["updated_at"]


async def test_status_change_returns_200_with_new_status(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "FIX-STATUS-0001", "equipment_name": "Wheelchair"},
    )
    assert create_resp.status_code == 201, create_resp.text
    equipment_id = create_resp.json()["id"]

    status_resp = await client.post(
        f"/api/v1/equipment/{equipment_id}/status",
        headers=headers,
        json={"status": "repair", "reason": "Needs a new wheel"},
    )
    assert status_resp.status_code == 200, status_resp.text
    body = status_resp.json()
    assert body["status"] == "repair"
    assert body["id"] == equipment_id
    assert body["updated_at"]


async def test_update_equipment_persists_exactly_once_via_fresh_session(client, seeded_users, db_session):
    from app.models.equipment import Equipment

    headers = await _auth_headers(client, seeded_users, "admin")
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "FIX-UPD-0002", "equipment_name": "Old Name"},
    )
    equipment_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/equipment/{equipment_id}",
        headers=headers,
        json={"equipment_name": "New Name"},
    )
    assert update_resp.status_code == 200, update_resp.text

    result = await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
    rows = result.scalars().all()
    assert len(rows) == 1, "exactly one equipment row must exist — no duplicate mutation"
    assert rows[0].equipment_name == "New Name"


async def test_update_equipment_produces_exactly_one_audit_row(client, seeded_users, db_session):
    from app.models.audit import AuditLog

    headers = await _auth_headers(client, seeded_users, "admin")
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "FIX-UPD-0003", "equipment_name": "Old Name"},
    )
    equipment_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/equipment/{equipment_id}",
        headers=headers,
        json={"equipment_name": "New Name"},
    )
    assert update_resp.status_code == 200, update_resp.text

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "update",
            AuditLog.entity_type == "equipment",
            AuditLog.entity_id == uuid.UUID(equipment_id),
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1, "exactly one audit row must exist for the update — no duplicate audit event"


async def test_status_change_produces_exactly_one_audit_row(client, seeded_users, db_session):
    from app.models.audit import AuditLog

    headers = await _auth_headers(client, seeded_users, "admin")
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "FIX-STATUS-0002", "equipment_name": "Wheelchair"},
    )
    equipment_id = create_resp.json()["id"]

    status_resp = await client.post(
        f"/api/v1/equipment/{equipment_id}/status",
        headers=headers,
        json={"status": "repair", "reason": "Needs a new wheel"},
    )
    assert status_resp.status_code == 200, status_resp.text

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "status_change",
            AuditLog.entity_type == "equipment",
            AuditLog.entity_id == uuid.UUID(equipment_id),
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1, "exactly one audit row must exist for the status change"


async def test_ordinary_request_still_succeeds_after_update_and_status_change(client, seeded_users):
    """Proves the fix didn't leave the session/connection unusable — an
    unrelated, completely ordinary follow-up request still works."""
    headers = await _auth_headers(client, seeded_users, "admin")
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "FIX-FOLLOWUP-0001", "equipment_name": "Old Name"},
    )
    equipment_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/equipment/{equipment_id}",
        headers=headers,
        json={"equipment_name": "New Name"},
    )
    assert update_resp.status_code == 200, update_resp.text

    status_resp = await client.post(
        f"/api/v1/equipment/{equipment_id}/status",
        headers=headers,
        json={"status": "repair"},
    )
    assert status_resp.status_code == 200, status_resp.text

    follow_up = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "FIX-FOLLOWUP-0002", "equipment_name": "Another Item"},
    )
    assert follow_up.status_code == 201, follow_up.text
