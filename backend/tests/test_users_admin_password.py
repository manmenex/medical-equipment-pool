import json
import uuid

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY, User
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio

CREATE_PASSWORD = "Create-Secret-Pw-91"
PATCH_PASSWORD = "Patch-Secret-Pw-77"


async def _create(client, headers, code="ADM-USR-1"):
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "employee_code": code,
            "full_name": "Target User",
            "email": f"{code.lower()}@mep-hospital-test.dev",
            "password": CREATE_PASSWORD,
            "role_name": ROLE_READ_ONLY,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _audit_text(db_session) -> str:
    db_session.expire_all()
    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    return json.dumps([[r.action, r.before_data, r.after_data] for r in rows], default=str)


async def test_create_and_update_audit_contain_no_password_or_hash(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create(client, headers)
    resp = await client.patch(
        f"/api/v1/users/{created['id']}", headers=headers, json={"password": PATCH_PASSWORD, "full_name": "New"}
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    target = await db_session.get(User, uuid.UUID(created["id"]))
    password_hash = target.password_hash

    text = await _audit_text(db_session)
    assert CREATE_PASSWORD not in text
    assert PATCH_PASSWORD not in text
    assert password_hash not in text
    # app.core.audit.redact_sensitive masks these keys before persistence.
    assert "***REDACTED***" in text


async def test_reset_password_success_and_old_password_stops_working(client, seeded_users, db_session):
    admin_id = seeded_users[ROLE_ADMINISTRATOR].id
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create(client, headers)
    resp = await client.post(f"/api/v1/users/{created['id']}/reset-password", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["employee_code"] == "ADM-USR-1"
    temp = body["temporary_password"]
    assert temp and temp != CREATE_PASSWORD

    db_session.expire_all()
    target = await db_session.get(User, uuid.UUID(created["id"]))
    assert target.must_change_password is True
    assert target.failed_login_attempts == 0
    assert target.locked_until is None

    old = await client.post("/api/v1/auth/login", json={"identifier": "ADM-USR-1", "password": CREATE_PASSWORD})
    assert old.status_code != 200
    new = await client.post("/api/v1/auth/login", json={"identifier": "ADM-USR-1", "password": temp})
    assert new.status_code == 200, new.text

    password_hash = target.password_hash
    target_id = target.id
    text = await _audit_text(db_session)
    assert temp not in text
    assert password_hash not in text
    row = (await db_session.execute(select(AuditLog).where(AuditLog.action == "PASSWORD_RESET_ADMIN"))).scalar_one()
    assert row.user_id == admin_id
    assert row.entity_id == target_id


@pytest.mark.parametrize("role", [ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY])
async def test_reset_password_forbidden_for_non_admin(client, seeded_users, role):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create(client, admin)
    headers = await _auth_headers(client, role)
    resp = await client.post(f"/api/v1/users/{created['id']}/reset-password", headers=headers)
    assert resp.status_code == 403


async def test_reset_password_unknown_user_404(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(f"/api/v1/users/{uuid.uuid4()}/reset-password", headers=headers)
    assert resp.status_code == 404


async def test_reset_password_self_refused(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    me = seeded_users[ROLE_ADMINISTRATOR]
    resp = await client.post(f"/api/v1/users/{me.id}/reset-password", headers=headers)
    assert resp.status_code == 409
    login = await client.post("/api/v1/auth/login", json={"identifier": me.employee_code, "password": "Password@123"})
    assert login.status_code == 200


async def test_admin_cannot_deactivate_or_change_own_role(client, seeded_users):
    me_id = str(seeded_users[ROLE_ADMINISTRATOR].id)
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    r1 = await client.patch(f"/api/v1/users/{me_id}", headers=headers, json={"is_active": False})
    assert r1.status_code == 409
    r2 = await client.patch(f"/api/v1/users/{me_id}", headers=headers, json={"role_name": ROLE_READ_ONLY})
    assert r2.status_code == 409
    # Harmless self edits (same role, name change) still work.
    r3 = await client.patch(
        f"/api/v1/users/{me_id}", headers=headers, json={"role_name": ROLE_ADMINISTRATOR, "full_name": "Renamed"}
    )
    assert r3.status_code == 200, r3.text


async def test_other_user_can_still_be_deactivated(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create(client, headers)
    resp = await client.patch(f"/api/v1/users/{created['id']}", headers=headers, json={"is_active": False})
    assert resp.status_code == 200


class _FakeRedis:
    def __init__(self, data):
        self.data = dict(data)

    async def scan_iter(self, match=None):
        for k in list(self.data):
            yield k

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)


async def test_reset_password_revokes_target_refresh_tokens_only(client, seeded_users, monkeypatch):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create(client, headers)
    other = str(seeded_users[ROLE_READ_ONLY].id)
    fake = _FakeRedis({"refresh:a": created["id"], "refresh:b": created["id"], "refresh:c": other})
    import app.core.redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)
    resp = await client.post(f"/api/v1/users/{created['id']}/reset-password", headers=headers)
    assert resp.status_code == 200, resp.text
    assert fake.data == {"refresh:c": other}
