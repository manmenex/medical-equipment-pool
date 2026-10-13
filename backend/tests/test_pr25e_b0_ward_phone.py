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


async def _mk(client, h, path, code="P1", phone=None, name=None):
    body = {"code": code, "name": name or code}
    if phone:
        body["phone"] = phone
    r = await client.post(path, headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("path", ["/api/v1/wards", "/api/v1/departments"])
async def test_patch_phone_set_clear_and_audit(client, seeded_users, db_session, path):
    from sqlalchemy import select

    from app.models.audit import AuditLog

    h = await auth_headers(client)
    obj = await _mk(client, h, path, phone="1111")
    r = await client.patch(f"{path}/{obj['id']}", headers=h, json={"phone": " 02-999-8888 "})
    assert r.status_code == 200 and r.json()["phone"] == "02-999-8888"
    r = await client.patch(f"{path}/{obj['id']}", headers=h, json={"phone": "  "})
    assert r.status_code == 200 and r.json()["phone"] is None
    r = await client.patch(f"{path}/{obj['id']}", headers=h, json={"phone": None})
    assert r.status_code == 200 and r.json()["phone"] is None
    rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "update").order_by(AuditLog.created_at)
        )
    ).scalars().all()
    assert len(rows) == 3
    assert rows[0].before_data == {"phone": "1111"} and rows[0].after_data == {"phone": "02-999-8888"}
    assert rows[1].after_data == {"phone": None}


@pytest.mark.parametrize("path", ["/api/v1/wards", "/api/v1/departments"])
async def test_patch_validation_extra_fields_missing_and_permissions(client, seeded_users, path):
    h = await auth_headers(client)
    obj = await _mk(client, h, path, phone="1111")
    url = f"{path}/{obj['id']}"
    assert (await client.patch(url, headers=h, json={"phone": "abc"})).status_code == 422
    assert (await client.patch(url, headers=h, json={"phone": "1234", "name": "X"})).status_code == 422
    assert (await client.patch(url, headers=h, json={"code": "X"})).status_code == 422
    assert (await client.patch(f"{path}/00000000-0000-0000-0000-000000000000", headers=h, json={"phone": "1234"})).status_code == 404
    assert (await client.patch(f"{path}/not-a-uuid", headers=h, json={"phone": "1234"})).status_code == 400
    for role in (ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        rh = await auth_headers(client, role)
        assert (await client.patch(url, headers=rh, json={"phone": "9999"})).status_code == 403
    assert (await client.get(path, headers=h)).json()[0]["phone"] == "1111"
    assert (await client.patch(url, json={"phone": "9999"})).status_code in (401, 403)


IMPORT = "/api/v1/wards/phones/import"


async def _wards(client, h):
    return {w["name"]: w["phone"] for w in (await client.get("/api/v1/wards", headers=h)).json()}


async def test_import_dry_run_default_writes_nothing_and_reports(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog

    h = await auth_headers(client)
    await _mk(client, h, "/api/v1/wards", "A", name="Ward A")
    await _mk(client, h, "/api/v1/wards", "B", name="Ward B", phone="5555")
    await _mk(client, h, "/api/v1/wards", "C", name="Ward C", phone="7777")
    rows = [
        {"ward_name": " Ward A ", "phone": "1001"},
        {"ward_name": "Ward B", "phone": "1002"},
        {"ward_name": "Ward C", "phone": "7777"},
        {"ward_name": "Nope", "phone": "1004"},
        {"ward_name": "Ward A2", "phone": "bad!"},
        {"ward_name": "Dup", "phone": "1005"},
        {"ward_name": "Dup", "phone": "1006"},
        {"ward_name": "ward a", "phone": "1007"},
    ]
    r = await client.post(IMPORT, headers=h, json={"rows": rows})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True and body["applied"] is False
    assert [x["outcome"] for x in body["results"]] == [
        "will_set", "skipped_existing", "unchanged", "unknown_ward",
        "invalid_phone", "duplicate_ward_name", "duplicate_ward_name", "unknown_ward",
    ]
    assert await _wards(client, h) == {"Ward A": None, "Ward B": "5555", "Ward C": "7777"}
    audits = (await db_session.execute(select(AuditLog).where(AuditLog.action == "import"))).scalars().all()
    assert audits == []


async def test_import_apply_one_transaction_one_audit(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog

    h = await auth_headers(client)
    await _mk(client, h, "/api/v1/wards", "A", name="Ward A")
    await _mk(client, h, "/api/v1/wards", "B", name="Ward B", phone="5555")
    await _mk(client, h, "/api/v1/wards", "D", name="Ward D")
    rows = [
        {"ward_name": "Ward A", "phone": "1001"},
        {"ward_name": "Ward B", "phone": "1002"},
        {"ward_name": "Ward D", "phone": "x"},
    ]
    r = await client.post(IMPORT + "?dry_run=false", headers=h, json={"rows": rows})
    assert r.status_code == 200 and r.json()["applied"] is True
    assert await _wards(client, h) == {"Ward A": "1001", "Ward B": "5555", "Ward D": None}
    audits = (await db_session.execute(select(AuditLog).where(AuditLog.action == "import"))).scalars().all()
    assert len(audits) == 1
    assert [c["after"] for c in audits[0].after_data["changed"]] == ["1001"]


async def test_import_overwrite_flag(client, seeded_users):
    h = await auth_headers(client)
    await _mk(client, h, "/api/v1/wards", "B", name="Ward B", phone="5555")
    rows = [{"ward_name": "Ward B", "phone": "1002"}]
    r = await client.post(IMPORT + "?dry_run=false&overwrite=true", headers=h, json={"rows": rows})
    assert r.json()["results"][0]["outcome"] == "will_overwrite"
    assert await _wards(client, h) == {"Ward B": "1002"}


async def test_import_size_bound_and_shape(client, seeded_users):
    h = await auth_headers(client)
    big = {"rows": [{"ward_name": f"W{i}", "phone": "1234"} for i in range(501)]}
    assert (await client.post(IMPORT, headers=h, json=big)).status_code == 422
    ok = {"rows": [{"ward_name": f"W{i}", "phone": "1234"} for i in range(500)]}
    assert (await client.post(IMPORT, headers=h, json=ok)).status_code == 200
    assert (await client.post(IMPORT, headers=h, json={"rows": []})).status_code == 422
    assert (await client.post(IMPORT, headers=h, json={"rows": [{"ward_name": "a"}], "x": 1})).status_code == 422


@pytest.mark.parametrize("role", [ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY])
async def test_import_admin_only(client, seeded_users, role):
    h = await auth_headers(client, role)
    r = await client.post(IMPORT + "?dry_run=false", headers=h, json={"rows": [{"ward_name": "a", "phone": "1234"}]})
    assert r.status_code == 403
