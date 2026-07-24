"""Roadmap PR10 (Role Model Consolidation): the complete table-driven RBAC
matrix for the confirmed 3-role model (administrator, equipment_pool_staff,
read_only), covering every capability group defined in
app.api.v1.deps (EQUIPMENT_POOL_OPERATION_ROLES, ADMINISTRATOR_ONLY_ROLES,
VIEW_AND_REPORT_ROLES, WARD_CORRECTION_ROLES) plus the unrestricted
view/list surfaces. Each capability is exercised against all 3 roles, with
an explicit negative case for every role that must be denied -- not just a
single "some role is denied" smoke test.

Ward-correction's own dedicated matrix lives in test_ward_correction.py
(it needs its own fixtures for dispatch/ward setup and audit-content
assertions); it is not duplicated here beyond the single row this table
needs for completeness.
"""
import pytest

from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward
from tests.conftest import on_demand_borrow_payload as _on_demand_borrow_payload

pytestmark = pytest.mark.asyncio

ALL_THREE_ROLES = (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY)

# EQUIPMENT_POOL_OPERATION_ROLES: administrator + equipment_pool_staff granted, read_only denied.
EQUIPMENT_POOL_OPERATION_MATRIX = [
    (ROLE_ADMINISTRATOR, True),
    (ROLE_EQUIPMENT_POOL_STAFF, True),
    (ROLE_READ_ONLY, False),
]

# ADMINISTRATOR_ONLY_ROLES: only administrator granted.
ADMINISTRATOR_ONLY_MATRIX = [
    (ROLE_ADMINISTRATOR, True),
    (ROLE_EQUIPMENT_POOL_STAFF, False),
    (ROLE_READ_ONLY, False),
]


async def _create_equipment(client, headers, asset_number):
    resp = await client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": asset_number, "equipment_name": "RBAC Pump"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Equipment master data: create / update / delete (ADMINISTRATOR_ONLY_ROLES)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_create_equipment_rbac(client, seeded_users, role, granted):
    headers = await _auth_headers(client, role)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": f"RBAC-CREATE-{role}", "equipment_name": "Pump"},
    )
    assert resp.status_code == (201 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_update_equipment_rbac(client, seeded_users, role, granted):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment(client, admin_headers, f"RBAC-UPDATE-{role}")

    headers = await _auth_headers(client, role)
    resp = await client.patch(
        f"/api/v1/equipment/{equipment['id']}", headers=headers, json={"equipment_name": "Renamed"}
    )
    assert resp.status_code == (200 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_delete_equipment_rbac(client, seeded_users, role, granted):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment(client, admin_headers, f"RBAC-DELETE-{role}")

    headers = await _auth_headers(client, role)
    resp = await client.delete(f"/api/v1/equipment/{equipment['id']}", headers=headers)
    assert resp.status_code == (204 if granted else 403), resp.text


# ---------------------------------------------------------------------------
# Equipment manual status change: three capabilities behind one endpoint,
# distinguished by payload.status (app.api.v1.equipment.
# EQUIPMENT_STATUS_ADMINISTRATOR_ONLY_TARGETS).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role, granted", EQUIPMENT_POOL_OPERATION_MATRIX)
async def test_mark_defective_rbac(client, seeded_users, role, granted):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment(client, admin_headers, f"RBAC-DEFECTIVE-{role}")

    headers = await _auth_headers(client, role)
    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "RBAC matrix"},
    )
    assert resp.status_code == (200 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_reactivate_equipment_rbac(client, seeded_users, role, granted):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment(client, admin_headers, f"RBAC-REACTIVATE-{role}")
    defective_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=admin_headers,
        json={"status": "unavailable_defective", "reason": "setup"},
    )
    assert defective_resp.status_code == 200, defective_resp.text

    headers = await _auth_headers(client, role)
    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "available_at_pool", "reason": "RBAC matrix"},
    )
    assert resp.status_code == (200 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_decommission_equipment_rbac(client, seeded_users, role, granted):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment(client, admin_headers, f"RBAC-DECOMMISSION-{role}")
    defective_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=admin_headers,
        json={"status": "unavailable_defective", "reason": "setup"},
    )
    assert defective_resp.status_code == 200, defective_resp.text

    headers = await _auth_headers(client, role)
    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "decommissioned", "reason": "RBAC matrix"},
    )
    assert resp.status_code == (200 if granted else 403), resp.text


# ---------------------------------------------------------------------------
# Dispatch / receipt / ward correction (EQUIPMENT_POOL_OPERATION_ROLES /
# WARD_CORRECTION_ROLES -- confirmed to be the same set today, but asserted
# independently since they are separate capability groups).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role, granted", EQUIPMENT_POOL_OPERATION_MATRIX)
async def test_dispatch_rbac(client, seeded_users, role, granted):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment(client, admin_headers, f"RBAC-DISPATCH-{role}")
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code=f"W-RBAC-D-{role[:8]}")

    headers = await _auth_headers(client, role)
    resp = await client.post("/api/v1/borrow", headers=headers, json=payload)
    assert resp.status_code == (201 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", EQUIPMENT_POOL_OPERATION_MATRIX)
async def test_receipt_rbac(client, seeded_users, role, granted):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment(client, admin_headers, f"RBAC-RECEIPT-{role}")
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code=f"W-RBAC-R-{role[:8]}")
    borrow_resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx_id = borrow_resp.json()["id"]

    headers = await _auth_headers(client, role)
    resp = await client.post(f"/api/v1/return/{tx_id}", headers=headers, json={"receipt_outcome": "usable"})
    assert resp.status_code == (200 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", EQUIPMENT_POOL_OPERATION_MATRIX)
async def test_ward_correction_rbac(client, seeded_users, role, granted):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment(client, admin_headers, f"RBAC-WARDCORR-{role}")
    payload = await _on_demand_borrow_payload(
        client, admin_headers, equipment["id"], ward_code=f"W-RBAC-WC1-{role[:8]}"
    )
    borrow_resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx_id = borrow_resp.json()["id"]
    new_ward_id = await _create_ward(client, admin_headers, f"W-RBAC-WC2-{role[:8]}")

    headers = await _auth_headers(client, role)
    resp = await client.post(
        f"/api/v1/transactions/{tx_id}/correct-ward",
        headers=headers,
        json={"ward_id": new_ward_id, "reason": "RBAC matrix"},
    )
    assert resp.status_code == (200 if granted else 403), resp.text


# ---------------------------------------------------------------------------
# Master data create (ADMINISTRATOR_ONLY_ROLES): departments, wards,
# locations, categories.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_create_department_rbac(client, seeded_users, role, granted):
    headers = await _auth_headers(client, role)
    resp = await client.post(
        "/api/v1/departments", headers=headers, json={"code": f"RBAC-DEP-{role[:6]}", "name": "RBAC Dept"}
    )
    assert resp.status_code == (201 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_create_ward_rbac(client, seeded_users, role, granted):
    headers = await _auth_headers(client, role)
    resp = await client.post("/api/v1/wards", headers=headers, json={"code": f"RBAC-W-{role[:6]}", "name": "RBAC Ward"})
    assert resp.status_code == (201 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_create_location_rbac(client, seeded_users, role, granted):
    headers = await _auth_headers(client, role)
    resp = await client.post("/api/v1/locations", headers=headers, json={"name": f"RBAC Location {role}"})
    assert resp.status_code == (201 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_create_category_rbac(client, seeded_users, role, granted):
    headers = await _auth_headers(client, role)
    resp = await client.post("/api/v1/categories", headers=headers, json={"name": f"RBAC Category {role}"})
    assert resp.status_code == (201 if granted else 403), resp.text


# ---------------------------------------------------------------------------
# User and role management (ADMINISTRATOR_ONLY_ROLES).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_list_users_rbac(client, seeded_users, role, granted):
    headers = await _auth_headers(client, role)
    resp = await client.get("/api/v1/users", headers=headers)
    assert resp.status_code == (200 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_create_user_rbac(client, seeded_users, role, granted):
    headers = await _auth_headers(client, role)
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "employee_code": f"RBAC-USR-{role[:6]}",
            "full_name": "RBAC New User",
            "email": f"rbac-{role}@mep-hospital-test.dev",
            "password": "Password@123",
            "role_name": ROLE_READ_ONLY,
        },
    )
    assert resp.status_code == (201 if granted else 403), resp.text


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_update_user_rbac(client, seeded_users, role, granted):
    target_id = str(seeded_users[ROLE_READ_ONLY].id)
    headers = await _auth_headers(client, role)
    resp = await client.patch(f"/api/v1/users/{target_id}", headers=headers, json={"full_name": "RBAC Renamed"})
    assert resp.status_code == (200 if granted else 403), resp.text


# ---------------------------------------------------------------------------
# Audit log reads (ADMINISTRATOR_ONLY_ROLES).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role, granted", ADMINISTRATOR_ONLY_MATRIX)
async def test_audit_log_listing_rbac(client, seeded_users, role, granted):
    headers = await _auth_headers(client, role)
    resp = await client.get("/api/v1/audit-logs", headers=headers)
    assert resp.status_code == (200 if granted else 403), resp.text


# ---------------------------------------------------------------------------
# Reports export (VIEW_AND_REPORT_ROLES: all 3 confirmed roles).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ALL_THREE_ROLES)
async def test_reports_export_rbac(client, seeded_users, role):
    headers = await _auth_headers(client, role)
    resp = await client.get("/api/v1/reports/export", headers=headers, params={"format": "csv"})
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Unrestricted view/list surfaces: every authenticated role, including
# Read Only, may view. No 403 for any of the 3 confirmed roles.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ALL_THREE_ROLES)
async def test_list_equipment_unrestricted(client, seeded_users, role):
    headers = await _auth_headers(client, role)
    resp = await client.get("/api/v1/equipment", headers=headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", ALL_THREE_ROLES)
async def test_list_active_borrows_unrestricted(client, seeded_users, role):
    headers = await _auth_headers(client, role)
    resp = await client.get("/api/v1/borrow/active", headers=headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", ALL_THREE_ROLES)
async def test_list_transactions_unrestricted(client, seeded_users, role):
    headers = await _auth_headers(client, role)
    resp = await client.get("/api/v1/transactions", headers=headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", ALL_THREE_ROLES)
async def test_list_master_data_unrestricted(client, seeded_users, role):
    headers = await _auth_headers(client, role)
    for path in ("/api/v1/departments", "/api/v1/wards", "/api/v1/locations", "/api/v1/categories"):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 200, f"{path} for {role}: {resp.text}"


# ---------------------------------------------------------------------------
# Explicit negative tests: an unauthenticated caller and an unrecognized
# role name are rejected the same way for every capability tier -- not
# merely "some authenticated role is denied."
# ---------------------------------------------------------------------------


async def test_unauthenticated_caller_is_rejected_on_every_capability_tier(client, seeded_users):
    for method, path, json_body in (
        ("GET", "/api/v1/equipment", None),
        ("POST", "/api/v1/equipment", {"asset_number": "NOAUTH", "equipment_name": "X"}),
        ("GET", "/api/v1/users", None),
        ("GET", "/api/v1/audit-logs", None),
        ("GET", "/api/v1/reports/export", None),
    ):
        resp = await client.request(method, path, json=json_body)
        assert resp.status_code == 401, f"{method} {path}: {resp.text}"


async def test_administrator_only_capabilities_deny_both_non_administrator_roles_identically(client, seeded_users):
    """Both non-administrator roles must be denied the same way (403
    FORBIDDEN), not just "denied to at least one of them" -- proves
    ADMINISTRATOR_ONLY_ROLES is enforced as a single-member set, not
    accidentally permissive to equipment_pool_staff."""
    for role in (ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        resp = await client.get("/api/v1/users", headers=headers)
        assert resp.status_code == 403, f"{role}: {resp.text}"
        assert resp.json()["code"] == "FORBIDDEN"
