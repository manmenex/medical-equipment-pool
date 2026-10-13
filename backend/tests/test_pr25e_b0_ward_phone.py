"""Roadmap PR25E slice B0: optional contact phone on wards and departments.

Create-time only: no ward/department update endpoint exists (and none is added
here), so editing an existing record's phone is a flagged prerequisite.
"""
import pytest

from app.models.user import ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers

VALID = ["02-123-4567", "+66 2 123 4567", "1234", "02 123 4567 ext 12", "02-123-4567 x123", "  081-234-5678  "]
INVALID = ["abc", "12", "++66123", "02-123-4567 (home)", "1" * 21, "02-123-4567; DROP", "ext 123", "12-"]


@pytest.mark.parametrize("path", ["/api/v1/wards", "/api/v1/departments"])
async def test_phone_set_on_create_and_read_back(client, seeded_users, path):
    h = await auth_headers(client)
    resp = await client.post(path, headers=h, json={"code": "P1", "name": "N", "phone": " 02-123-4567 x12 "})
    assert resp.status_code == 201, resp.text
    assert resp.json()["phone"] == "02-123-4567 x12"
    listed = (await client.get(path, headers=h)).json()
    assert [r["phone"] for r in listed] == ["02-123-4567 x12"]


@pytest.mark.parametrize("path", ["/api/v1/wards", "/api/v1/departments"])
async def test_phone_optional_and_blank_is_null(client, seeded_users, path):
    h = await auth_headers(client)
    a = await client.post(path, headers=h, json={"code": "P1", "name": "N"})
    b = await client.post(path, headers=h, json={"code": "P2", "name": "N", "phone": "   "})
    assert a.status_code == b.status_code == 201
    assert a.json()["phone"] is None and b.json()["phone"] is None


@pytest.mark.parametrize("path", ["/api/v1/wards", "/api/v1/departments"])
@pytest.mark.parametrize("phone", VALID)
async def test_phone_valid_formats(client, seeded_users, path, phone):
    h = await auth_headers(client)
    resp = await client.post(path, headers=h, json={"code": "P1", "name": "N", "phone": phone})
    assert resp.status_code == 201, resp.text
    assert resp.json()["phone"] == phone.strip()


@pytest.mark.parametrize("path", ["/api/v1/wards", "/api/v1/departments"])
@pytest.mark.parametrize("phone", INVALID)
async def test_phone_invalid_formats_rejected(client, seeded_users, path, phone):
    h = await auth_headers(client)
    resp = await client.post(path, headers=h, json={"code": "P1", "name": "N", "phone": phone})
    assert resp.status_code == 422, resp.text
    assert (await client.get(path, headers=h)).json() == []


@pytest.mark.parametrize("path", ["/api/v1/wards", "/api/v1/departments"])
@pytest.mark.parametrize("role", [ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY])
async def test_only_administrator_can_set_phone(client, seeded_users, path, role):
    h = await auth_headers(client, role)
    resp = await client.post(path, headers=h, json={"code": "P1", "name": "N", "phone": "1234"})
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("path", ["/api/v1/wards", "/api/v1/departments"])
@pytest.mark.parametrize("role", [ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY])
async def test_non_admin_roles_can_read_phone(client, seeded_users, path, role):
    admin = await auth_headers(client)
    await client.post(path, headers=admin, json={"code": "P1", "name": "N", "phone": "1234"})
    resp = await client.get(path, headers=await auth_headers(client, role))
    assert resp.status_code == 200
    assert resp.json()[0]["phone"] == "1234"


async def test_ward_audit_records_phone(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog

    h = await auth_headers(client)
    await client.post("/api/v1/wards", headers=h, json={"code": "P1", "name": "N", "phone": "1234"})
    rows = (await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "ward"))).scalars().all()
    assert rows and rows[0].after_data["phone"] == "1234"


async def test_no_update_endpoint_exists(client, seeded_users):
    """Documents the flagged prerequisite: PUT/PATCH on a ward is not routed."""
    h = await auth_headers(client)
    ward = (await client.post("/api/v1/wards", headers=h, json={"code": "P1", "name": "N"})).json()
    for method in ("put", "patch"):
        resp = await getattr(client, method)(f"/api/v1/wards/{ward['id']}", headers=h, json={"phone": "1234"})
        assert resp.status_code in (404, 405)
