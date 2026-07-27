import uuid

import pytest
from sqlalchemy import select

from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import on_demand_borrow_payload as _on_demand_borrow_payload
from tests.identifier_vectors import (
    BCM_INVALID_VECTORS,
    BCM_VALID_VECTORS,
    ITEM_NO_INVALID_VECTORS,
    ITEM_NO_VALID_VECTORS,
)

pytestmark = pytest.mark.asyncio


async def test_create_and_get_equipment(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-0001", "equipment_name": "Infusion Pump"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "available_at_pool"
    assert "qr_code_value" not in body, "retired legacy QR value must never appear in a response (ADR-004)"

    resp2 = await client.get(f"/api/v1/equipment/{body['id']}", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["asset_number"] == "AST-0001"


async def test_viewer_cannot_create_equipment(client, seeded_users):
    headers = await _auth_headers(client, ROLE_READ_ONLY)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-0002", "equipment_name": "ECG"},
    )
    assert resp.status_code == 403


async def test_search_equipment_by_name(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-0003", "equipment_name": "Ventilator Pro"},
    )
    resp = await client.get("/api/v1/equipment", headers=headers, params={"q": "Ventilator"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(i["asset_number"] == "AST-0003" for i in items)


async def test_legacy_by_qr_route_removed(client, seeded_users):
    """ADR-004: the legacy exact-match-on-qr_code_value route is retired,
    not merely redirected — it must not exist at all."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/equipment/by-qr/MEP:AST-0004", headers=headers)
    assert resp.status_code == 404


async def test_legacy_qrcode_generation_route_removed(client, seeded_users):
    """ADR-004: the app must not generate/expose its own competing QR
    image for the retired legacy scheme."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-0004", "equipment_name": "Defibrillator"},
    )
    equipment_id = create_resp.json()["id"]
    resp = await client.get(f"/api/v1/equipment/{equipment_id}/qrcode", headers=headers)
    assert resp.status_code == 404


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
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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
        json={"status": "unavailable_defective", "reason": "Needs a new wheel"},
    )
    assert status_resp.status_code == 200, status_resp.text
    body = status_resp.json()
    assert body["status"] == "unavailable_defective"
    assert body["id"] == equipment_id
    assert body["updated_at"]


async def test_update_equipment_persists_exactly_once_via_fresh_session(client, seeded_users, db_session):
    from app.models.equipment import Equipment

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "FIX-STATUS-0002", "equipment_name": "Wheelchair"},
    )
    equipment_id = create_resp.json()["id"]

    status_resp = await client.post(
        f"/api/v1/equipment/{equipment_id}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "Needs a new wheel"},
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


# ---------------------------------------------------------------------------
# Roadmap PR14A (Backend Audit 4.1): PATCH nullable-field correctness.
# ---------------------------------------------------------------------------


async def test_update_equipment_can_clear_a_nullable_field(client, seeded_users, db_session):
    """Proves persisted state actually changed, not just that the PATCH
    response body echoes null -- a fresh GET (new request, same committed
    row) and a direct DB re-read both confirm the clear landed, and the
    audit row's `after` payload records the null explicitly."""
    from app.models.audit import AuditLog
    from app.models.equipment import Equipment

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "PR14A-0001", "equipment_name": "Pump", "brand": "Acme"},
    )
    equipment_id = create_resp.json()["id"]
    assert create_resp.json()["brand"] == "Acme"

    update_resp = await client.patch(
        f"/api/v1/equipment/{equipment_id}", headers=headers, json={"brand": None}
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["brand"] is None

    get_resp = await client.get(f"/api/v1/equipment/{equipment_id}", headers=headers)
    assert get_resp.json()["brand"] is None, "a fresh read must also see the cleared value, not a stale echo"

    db_session.expire_all()
    row = await db_session.get(Equipment, uuid.UUID(equipment_id))
    assert row.brand is None, "brand must actually be cleared in the database"

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "update",
            AuditLog.entity_type == "equipment",
            AuditLog.entity_id == uuid.UUID(equipment_id),
        )
    )
    audit_rows = result.scalars().all()
    assert len(audit_rows) == 1
    assert audit_rows[0].after_data["brand"] is None, "the audit row must record after.brand = null"


async def test_update_equipment_rejects_null_on_required_equipment_name(client, seeded_users, db_session):
    from app.models.audit import AuditLog

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "PR14A-0002", "equipment_name": "Old Name"},
    )
    equipment_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/equipment/{equipment_id}", headers=headers, json={"equipment_name": None}
    )
    assert update_resp.status_code == 400, update_resp.text
    assert update_resp.json()["code"] == "INVALID_INPUT"

    get_resp = await client.get(f"/api/v1/equipment/{equipment_id}", headers=headers)
    assert get_resp.json()["equipment_name"] == "Old Name", "the required field must remain unchanged"

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "update",
            AuditLog.entity_type == "equipment",
            AuditLog.entity_id == uuid.UUID(equipment_id),
        )
    )
    assert result.scalars().all() == [], "a rejected request must produce no audit event"


async def test_update_equipment_rejects_null_bcm_code_with_no_mutation_and_no_audit_event(
    client, seeded_users, db_session
):
    from app.models.audit import AuditLog

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "PR14A-0003", bcm_code="BCM00900")
    equipment_id = created["id"]

    update_resp = await client.patch(
        f"/api/v1/equipment/{equipment_id}", headers=headers, json={"bcm_code": None}
    )
    assert update_resp.status_code == 400, update_resp.text
    assert update_resp.json()["code"] == "INVALID_INPUT"

    get_resp = await client.get(f"/api/v1/equipment/{equipment_id}", headers=headers)
    assert get_resp.json()["bcm_code"] == "BCM00900", "bcm_code must not be cleared by a rejected request"

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "update",
            AuditLog.entity_type == "equipment",
            AuditLog.entity_id == uuid.UUID(equipment_id),
        )
    )
    assert result.scalars().all() == [], "a rejected identifier-null request must produce no audit event"


async def test_update_equipment_rejects_null_item_no_with_no_mutation_and_no_audit_event(
    client, seeded_users, db_session
):
    from app.models.audit import AuditLog

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "PR14A-0004", item_no="ITEM-PR14A-0004")
    equipment_id = created["id"]

    update_resp = await client.patch(
        f"/api/v1/equipment/{equipment_id}", headers=headers, json={"item_no": None}
    )
    assert update_resp.status_code == 400, update_resp.text
    assert update_resp.json()["code"] == "INVALID_INPUT"

    resolved = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "ITEM-PR14A-0004"}
    )
    assert resolved.status_code == 200, "item_no must not be cleared by a rejected request"

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "update",
            AuditLog.entity_type == "equipment",
            AuditLog.entity_id == uuid.UUID(equipment_id),
        )
    )
    assert result.scalars().all() == [], "a rejected identifier-null request must produce no audit event"


async def test_update_equipment_still_accepts_a_nonnull_bcm_code_change(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "PR14A-0005", bcm_code="BCM00901")

    update_resp = await client.patch(
        f"/api/v1/equipment/{created['id']}", headers=headers, json={"bcm_code": "BCM00902"}
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["bcm_code"] == "BCM00902"


async def test_ordinary_request_still_succeeds_after_update_and_status_change(client, seeded_users):
    """Proves the fix didn't leave the session/connection unusable — an
    unrelated, completely ordinary follow-up request still works."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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
        json={"status": "unavailable_defective"},
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
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0001", bcm_code="BCM00001")
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-PR5-0002", "equipment_name": "Other", "bcm_code": "BCM00001"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_duplicate_item_no_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0003", item_no="ITEM-0001")
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-PR5-0004", "equipment_name": "Second", "item_no": "ITEM-0001"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_bcm_search_matches_only_bcm_code_not_other_fields(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(
        client, headers, "AST-PR5-0005", bcm_code="BCM00342", name="Very Special Pump Name"
    )
    for q in ["Very Special", "AST-PR5-0005", "Pump"]:
        resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": q})
        assert resp.status_code == 200, resp.text
        assert resp.json() == [], f"query {q!r} must not match anything but bcm_code"


async def test_bcm_search_case_insensitive_and_trimmed(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0006", bcm_code="BCM00342")
    for q in ["342", "  342  ", "bcm00342", "BCM00342", "  bcm342  ", "Bcm342"]:
        resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": q})
        assert resp.status_code == 200, resp.text
        codes = [item["bcm_code"] for item in resp.json()]
        assert "BCM00342" in codes, f"query {q!r} should match BCM00342, got {codes}"


async def test_bcm_search_supports_without_prefix_and_partial_matching(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0012", bcm_code="BCM00342")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0013", bcm_code="BCM13420")
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0014", bcm_code="BCM342")

    resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "342", "limit": 20})
    assert resp.status_code == 200
    codes = [item["bcm_code"] for item in resp.json()]
    assert codes[0] == "BCM342", f"exact match (BCM342) must rank first, got order {codes}"
    assert set(codes) == {"BCM00342", "BCM13420", "BCM342"}


async def test_bcm_search_limits_result_count(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    for i in range(15):
        await _create_equipment_with_bcm(client, headers, f"AST-PR5-LIMIT-{i:03d}", bcm_code=f"BCM9{i:04d}")
    resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "9", "limit": 5})
    assert resp.status_code == 200
    assert len(resp.json()) == 5


async def test_bcm_suggestion_contains_only_minimum_selection_data(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(
        client, headers, "AST-PR5-0015", bcm_code="BCM00500", item_no="ITEM-0500", name="Must Not Appear"
    )
    resp = await client.get("/api/v1/equipment/search/bcm", headers=headers, params={"q": "500"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert set(items[0].keys()) == {"id", "bcm_code"}


async def test_bcm_search_item_no_does_not_act_as_manual_search_and_is_not_leaked(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "NOPE-NOT-REAL"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "EQUIPMENT_NOT_FOUND"


async def test_resolve_qr_malformed_payload_returns_controlled_error(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)

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
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0019", item_no="ITEM-EXACT-100")

    resp = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "ITEM-EXACT-1"})
    assert resp.status_code == 404, "a partial Item No must not resolve to an equipment record"


async def test_resolve_qr_and_bcm_search_use_separate_fields(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
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


async def test_resolve_qr_rejects_retired_mep_format_as_malformed(client, seeded_users):
    """ADR-004: a scanned legacy MEP:{asset_number} label is rejected as
    unsupported, distinctly from an unrecognized-but-well-formed Item No
    (404) — never silently interpreted as an Item No candidate."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "MEP:AST-0001"}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "MALFORMED_QR_CODE"


async def test_borrow_by_hospital_item_no_scan(client, seeded_users):
    """Full Borrow scanner flow: resolve-qr (Item No) -> equipment_id -> borrow."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    created = await _create_equipment_with_bcm(
        client, headers, "AST-PR5-0021", item_no="ITEM-BORROW-001", name="Borrow Scan Target"
    )

    resolved = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "ITEM-BORROW-001"}
    )
    assert resolved.status_code == 200
    assert resolved.json()["id"] == created["id"]

    payload = await _on_demand_borrow_payload(client, headers, resolved.json()["id"], ward_code="W-PR5-0021")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    assert borrow_resp.json()["equipment"]["status"] == "issued_to_ward"


async def test_return_by_hospital_item_no_scan(client, seeded_users):
    """Full Return scanner flow: resolve-qr (Item No) -> equipment_id -> return."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    created = await _create_equipment_with_bcm(
        client, headers, "AST-PR5-0022", item_no="ITEM-RETURN-001", name="Return Scan Target"
    )
    payload = await _on_demand_borrow_payload(client, headers, created["id"], ward_code="W-PR5-0022")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    tx = borrow_resp.json()

    resolved = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "ITEM-RETURN-001"}
    )
    assert resolved.status_code == 200
    assert resolved.json()["id"] == created["id"]

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"receipt_outcome": "usable"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert return_resp.json()["status"] == "closed"


async def test_item_no_with_leading_zeros_preserved_through_resolution(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-PR5-0023", item_no="0000123")

    resp = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "0000123"})
    assert resp.status_code == 200, resp.text

    # A numerically-equal but differently-formatted value must NOT match --
    # leading zeros are significant, never reinterpreted numerically.
    resp2 = await client.post("/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "123"})
    assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# ADR-002 / knowledge/architecture/identifiers.md: canonicalization rules
# for BCM Code and Item No, enforced identically at create and update.
# ---------------------------------------------------------------------------


async def test_bcm_code_create_canonicalization(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0001", "equipment_name": "Pump", "bcm_code": "bcm001"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["bcm_code"] == "BCM001"


async def test_bcm_code_update_canonicalization(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "AST-CANON-0002")

    resp = await client.patch(
        f"/api/v1/equipment/{created['id']}", headers=headers, json={"bcm_code": "  bcm002  "}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["bcm_code"] == "BCM002"


async def test_bcm_code_prefix_omitted_and_supplied_are_equivalent_for_uniqueness(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "AST-CANON-0003", bcm_code="003")
    assert created["bcm_code"] == "BCM003", "prefixless input must canonicalize to BCM003"
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0004", "equipment_name": "Other", "bcm_code": "BCM003"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_bcm_code_surrounding_whitespace_canonicalizes_on_create(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "AST-CANON-0003B", bcm_code="  BCM003B  ")
    assert created["bcm_code"] == "BCM003B"


async def test_bcm_code_duplicate_by_case_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-CANON-0005", bcm_code="BCM005")
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0006", "equipment_name": "Other", "bcm_code": "bcm005"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_bcm_code_duplicate_by_surrounding_whitespace_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-CANON-0007", bcm_code="BCM007")
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0008", "equipment_name": "Other", "bcm_code": "  BCM007  "},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_bcm_code_leading_zeros_preserved(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "AST-CANON-0009", bcm_code="00042")
    assert created["bcm_code"] == "BCM00042"


async def test_item_no_create_normalization_trims_whitespace_preserves_case(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-CANON-0010", item_no="  MiXed-Case-001  ")

    resp = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "MiXed-Case-001"}
    )
    assert resp.status_code == 200, resp.text

    # Case is preserved exactly -- an all-uppercase variant must not match.
    resp2 = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "MIXED-CASE-001"}
    )
    assert resp2.status_code == 404


async def test_item_no_update_normalization_matches_create(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "AST-CANON-0011")

    resp = await client.patch(
        f"/api/v1/equipment/{created['id']}", headers=headers, json={"item_no": "  ItemUpdated-001  "}
    )
    assert resp.status_code == 200, resp.text

    resolve_resp = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "ItemUpdated-001"}
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["id"] == created["id"]


async def test_item_no_duplicate_by_whitespace_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-CANON-0012", item_no="ITEM-WS-001")
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0013", "equipment_name": "Other", "item_no": "  ITEM-WS-001  "},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_bcm_code_update_into_equivalent_existing_value_is_rejected(client, seeded_users):
    """PR5-H3R: a duplicate must be rejected on update, not only on create."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-CANON-0014", bcm_code="BCM014")
    other = await _create_equipment_with_bcm(client, headers, "AST-CANON-0015", bcm_code="BCM015")

    resp = await client.patch(
        f"/api/v1/equipment/{other['id']}", headers=headers, json={"bcm_code": "  bcm014  "}
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_item_no_update_into_equivalent_existing_value_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-CANON-0016", item_no="ITEM-UPD-CONFLICT")
    other = await _create_equipment_with_bcm(client, headers, "AST-CANON-0017", item_no="ITEM-OTHER")

    resp = await client.patch(
        f"/api/v1/equipment/{other['id']}", headers=headers, json={"item_no": "  ITEM-UPD-CONFLICT  "}
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE"


async def test_bcm_code_prefix_only_value_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0018", "equipment_name": "Other", "bcm_code": "BCM"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_bcm_code_embedded_whitespace_after_prefix_is_rejected_not_folded(client, seeded_users):
    """PR5-H3R: ADR-002 does not define "bcm 001" as equivalent to "bcm001"
    -- this must be rejected outright, never silently normalized to the
    same canonical form as the no-space input, and never silently
    persisted as its own distinct non-canonical value."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0019", "equipment_name": "Other", "bcm_code": "bcm 019"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_item_no_empty_after_trim_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0020", "equipment_name": "Other", "item_no": "   "},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# PR5-H3R: post-normalization length validation. The canonical value (not
# just the raw input) must fit the database column -- a prefixless BCM
# Code only becomes overlength once "BCM" is prepended, so this cannot be
# caught by the raw-input schema bound alone.
# ---------------------------------------------------------------------------


async def test_bcm_code_prefixless_overlength_after_normalization_is_rejected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    # 64 raw characters (passes the schema's max_length=64 on the raw
    # field) but becomes 67 once "BCM" is prepended -- must be rejected,
    # not truncated or 500'd.
    body = "9" * 64
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0021", "equipment_name": "Other", "bcm_code": body},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_bcm_code_prefixed_overlength_is_rejected(client, seeded_users):
    """A prefixed BCM Code is length-neutral through normalization (the
    "BCM" prefix is stripped and reapplied, never duplicated), so the only
    way for a *prefixed* input to be overlength is for the raw input
    itself to already exceed the column width -- caught by the schema's
    own max_length bound (422 VALIDATION_ERROR) before it ever reaches
    normalize_bcm_code. Either layer catching it is a controlled response;
    what must never happen is a database-level DataError/500."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    body = "BCM" + "9" * 65  # 68 raw chars, already over the column width
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0022", "equipment_name": "Other", "bcm_code": body},
    )
    assert resp.status_code in (400, 422), resp.text
    assert resp.json()["code"] in ("INVALID_INPUT", "VALIDATION_ERROR")


async def test_bcm_code_overlength_update_matches_create_behavior(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "AST-CANON-0023")
    resp = await client.patch(
        f"/api/v1/equipment/{created['id']}", headers=headers, json={"bcm_code": "9" * 64}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_item_no_overlength_is_rejected_consistently_on_create_and_update(client, seeded_users):
    """EquipmentCreate and EquipmentUpdate now share the identical
    max_length=64 schema bound on item_no (See PR5-H3R), so a 65-char raw
    value is rejected identically -- same status, same error code -- on
    both paths, at the schema layer before ever reaching normalize_item_no.
    """
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    overlength = "I" * 65

    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-CANON-0024", "equipment_name": "Other", "item_no": overlength},
    )
    assert create_resp.status_code == 422, create_resp.text
    assert create_resp.json()["code"] == "VALIDATION_ERROR"

    created = await _create_equipment_with_bcm(client, headers, "AST-CANON-0025")
    update_resp = await client.patch(
        f"/api/v1/equipment/{created['id']}", headers=headers, json={"item_no": overlength}
    )
    assert update_resp.status_code == 422, update_resp.text
    assert update_resp.json()["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Shared test vectors (tests/identifier_vectors.py): the runtime API and
# the migration 0005 CLI (tests/test_postgres_integration.py) are checked
# against the exact same inputs/expected outcomes without either test
# suite importing the other's canonicalization implementation. A vector
# both suites disagree on is a real bug, not a coverage gap -- this is
# what actually catches a "migration accepts BCM 001, runtime rejects it"
# class of regression. See PR5-H3R-MIG follow-up.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected_canonical", BCM_VALID_VECTORS)
async def test_bcm_code_vector_accepted_with_expected_canonical_value(client, seeded_users, raw, expected_canonical):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": f"AST-VEC-BCM-{uuid.uuid4().hex[:8]}", "equipment_name": "Vector", "bcm_code": raw},
    )
    assert resp.status_code == 201, f"vector {raw!r} must be accepted: {resp.text}"
    assert resp.json()["bcm_code"] == expected_canonical, f"vector {raw!r} canonicalized incorrectly"


@pytest.mark.parametrize("raw,category", BCM_INVALID_VECTORS)
async def test_bcm_code_vector_rejected_never_500(client, seeded_users, raw, category):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": f"AST-VEC-BCMX-{uuid.uuid4().hex[:8]}", "equipment_name": "Vector", "bcm_code": raw},
    )
    assert resp.status_code in (400, 422), f"vector {raw!r} ({category}) must be a controlled rejection: {resp.text}"
    assert resp.status_code < 500, f"vector {raw!r} ({category}) must never 500: {resp.text}"

    # Update must reject the same vector identically -- create/update parity.
    created = await _create_equipment_with_bcm(
        client, headers, f"AST-VEC-BCMX-UPD-{uuid.uuid4().hex[:8]}"
    )
    update_resp = await client.patch(
        f"/api/v1/equipment/{created['id']}", headers=headers, json={"bcm_code": raw}
    )
    assert update_resp.status_code in (400, 422), (
        f"vector {raw!r} ({category}) must be rejected on update too: {update_resp.text}"
    )
    assert update_resp.status_code < 500


async def test_bcm_001_specifically_is_rejected_never_rewritten(client, seeded_users):
    """The exact vector named in this round's fix: 'BCM 001' must be
    rejected by the runtime, never silently rewritten to 'BCM001'."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AST-BCM-SPACE-001", "equipment_name": "Vector", "bcm_code": "BCM 001"},
    )
    assert resp.status_code in (400, 422), resp.text
    assert resp.status_code < 500


@pytest.mark.parametrize("raw,expected_canonical", ITEM_NO_VALID_VECTORS)
async def test_item_no_vector_accepted_with_expected_canonical_value(
    client, seeded_users, raw, expected_canonical
):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": f"AST-VEC-ITEM-{uuid.uuid4().hex[:8]}", "equipment_name": "Vector", "item_no": raw},
    )
    assert resp.status_code == 201, f"vector {raw!r} must be accepted: {resp.text}"

    resolve_resp = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": expected_canonical}
    )
    assert resolve_resp.status_code == 200, (
        f"vector {raw!r} must have canonicalized to {expected_canonical!r}: {resolve_resp.text}"
    )
    assert resolve_resp.json()["id"] == resp.json()["id"]


@pytest.mark.parametrize("raw,category", ITEM_NO_INVALID_VECTORS)
async def test_item_no_vector_rejected_never_500(client, seeded_users, raw, category):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": f"AST-VEC-ITEMX-{uuid.uuid4().hex[:8]}", "equipment_name": "Vector", "item_no": raw},
    )
    assert resp.status_code in (400, 422), f"vector {raw!r} ({category}) must be a controlled rejection: {resp.text}"
    assert resp.status_code < 500, f"vector {raw!r} ({category}) must never 500: {resp.text}"


# ---------------------------------------------------------------------------
# knowledge/architecture/api-information-boundaries.md (ADR-002 / ADR-003):
# item_no must never appear in a normal operator-facing response, across
# the complete manual and QR flows. Not enforced only by hiding the field
# in the frontend -- asserted directly against the JSON response shapes.
# ---------------------------------------------------------------------------


async def test_item_no_absent_from_create_response(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(
        client, headers, "AST-BOUND-0001", bcm_code="BCM00900", item_no="ITEM-BOUND-001"
    )
    assert "item_no" not in created


async def test_item_no_absent_from_general_equipment_detail_and_list(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(
        client, headers, "AST-BOUND-0002", bcm_code="BCM00901", item_no="ITEM-BOUND-002"
    )

    detail_resp = await client.get(f"/api/v1/equipment/{created['id']}", headers=headers)
    assert detail_resp.status_code == 200
    assert "item_no" not in detail_resp.json()

    list_resp = await client.get("/api/v1/equipment", headers=headers, params={"q": "AST-BOUND-0002"})
    assert list_resp.status_code == 200
    for item in list_resp.json()["items"]:
        assert "item_no" not in item


async def test_item_no_absent_from_qr_resolution_response(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-BOUND-0003", item_no="ITEM-BOUND-003")

    resp = await client.post(
        "/api/v1/equipment/resolve-qr", headers=headers, json={"raw_value": "ITEM-BOUND-003"}
    )
    assert resp.status_code == 200
    assert "item_no" not in resp.json(), "QR resolution must not echo the Item No back to the client"


async def test_item_no_absent_from_update_response(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    created = await _create_equipment_with_bcm(client, headers, "AST-BOUND-0004")

    resp = await client.patch(
        f"/api/v1/equipment/{created['id']}", headers=headers, json={"item_no": "ITEM-BOUND-004"}
    )
    assert resp.status_code == 200
    assert "item_no" not in resp.json()


async def test_item_no_absent_from_borrow_and_return_manual_selection_responses(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    created = await _create_equipment_with_bcm(
        client, headers, "AST-BOUND-0005", bcm_code="BCM00902", item_no="ITEM-BOUND-005"
    )

    payload = await _on_demand_borrow_payload(client, headers, created["id"], ward_code="W-BOUND-0005")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx = borrow_resp.json()
    assert "item_no" not in tx["equipment"]

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"receipt_outcome": "usable"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert "item_no" not in return_resp.json()["equipment"]

# ---------------------------------------------------------------------------
# Roadmap PR6 (docs/audits/04-consolidated-implementation-plan.md, Part D):
# collapse the legacy 8-value EquipmentStatus enum to the confirmed 4-state
# model (AVAILABLE_AT_POOL, ISSUED_TO_WARD, UNAVAILABLE_DEFECTIVE,
# DECOMMISSIONED), transition enforcement, and the owner-confirmed
# retirement of `cleaning` as an active/writable status.
# ---------------------------------------------------------------------------


async def test_dispatch_rejected_when_equipment_unavailable_defective(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR6-0001")

    status_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "Broken wheel"},
    )
    assert status_resp.status_code == 200, status_resp.text

    payload = await _on_demand_borrow_payload(client, headers, equipment["id"], ward_code="W-PR6-0001")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 409
    assert borrow_resp.json()["code"] == "EQUIPMENT_NOT_AVAILABLE"


async def test_dispatch_rejected_when_equipment_decommissioned(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR6-0002")

    # Decommissioning requires passing through UNAVAILABLE_DEFECTIVE first
    # -- AVAILABLE_AT_POOL cannot skip directly to DECOMMISSIONED.
    defective_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "End of life review"},
    )
    assert defective_resp.status_code == 200, defective_resp.text

    status_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "decommissioned", "reason": "End of life"},
    )
    assert status_resp.status_code == 200, status_resp.text

    payload = await _on_demand_borrow_payload(client, headers, equipment["id"], ward_code="W-PR6-0002")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 409
    assert borrow_resp.json()["code"] == "EQUIPMENT_NOT_AVAILABLE"


async def test_dispatch_succeeds_for_available_at_pool_with_legacy_status_cleaning(
    client, seeded_users, db_session
):
    """A row left over from the pre-PR6 migration -- status=AVAILABLE_AT_POOL,
    legacy_status='cleaning' -- must be dispatchable under exactly the same
    rule as any other AVAILABLE_AT_POOL row. legacy_status must never gate
    or influence dispatch eligibility (owner-confirmed cleaning retirement)."""
    from app.models.equipment import Equipment

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR6-0003")

    row = (
        await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment["id"])))
    ).scalar_one()
    row.legacy_status = "cleaning"
    await db_session.commit()

    payload = await _on_demand_borrow_payload(client, headers, equipment["id"], ward_code="W-PR6-0003")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    assert borrow_resp.json()["equipment"]["status"] == "issued_to_ward"


async def test_decommissioned_has_no_normal_workflow_exit(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR6-0004")

    defective_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "End of life review"},
    )
    assert defective_resp.status_code == 200, defective_resp.text

    decommission_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "decommissioned", "reason": "End of life"},
    )
    assert decommission_resp.status_code == 200, decommission_resp.text

    exit_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "available_at_pool", "reason": "Attempted revival"},
    )
    assert exit_resp.status_code == 409
    assert exit_resp.json()["code"] == "INVALID_STATUS_TRANSITION"

    exit_resp_defective = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "Attempted revival"},
    )
    assert exit_resp_defective.status_code == 409
    assert exit_resp_defective.json()["code"] == "INVALID_STATUS_TRANSITION"


# PR16-H3: DECOMMISSIONED is no longer directly reachable from
# AVAILABLE_AT_POOL via the manual endpoint -- reaching it as test setup
# now requires the same two-step path (-> UNAVAILABLE_DEFECTIVE ->
# DECOMMISSIONED) a real caller must use. Every equipment row starts
# AVAILABLE_AT_POOL (the ORM default), so this only ever needs to walk
# forward from there.
_MANUAL_STATUS_PATH: dict[str, list[str]] = {
    "available_at_pool": [],
    "unavailable_defective": ["unavailable_defective"],
    "decommissioned": ["unavailable_defective", "decommissioned"],
}


async def _reach_status_via_manual_endpoint(client, headers, equipment_id, target_status):
    for step_status in _MANUAL_STATUS_PATH[target_status]:
        step_resp = await client.post(
            f"/api/v1/equipment/{equipment_id}/status", headers=headers, json={"status": step_status}
        )
        assert step_resp.status_code == 200, step_resp.text


@pytest.mark.parametrize(
    "from_status,to_status",
    [
        ("available_at_pool", "unavailable_defective"),
        ("unavailable_defective", "available_at_pool"),
        ("unavailable_defective", "decommissioned"),
    ],
)
async def test_allowed_status_transitions_succeed(client, seeded_users, from_status, to_status):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    asset_number = f"AST-PR6A-{from_status[:3]}-{to_status[:3]}-{uuid.uuid4().hex[:6]}"
    equipment = await _create_equipment_with_bcm(client, headers, asset_number)

    await _reach_status_via_manual_endpoint(client, headers, equipment["id"], from_status)

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status", headers=headers, json={"status": to_status}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == to_status


@pytest.mark.parametrize(
    "from_status,to_status",
    [
        ("available_at_pool", "available_at_pool"),
        ("available_at_pool", "decommissioned"),
        ("unavailable_defective", "issued_to_ward"),
        ("decommissioned", "available_at_pool"),
        ("decommissioned", "unavailable_defective"),
    ],
)
async def test_invalid_status_transitions_are_rejected(client, seeded_users, from_status, to_status):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    asset_number = f"AST-PR6D-{from_status[:3]}-{to_status[:3]}-{uuid.uuid4().hex[:6]}"
    equipment = await _create_equipment_with_bcm(client, headers, asset_number)

    await _reach_status_via_manual_endpoint(client, headers, equipment["id"], from_status)

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status", headers=headers, json={"status": to_status}
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"


async def test_status_change_rejects_old_eight_state_enum_value(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR6-0005")

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status", headers=headers, json={"status": "repair"}
    )
    assert resp.status_code == 422, resp.text


async def test_status_change_rejects_cleaning_as_new_active_status(client, seeded_users):
    """Retired: cleaning is never a writable status again -- only
    preserved historically via legacy_status on rows migrated before PR6."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR6-0006")

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status", headers=headers, json={"status": "cleaning"}
    )
    assert resp.status_code == 422, resp.text


async def test_return_condition_cleaning_is_rejected_not_silently_accepted(client, seeded_users):
    """Roadmap PR6: cleaning is retired. Under the Roadmap PR8B binary
    receipt_outcome contract (usable/defective), "cleaning" is impossible
    to express by construction -- a client still sending
    receipt_outcome="cleaning" gets a 422 VALIDATION_ERROR (unrecognized
    enum value), never a silent AVAILABLE_AT_POOL/legacy CLEANING
    acceptance."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR6-0007")

    payload = await _on_demand_borrow_payload(client, headers, equipment["id"], ward_code="W-PR6-0007")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx = borrow_resp.json()

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"receipt_outcome": "cleaning"}
    )
    assert return_resp.status_code == 422
    assert return_resp.json()["code"] == "VALIDATION_ERROR"


async def test_defective_receipt_transitions_to_unavailable_defective(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR6-0008")

    payload = await _on_demand_borrow_payload(client, headers, equipment["id"], ward_code="W-PR6-0008")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx = borrow_resp.json()

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"receipt_outcome": "defective"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert return_resp.json()["equipment"]["status"] == "unavailable_defective"


async def test_dashboard_summary_uses_four_state_fields(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment_with_bcm(client, headers, "AST-PR6-0009")

    resp = await client.get("/api/v1/dashboard/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Roadmap PR13: pm_due_soon/cal_due_soon are retired -- MVP-irrelevant
    # dashboard widgets per docs/audits/04-consolidated-implementation-plan.md's
    # PR13 entry. The response shape now matches exactly.
    assert set(body.keys()) == {
        "total",
        "available_at_pool",
        "issued_to_ward",
        "unavailable_defective",
        "decommissioned",
    }
    assert body["available_at_pool"] >= 1


# ---------------------------------------------------------------------------
# PR16-H2 (review of Draft PR #16): the generic admin/BME status endpoint
# must not be able to perform a dispatch or receipt transition -- those must
# stay atomic with the BorrowTransaction they create/close, which only
# app.services.borrow_service does. See app.models.equipment.
# DISPATCH_RECEIPT_TRANSITIONS / MANUAL_LIFECYCLE_TRANSITIONS and
# app.crud.equipment.change_status_for_dispatch_receipt /
# .change_status_for_manual_lifecycle.
# ---------------------------------------------------------------------------


async def test_generic_status_endpoint_cannot_synthesize_issued_to_ward(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR16-H2-0001")

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "issued_to_ward", "reason": "Attempted manual dispatch"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=headers)
    assert check_resp.json()["status"] == "available_at_pool", "status must be unchanged after the rejected attempt"


@pytest.mark.parametrize("target_status", ["available_at_pool", "unavailable_defective"])
async def test_generic_status_endpoint_cannot_return_issued_equipment(client, seeded_users, target_status):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    equipment = await _create_equipment_with_bcm(
        client, headers, f"AST-PR16-H2-RET-{target_status[:4]}-{uuid.uuid4().hex[:6]}"
    )

    payload = await _on_demand_borrow_payload(
        client, headers, equipment["id"], ward_code=f"W-PR16-RET-{uuid.uuid4().hex[:6]}"
    )
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": target_status, "reason": "Attempted manual receipt"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"


async def test_generic_status_endpoint_cannot_desynchronize_open_transaction(client, seeded_users, db_session):
    """A rejected manual-endpoint receipt attempt must leave both the
    equipment status AND the open BorrowTransaction completely untouched --
    proving the block is real, not just a response-shape difference."""
    from app.models.transaction import BorrowTransaction

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR16-H2-0002")

    payload = await _on_demand_borrow_payload(client, headers, equipment["id"], ward_code="W-PR16-H2-0002")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx_id = borrow_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "available_at_pool", "reason": "Attempted manual receipt"},
    )
    assert resp.status_code == 409, resp.text

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=headers)
    assert check_resp.json()["status"] == "issued_to_ward", "equipment must still read ISSUED_TO_WARD"

    tx_row = (
        await db_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx_id)))
    ).scalar_one()
    assert tx_row.status == "open", "the OPEN transaction must remain open (not desynchronized)"
    assert tx_row.returned_at is None


async def test_dispatch_and_return_services_still_perform_valid_transitions(client, seeded_users):
    """End-to-end proof that H2's split did not break the actual
    dispatch/receipt flows it protects -- dispatch, then a usable return,
    then (via the now-separate manual endpoint) an authorized lifecycle
    change, all still succeed."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR16-H2-0003")

    payload = await _on_demand_borrow_payload(client, headers, equipment["id"], ward_code="W-PR16-H2-0003")
    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    assert borrow_resp.json()["equipment"]["status"] == "issued_to_ward"
    tx = borrow_resp.json()

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"receipt_outcome": "usable"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert return_resp.json()["equipment"]["status"] == "available_at_pool"

    lifecycle_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "Routine inspection finding"},
    )
    assert lifecycle_resp.status_code == 200, lifecycle_resp.text
    assert lifecycle_resp.json()["status"] == "unavailable_defective"


async def test_viewer_cannot_change_equipment_status(client, seeded_users):
    """PR16-H2: auth behavior on the generic status endpoint is unchanged
    by the transition-authority split -- role enforcement still runs."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    viewer_headers = await _auth_headers(client, ROLE_READ_ONLY)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR16-H2-0004")

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=viewer_headers,
        json={"status": "unavailable_defective", "reason": "Should be forbidden"},
    )
    assert resp.status_code == 403


async def test_status_change_audit_still_records_manual_lifecycle_change(client, seeded_users, db_session):
    """PR16-H2: audit behavior on the generic endpoint's own (now
    lifecycle-only) transitions is unchanged."""
    from app.models.audit import AuditLog

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR16-H2-0005")

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "Needs inspection"},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "status_change",
                AuditLog.entity_type == "equipment",
                AuditLog.entity_id == uuid.UUID(equipment["id"]),
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].after_data == {"status": "unavailable_defective", "reason": "Needs inspection"}


# ---------------------------------------------------------------------------
# PR16-H1 / Roadmap PR8B: the receipt contract must never advertise
# "cleaning" as an acceptable value. Under the pre-PR8B `condition` string
# this was a description-text/runtime-rejection guarantee; under the
# binary `receipt_outcome` enum (this test, updated for PR8B) it is
# structural -- "cleaning" cannot appear in the schema's enum list at all.
# Runtime rejection remains covered separately (see
# test_return_condition_cleaning_is_rejected_not_silently_accepted above).
# ---------------------------------------------------------------------------


async def test_openapi_return_request_does_not_advertise_cleaning():
    import json

    from app.main import app

    schema = app.openapi()["components"]["schemas"]["ReturnRequest"]
    # Roadmap PR8B: `condition` no longer exists in the contract at all --
    # not narrowed, replaced.
    assert "condition" not in schema["properties"]
    assert "receipt_outcome" in schema["properties"]
    assert "cleaning" not in json.dumps(schema).lower()


async def test_openapi_transaction_out_receipt_outcome_is_a_typed_enum():
    """Codex review round 1, finding 3: TransactionOut.receipt_outcome must
    be emitted in the OpenAPI schema as a reference to the ReceiptOutcome
    enum, not an unconstrained string -- otherwise a client generating
    types from this schema would get `string`, not a `usable`/`defective`
    union, even though the Python-side contract is strictly binary
    (Codex review round 1, finding 2). legacy_condition_on_return, by
    contrast, is deliberately an unconstrained string -- it carries
    whatever a pre-PR8B row's raw value happened to be."""
    from app.main import app

    schemas = app.openapi()["components"]["schemas"]
    tx_schema = schemas["TransactionOut"]

    receipt_outcome_schema = tx_schema["properties"]["receipt_outcome"]
    refs = [entry["$ref"] for entry in receipt_outcome_schema.get("anyOf", []) if "$ref" in entry]
    assert refs == ["#/components/schemas/ReceiptOutcome"], (
        f"receipt_outcome must reference the ReceiptOutcome enum component, got {receipt_outcome_schema}"
    )
    assert schemas["ReceiptOutcome"]["enum"] == ["usable", "defective"]

    legacy_schema = tx_schema["properties"]["legacy_condition_on_return"]
    types = [entry.get("type") for entry in legacy_schema.get("anyOf", [])]
    assert "string" in types, "legacy_condition_on_return must remain an unconstrained string"
    assert "$ref" not in str(legacy_schema), "legacy_condition_on_return must never reference the binary enum"


# ---------------------------------------------------------------------------
# PR16-H3 (review of Draft PR #16): AVAILABLE_AT_POOL must not skip directly
# to DECOMMISSIONED -- equipment must first be classified
# UNAVAILABLE_DEFECTIVE, and only UNAVAILABLE_DEFECTIVE may move to
# DECOMMISSIONED. See app.models.equipment.MANUAL_LIFECYCLE_TRANSITIONS.
# ---------------------------------------------------------------------------


async def test_available_at_pool_cannot_skip_directly_to_decommissioned(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR16-H3-0001")

    resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "decommissioned", "reason": "Attempted direct skip"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=headers)
    assert check_resp.json()["status"] == "available_at_pool", "status must be unchanged after the rejected attempt"


async def test_decommission_requires_passing_through_unavailable_defective(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    equipment = await _create_equipment_with_bcm(client, headers, "AST-PR16-H3-0002")

    defective_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "Failed inspection"},
    )
    assert defective_resp.status_code == 200, defective_resp.text
    assert defective_resp.json()["status"] == "unavailable_defective"

    decommission_resp = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status",
        headers=headers,
        json={"status": "decommissioned", "reason": "End of life"},
    )
    assert decommission_resp.status_code == 200, decommission_resp.text
    assert decommission_resp.json()["status"] == "decommissioned"
