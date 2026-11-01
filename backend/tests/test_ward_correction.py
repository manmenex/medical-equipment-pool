import uuid

import pytest

from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward
from tests.conftest import on_demand_borrow_payload as _on_demand_borrow_payload

pytestmark = pytest.mark.asyncio


async def _create_equipment(client, headers, asset_number="AST-WC-0001", name="Infusion Pump"):
    resp = await client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": asset_number, "equipment_name": name}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _dispatch_open_transaction(client, headers, *, asset_number, ward_code):
    """Dispatches one piece of equipment and returns (transaction_json, ward_id)."""
    equipment = await _create_equipment(client, headers, asset_number=asset_number)
    payload = await _on_demand_borrow_payload(client, headers, equipment["id"], ward_code=ward_code)
    resp = await client.post("/api/v1/borrow", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json(), payload["ward_id"]


async def _correct_ward(client, headers, tx_id, *, ward_id, reason="Correcting a misrecorded ward"):
    return await client.post(
        f"/api/v1/transactions/{tx_id}/correct-ward", headers=headers, json={"ward_id": ward_id, "reason": reason}
    )


# ---------------------------------------------------------------------------
# Authorization -- confirmed 3-role permission matrix (Roadmap PR10): ward
# correction is granted to Administrator and Equipment Pool Staff (the two
# roles with an ongoing equipment-operations responsibility) and denied to
# Read Only. See app.api.v1.deps.WARD_CORRECTION_ROLES's docstring for the
# full rationale -- this must not be inferred from, or claimed to match,
# the roles trusted by dispatch (app.api.v1.borrow.BORROW_ROLES) or
# receipt, even though they happen to be the same set today.
# ---------------------------------------------------------------------------

_WARD_CORRECTION_ROLE_MATRIX = [
    (ROLE_ADMINISTRATOR, 200),
    (ROLE_EQUIPMENT_POOL_STAFF, 200),
    (ROLE_READ_ONLY, 403),
]


@pytest.mark.parametrize("role, expected_status", _WARD_CORRECTION_ROLE_MATRIX)
async def test_ward_correction_temporary_permission_matrix(client, seeded_users, db_session, role, expected_status):
    """Exercises the complete confirmed permission matrix: Administrator and
    Equipment Pool Staff are granted (200); Read Only is denied (403). Every
    granted case also confirms a successful correction creates exactly one
    audit entry (the mandatory audit requirement, not just the
    authorization outcome)."""
    from sqlalchemy import select

    from app.models.audit import AuditLog

    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    actor_headers = await _auth_headers(client, role)
    tx, original_ward_id = await _dispatch_open_transaction(
        client, admin_headers, asset_number=f"AST-WC-ROLE-{role}", ward_code=f"W-WC-R-{role[:8]}"
    )
    new_ward_id = await _create_ward(client, admin_headers, f"W-WC-R2-{role[:8]}")

    resp = await _correct_ward(client, actor_headers, tx["id"], ward_id=new_ward_id)
    assert resp.status_code == expected_status, resp.text

    if expected_status == 200:
        assert resp.json()["ward_id"] == new_ward_id
        assert resp.json()["ward_id"] != original_ward_id

        audit_rows = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "ward_correction",
                    AuditLog.entity_id == uuid.UUID(tx["id"]),
                )
            )
        ).scalars().all()
        assert len(audit_rows) == 1, "a successful admin correction must create exactly one audit entry"


# ---------------------------------------------------------------------------
# Request contract validation (required tests 4-8)
# ---------------------------------------------------------------------------


async def test_missing_reason_is_rejected(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(client, admin_headers, asset_number="AST-WC-NOREASON", ward_code="W-WC-NR-1")
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-NR-2")

    resp = await client.post(
        f"/api/v1/transactions/{tx['id']}/correct-ward", headers=admin_headers, json={"ward_id": new_ward_id}
    )
    assert resp.status_code == 422, resp.text


async def test_blank_reason_is_rejected(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(client, admin_headers, asset_number="AST-WC-BLANK", ward_code="W-WC-BLANK-1")
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-BLANK-2")

    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=new_ward_id, reason="    ")
    assert resp.status_code == 422, resp.text


async def test_unknown_request_field_is_rejected(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(client, admin_headers, asset_number="AST-WC-EXTRA", ward_code="W-WC-EXTRA-1")
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-EXTRA-2")

    resp = await client.post(
        f"/api/v1/transactions/{tx['id']}/correct-ward",
        headers=admin_headers,
        json={"ward_id": new_ward_id, "reason": "Fixing it", "status": "closed"},
    )
    assert resp.status_code == 422, resp.text


async def test_missing_ward_id_is_rejected(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(client, admin_headers, asset_number="AST-WC-NOWARD", ward_code="W-WC-NOWARD-1")

    resp = await client.post(
        f"/api/v1/transactions/{tx['id']}/correct-ward", headers=admin_headers, json={"reason": "Fixing it"}
    )
    assert resp.status_code == 422, resp.text


async def test_invalid_ward_id_is_rejected(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-BADWARD", ward_code="W-WC-BADWARD-1"
    )

    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id="not-a-real-uuid")
    assert resp.status_code == 422, resp.text


async def test_nonexistent_ward_id_is_rejected(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-GHOSTWARD", ward_code="W-WC-GHOSTWARD-1"
    )

    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=str(uuid.uuid4()))
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_unknown_transaction_is_rejected(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-UNKNOWNTX")

    resp = await _correct_ward(client, admin_headers, str(uuid.uuid4()), ward_id=new_ward_id)
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "TRANSACTION_NOT_FOUND"


# ---------------------------------------------------------------------------
# Reason boundary and whitespace (declared contract:
# app.schemas.transaction.WARD_CORRECTION_REASON_MAX_LENGTH == 500)
# ---------------------------------------------------------------------------


async def test_reason_at_exactly_the_max_length_is_accepted_and_audited(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.schemas.transaction import WARD_CORRECTION_REASON_MAX_LENGTH

    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-MAXLEN", ward_code="W-WC-MAXLEN-1"
    )
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-MAXLEN-2")

    reason = "x" * WARD_CORRECTION_REASON_MAX_LENGTH
    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=new_ward_id, reason=reason)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ward_id"] == new_ward_id

    audit_row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "ward_correction",
                AuditLog.entity_id == uuid.UUID(tx["id"]),
            )
        )
    ).scalar_one()
    assert audit_row.after_data["reason"] == reason
    assert len(audit_row.after_data["reason"]) == WARD_CORRECTION_REASON_MAX_LENGTH


async def test_reason_one_character_over_the_max_length_is_rejected(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.schemas.transaction import WARD_CORRECTION_REASON_MAX_LENGTH

    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, original_ward_id = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-OVERLEN", ward_code="W-WC-OVERLEN-1"
    )
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-OVERLEN-2")

    reason = "x" * (WARD_CORRECTION_REASON_MAX_LENGTH + 1)
    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=new_ward_id, reason=reason)
    assert resp.status_code == 422, resp.text

    get_resp = await client.get(f"/api/v1/transactions/{tx['id']}", headers=admin_headers)
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["ward_id"] == original_ward_id, "an over-length reason must never change the ward"

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "ward_correction",
                AuditLog.entity_id == uuid.UUID(tx["id"]),
            )
        )
    ).scalars().all()
    assert audit_rows == [], "a rejected over-length request must not write an audit row"


async def test_reason_surrounding_whitespace_is_trimmed_before_storage(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog

    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-TRIM", ward_code="W-WC-TRIM-1"
    )
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-TRIM-2")

    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=new_ward_id, reason="  valid reason  ")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ward_id"] == new_ward_id

    audit_row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "ward_correction",
                AuditLog.entity_id == uuid.UUID(tx["id"]),
            )
        )
    ).scalar_one()
    assert audit_row.after_data["reason"] == "valid reason", "the audited reason must be trimmed before storage"


# ---------------------------------------------------------------------------
# Same-ward no-op (required test 9)
# ---------------------------------------------------------------------------


async def test_same_ward_correction_is_rejected_without_an_audit_entry(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog

    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, original_ward_id = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-NOOP", ward_code="W-WC-NOOP-1"
    )

    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=original_ward_id)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "WARD_CORRECTION_NOOP"
    # Deliberately distinct from the receipt-flow conflict codes (Roadmap PR8C).
    assert resp.json()["code"] not in {"TRANSACTION_ALREADY_RETURNED", "RECEIPT_RACE_LOST"}

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "ward_correction",
                AuditLog.entity_id == uuid.UUID(tx["id"]),
            )
        )
    ).scalars().all()
    assert audit_rows == [], "a rejected no-op must not write an audit row"


# ---------------------------------------------------------------------------
# OPEN vs CLOSED (required tests 10-11)
# ---------------------------------------------------------------------------


async def test_open_transaction_can_be_corrected(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(client, admin_headers, asset_number="AST-WC-OPEN", ward_code="W-WC-OPEN-1")
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-OPEN-2")
    assert tx["status"] == "open"

    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=new_ward_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "open", "ward correction must never change the transaction lifecycle state"
    assert resp.json()["ward_id"] == new_ward_id


async def test_closed_transaction_can_be_corrected(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(client, admin_headers, asset_number="AST-WC-CLOSED", ward_code="W-WC-CLOSED-1")
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-CLOSED-2")

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=admin_headers, json={"receipt_outcome": "usable"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert return_resp.json()["status"] == "closed"

    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=new_ward_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "closed", "ward correction must never change the transaction lifecycle state"
    assert resp.json()["ward_id"] == new_ward_id


# ---------------------------------------------------------------------------
# Only ward_id changes (required test 12)
# ---------------------------------------------------------------------------


async def test_only_ward_id_changes(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(client, admin_headers, asset_number="AST-WC-ONLYWARD", ward_code="W-WC-OW-1")
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-OW-2")

    before = tx
    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=new_ward_id)
    assert resp.status_code == 200, resp.text
    after = resp.json()

    assert after["ward_id"] == new_ward_id
    unchanged_fields = [
        "id",
        "transaction_no",
        "quantity",
        "borrowed_at",
        "returned_at",
        "borrower_name",
        "dispatch_type",
        "routine_round",
        "phone_number",
        "receipt_outcome",
        "legacy_condition_on_return",
        "status",
        "notes",
    ]
    for field in unchanged_fields:
        assert after[field] == before[field], f"ward correction must not change {field!r}"
    assert after["equipment"]["id"] == before["equipment"]["id"]
    assert after["equipment"]["status"] == before["equipment"]["status"], (
        "ward correction must never change equipment lifecycle state"
    )


# ---------------------------------------------------------------------------
# Audit (required tests 13-15)
# ---------------------------------------------------------------------------


async def test_exactly_one_audit_entry_is_created(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog

    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(client, admin_headers, asset_number="AST-WC-AUDIT1", ward_code="W-WC-A1-1")
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-A1-2")

    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=new_ward_id)
    assert resp.status_code == 200, resp.text

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "ward_correction",
                AuditLog.entity_id == uuid.UUID(tx["id"]),
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 1, f"expected exactly one audit row, got {len(audit_rows)}"


async def test_audit_captures_actor_target_before_after_and_reason(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.models.user import User

    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, original_ward_id = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-AUDIT2", ward_code="W-WC-A2-1"
    )
    new_ward_id = await _create_ward(client, admin_headers, "W-WC-A2-2")

    reason = "Ward was misread from the phone request"
    resp = await _correct_ward(client, admin_headers, tx["id"], ward_id=new_ward_id, reason=reason)
    assert resp.status_code == 200, resp.text

    admin_user = (
        await db_session.execute(select(User).where(User.employee_code == f"{ROLE_ADMINISTRATOR.upper()}001"))
    ).scalar_one()

    audit_row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "ward_correction",
                AuditLog.entity_id == uuid.UUID(tx["id"]),
            )
        )
    ).scalar_one()

    assert audit_row.user_id == admin_user.id, "audit must capture the actor"
    assert audit_row.entity_type == "borrow_transaction"
    assert audit_row.entity_id == uuid.UUID(tx["id"]), "audit must capture the target transaction"
    assert audit_row.before_data == {"ward_id": original_ward_id}, "audit must capture the previous ward"
    assert audit_row.after_data["ward_id"] == new_ward_id, "audit must capture the new ward"
    assert audit_row.after_data["reason"] == reason, "audit must capture the mandatory reason"
    # Request/correlation metadata the audit framework already supports
    # (app.core.audit.record_audit_event) -- captured for this action too,
    # not only for equipment/master-data audit rows.
    assert audit_row.ip_address is not None


async def test_audit_write_failure_rolls_back_the_ward_change(db_session, monkeypatch):
    """Roadmap PR9A atomicity requirement: if the audit write fails, the
    ward_id UPDATE must not persist either -- both succeed or neither does.
    Calls app.services.borrow_service.correct_ward directly (not through the
    HTTP client) so this test's own db_session sees the same, still-open
    transaction the service used, and can assert on it after an explicit
    rollback -- the HTTP client's per-request session would already have
    closed (and therefore rolled back) by the time an assertion could run.
    """
    from app.crud import audit as audit_crud
    from app.models.equipment import Equipment
    from app.models.master_data import Ward
    from app.models.transaction import BorrowTransaction
    from app.services import borrow_service

    equipment = Equipment(asset_number="AST-WC-ROLLBACK", equipment_name="Pump")
    ward_a = Ward(code="W-WC-RB-1", name="W-WC-RB-1")
    ward_b = Ward(code="W-WC-RB-2", name="W-WC-RB-2")
    db_session.add_all([equipment, ward_a, ward_b])
    await db_session.flush()

    tx = BorrowTransaction(transaction_no="TX-WC-ROLLBACK", equipment_id=equipment.id, ward_id=ward_a.id)
    db_session.add(tx)
    # Committed (not just flushed) before the correction attempt: the
    # rollback below must undo only correct_ward()'s own attempted changes,
    # not this setup data -- a rollback of never-committed rows would expunge
    # them from the session entirely, and db.refresh(tx) requires tx to still
    # be a persistent row afterward.
    await db_session.commit()
    # Captured as plain values before any rollback: Session.rollback()
    # expires every object still tracked by the session, and a bare
    # attribute access on an expired ORM object outside an explicit
    # await-based refresh raises under this project's async engine.
    tx_id, ward_a_id, ward_b_id = tx.id, ward_a.id, ward_b.id

    async def _failing_audit_create(*args, **kwargs):
        raise RuntimeError("simulated audit-subsystem failure")

    monkeypatch.setattr(audit_crud, "create", _failing_audit_create)

    with pytest.raises(RuntimeError):
        await borrow_service.correct_ward(
            db_session,
            transaction_id=tx_id,
            new_ward_id=ward_b_id,
            reason="Should never persist",
            actor_user_id=uuid.uuid4(),
            request=None,
        )

    await db_session.rollback()
    await db_session.refresh(tx)
    assert tx.ward_id == ward_a_id, "an audit-write failure must roll back the ward change too"


# ---------------------------------------------------------------------------
# Immutability outside the correction action (required tests 16-17)
# ---------------------------------------------------------------------------


async def test_receipt_path_leaves_ward_unchanged(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, original_ward_id = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-RECEIPT", ward_code="W-WC-RECEIPT-1"
    )

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=admin_headers, json={"receipt_outcome": "usable"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert return_resp.json()["ward_id"] == original_ward_id, "receipt must never change ward_id"


async def test_receipt_request_schema_rejects_a_ward_id_field(client, seeded_users):
    """Structural guarantee, independent of the behavioral check above:
    ReturnRequest's `extra: "forbid"` (Roadmap PR8B) means a caller cannot
    even submit ward_id to the receipt endpoint -- it is rejected at
    request-validation time, before any service code runs."""
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, original_ward_id = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-RECEIPT-SCHEMA", ward_code="W-WC-RECEIPT-SCHEMA-1"
    )

    resp = await client.post(
        f"/api/v1/return/{tx['id']}",
        headers=admin_headers,
        json={"receipt_outcome": "usable", "ward_id": original_ward_id},
    )
    assert resp.status_code == 422, resp.text


async def test_dispatch_creates_the_initial_ward_id(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    ward_id = await _create_ward(client, admin_headers, "W-WC-DISPATCH-1")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-WC-DISPATCH")

    resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={"equipment_id": equipment["id"], "ward_id": ward_id, "dispatch_type": "on_demand"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["ward_id"] == ward_id


async def test_no_generic_transaction_mutation_route_exists(client, seeded_users):
    """There is no PATCH/PUT on /transactions/{id} -- the only way to change
    ward_id after dispatch is the narrow, audited correction action."""
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    tx, _ = await _dispatch_open_transaction(
        client, admin_headers, asset_number="AST-WC-NOPATCH", ward_code="W-WC-NOPATCH-1"
    )

    patch_resp = await client.patch(
        f"/api/v1/transactions/{tx['id']}", headers=admin_headers, json={"ward_id": str(uuid.uuid4())}
    )
    assert patch_resp.status_code == 405, patch_resp.text

    put_resp = await client.put(
        f"/api/v1/transactions/{tx['id']}", headers=admin_headers, json={"ward_id": str(uuid.uuid4())}
    )
    assert put_resp.status_code == 405, put_resp.text


async def test_repository_correct_ward_second_call_on_stale_read_reports_conflict(db_session):
    """Repository-level (app.crud.transaction) proof of the concurrency
    guard, independent of the HTTP layer: correct_ward() is a conditional
    UPDATE guarded by the ward_id value the caller read -- a second call
    using a now-stale expected_ward_id must report the loss (rowcount == 0)
    and must not overwrite the first call's winning value. Real concurrent
    HTTP-request behavior against PostgreSQL is proven in
    tests/test_postgres_integration.py."""
    from app.crud import transaction as transaction_crud
    from app.models.equipment import Equipment
    from app.models.master_data import Ward

    equipment = Equipment(asset_number="AST-WC-REPO", equipment_name="Pump")
    ward_a = Ward(code="W-WC-REPO-1", name="W-WC-REPO-1")
    ward_b = Ward(code="W-WC-REPO-2", name="W-WC-REPO-2")
    ward_c = Ward(code="W-WC-REPO-3", name="W-WC-REPO-3")
    db_session.add_all([equipment, ward_a, ward_b, ward_c])
    await db_session.flush()

    from app.models.transaction import BorrowTransaction

    tx = BorrowTransaction(transaction_no="TX-WC-REPO", equipment_id=equipment.id, ward_id=ward_a.id)
    db_session.add(tx)
    await db_session.flush()

    won_first = await transaction_crud.correct_ward(db_session, tx, expected_ward_id=ward_a.id, new_ward_id=ward_b.id)
    assert won_first is True

    # Stand-in for a losing concurrent request: still expects the original
    # ward_a value, which is no longer current.
    won_second = await transaction_crud.correct_ward(
        db_session, tx, expected_ward_id=ward_a.id, new_ward_id=ward_c.id
    )
    assert won_second is False, "a stale expected_ward_id must report rowcount == 0, never silently overwrite"

    await db_session.refresh(tx, attribute_names=["ward_id"])
    assert tx.ward_id == ward_b.id, "the loser must not overwrite the winner's ward_id"


async def test_repository_correct_ward_handles_a_null_original_ward(db_session):
    """ward_id is nullable (a transaction predating Roadmap PR7b's
    required-ward_id rule may have none) -- the conditional UPDATE's
    IS NOT DISTINCT FROM comparison must still match a NULL expected value,
    not permanently report a false conflict for these rows."""
    from app.crud import transaction as transaction_crud
    from app.models.equipment import Equipment
    from app.models.master_data import Ward
    from app.models.transaction import BorrowTransaction

    equipment = Equipment(asset_number="AST-WC-NULLWARD", equipment_name="Pump")
    ward = Ward(code="W-WC-NULLWARD-1", name="W-WC-NULLWARD-1")
    db_session.add_all([equipment, ward])
    await db_session.flush()

    tx = BorrowTransaction(transaction_no="TX-WC-NULLWARD", equipment_id=equipment.id, ward_id=None)
    db_session.add(tx)
    await db_session.flush()

    won = await transaction_crud.correct_ward(db_session, tx, expected_ward_id=None, new_ward_id=ward.id)
    assert won is True, "a null current ward_id must still be matched by IS NOT DISTINCT FROM"

    await db_session.refresh(tx, attribute_names=["ward_id"])
    assert tx.ward_id == ward.id
