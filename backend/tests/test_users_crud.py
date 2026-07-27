import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.user import ROLE_ADMINISTRATOR, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Roadmap PR14A (Backend Audit 4.1): PATCH nullable-field correctness for
# users -- full_name and is_active are `nullable=False` in the database
# (app.models.user.User) and must reject an explicit null rather than
# silently discard it; phone is nullable and must actually clear.
# ---------------------------------------------------------------------------


async def _create_user(client, headers, employee_code: str) -> dict:
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "employee_code": employee_code,
            "full_name": "Original Name",
            "email": f"{employee_code.lower()}@mep-hospital-test.dev",
            "password": "Password@123",
            "role_name": ROLE_READ_ONLY,
            "phone": "0800000000",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_update_user_can_clear_nullable_phone(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_user(client, headers, "PR14A-USR-0001")

    resp = await client.patch(f"/api/v1/users/{created['id']}", headers=headers, json={"phone": None})
    assert resp.status_code == 200, resp.text


async def test_update_user_rejects_null_full_name_with_no_audit_event(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_user(client, headers, "PR14A-USR-0002")

    resp = await client.patch(
        f"/api/v1/users/{created['id']}", headers=headers, json={"full_name": None}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"

    list_resp = await client.get("/api/v1/users", headers=headers)
    target = next(u for u in list_resp.json() if u["id"] == created["id"])
    assert target["full_name"] == "Original Name"

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "update",
            AuditLog.entity_type == "user",
        )
    )
    rows = [r for r in result.scalars().all() if str(r.entity_id) == created["id"]]
    assert rows == [], "a rejected request must produce no audit event"


async def test_update_user_rejects_null_is_active(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_user(client, headers, "PR14A-USR-0003")

    resp = await client.patch(
        f"/api/v1/users/{created['id']}", headers=headers, json={"is_active": None}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_update_user_still_accepts_a_nonnull_full_name_change(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_user(client, headers, "PR14A-USR-0004")

    resp = await client.patch(
        f"/api/v1/users/{created['id']}", headers=headers, json={"full_name": "New Name"}
    )
    assert resp.status_code == 200, resp.text
