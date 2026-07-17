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


# ---------------------------------------------------------------------------
# Roadmap PR5 (docs/kickoffs/PR5-equipment-master-bcm-search.md): Equipment
# Master identifiers (item_no, bcm_code), manual BCM-Code-only search, and
# internal QR Item No resolution.
# ---------------------------------------------------------------------------


async def _create_equipment_with_bcm(
    client, headers, asset_number, bcm_code=None, item_no=None, name="PR5 Device"
):
    payload = {"asset_number": asset_number, "equipment_name": name}
    if bcm_code is not None:
        payload["bcm_code"] = bcm_code
    if item_no is not None:
        payload["item_no"] = item_no
    resp = await client.post("/api/v1/equipment", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_duplicate_bcm_code_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0001", bcm_code="BCM00001")
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-PR5-0002", "equipment_name": "Other", "bcm_code": "BCM00001"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_duplicate_item_no_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0003", item_no="ITEM-0001")
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-PR5-0004", "equipment_name": "Second", "item_no": "ITEM-0001"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_bcm_search_matches_only_bcm_code_not_other_fields(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(
        client, headers, "AST-PR5-0005", bcm_code="BCM00342", name="Very Special Pump Name"
    )
    for q in ["Very Special", "AST-PR5-0005", "Pump"]:
        resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": q})
        assert resp.status_code == 200, resp.text
        assert resp.json() == [], f"query {q!r} must not match anything but bcm_code"


async def test_bcm_search_case_insensitive_and_trimmed(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0006", bcm_code="BCM00342")
    for q in ["342", "  342  ", "bcm00342", "BCM00342", "  bcm342  ", "Bcm342"]:
        resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": q})
        assert resp.status_code == 200, resp.text
        codes = [item["bcm_code"] for item in resp.json()]
        assert "BCM00342" in codes, f"query {q!r} should match BCM00342, got {codes}"


async def test_bcm_search_supports_without_prefix_and_partial_matching(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    for asset, bcm in [
        ("AST-PR5-0007", "BCM00342"),
        ("AST-PR5-0008", "BCM01342"),
        ("AST-PR5-0009", "BCM03427"),
        ("AST-PR5-0010", "BCM13420"),
        ("AST-PR5-0011", "BCM99999"),
    ]:
        await _create_equipment_with_bcm(client, headers, asset, bcm_code=bcm)

    resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "342", "limit": 20})
    assert resp.status_code == 200
    codes = {item["bcm_code"] for item in resp.json()}
    assert codes == {"BCM00342", "BCM01342", "BCM03427", "BCM13420"}
    assert "BCM99999" not in codes


async def test_bcm_search_ranks_exact_match_before_partial_matches(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0012", bcm_code="BCM00342")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0013", bcm_code="BCM13420")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0014", bcm_code="BCM342")

    resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "342", "limit": 20})
    assert resp.status_code == 200
    codes = [item["bcm_code"] for item in resp.json()]
    assert codes[0] == "BCM342", f"exact match (BCM342) must rank first, got order {codes}"
    assert set(codes) == {"BCM00342", "BCM13420", "BCM342"}


async def test_bcm_search_limits_result_count(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    for i in range(15):
        await _create_equipment_with_bcm(client, headers, f"AST-PR5-LIMIT-{i:03d}", bcm_code=f"BCM9{i:04d}")
    resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "9", "limit": 5})
    assert resp.status_code == 200
    assert len(resp.json()) == 5


async def test_bcm_suggestion_contains_only_minimum_selection_data(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(
        client, headers, "AST-PR5-0015", bcm_code="BCM00500", item_no="ITEM-0500", name="Must Not Appear"
    )
    resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "500"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert set(items[0].keys()) == {"id", "bcm_code"}


async def test_bcm_search_item_no_does_not_act_as_manual_search_and_is_not_leaked(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(
        client, headers, "AST-PR5-0016", bcm_code="BCM00600", item_no="UNIQUE-ITEM-777"
    )
    resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "UNIQUE-ITEM-777"})
    assert resp.status_code == 200
    assert resp.json() == [], "item_no must not act as a manual-search field"

    resp2 = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "600"})
    assert resp2.status_code == 200
    for item in resp2.json():
        assert "item_no" not in item, "item_no must never appear in a BCM suggestion"


async def test_bcm_search_empty_or_insufficient_query_returns_empty_not_full_list(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0017", bcm_code="BCM00700")

    resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": ""})
    assert resp.status_code == 200
    assert resp.json() == []

    resp2 = await client.get("/api/v1/equipment/search/bcm", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json() == []

    # Prefix-only query: nothing left to search once "BCM" is stripped.
    resp3 = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "BCM"})
    assert resp3.status_code == 200
    assert resp3.json() == []


async def test_resolve_qr_by_item_no_finds_equipment(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    created = await _create_equipment_with_bcm(
        client, headers, "AST-PR5-0018", item_no="PHY-ITEM-001", name="Scanner Target"
    )

    resp = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "PHY-ITEM-001"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == created["id"]
    assert resp.json()["asset_number"] == "AST-PR5-0018"

    resp2 = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "  PHY-ITEM-001  "}
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] == created["id"]


async def test_resolve_qr_unknown_item_no_returns_not_found(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    resp = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "NOPE-NOT-REAL"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "EQUIPMENT_NOT_FOUND"


async def test_resolve_qr_malformed_payload_returns_controlled_error(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")

    resp = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "   "})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "MALFORMED_QR_CODE"

    resp2 = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "https://example.com/asset/123"}
    )
    assert resp2.status_code == 400
    assert resp2.json()["code"] == "MALFORMED_QR_CODE"

    resp3 = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "X" * 65})
    assert resp3.status_code == 400
    assert resp3.json()["code"] == "MALFORMED_QR_CODE"


async def test_resolve_qr_uses_exact_item_no_not_partial_matching(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0019", item_no="ITEM-EXACT-100")

    resp = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "ITEM-EXACT-1"})
    assert resp.status_code == 404, "a partial Item No must not resolve to an equipment record"


async def test_resolve_qr_and_bcm_search_use_separate_fields(client, seeded_users):
    headers = await _auth_headers(client, seeded_users, "admin")
    await _create_equipment_with_bcm(
        client, headers, "AST-PR5-0020", item_no="ITEM-BOTH-001", bcm_code="BCM00800", name="Both Fields"
    )

    resp = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "ITEM-BOTH-001"})
    assert resp.status_code == 200

    resp2 = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "800"})
    assert resp2.status_code == 200
    assert resp2.json()[0]["bcm_code"] == "BCM00800"

    resp3 = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "ITEM-BOTH-001"})
    assert resp3.json() == [], "BCM search must not match on item_no"

    resp4 = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "BCM00800"})
    assert resp4.status_code == 404, "QR resolution must not match on bcm_code"
