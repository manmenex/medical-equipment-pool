import io
import uuid

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.equipment import Equipment, EquipmentStatus
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.services.import_service import REQUIRED_HEADERS
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio


def _build_workbook(rows: list[dict[str, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(list(REQUIRED_HEADERS))
    for row in rows:
        ws.append([row.get(header, "") for header in REQUIRED_HEADERS])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _base_row(**overrides) -> dict[str, str]:
    row = {
        "Item No.": "",
        "ID CODE": "001",
        "Asset ID": "",
        "Equipment Name": "Infusion Pump",
        "Manufacturer": "Acme",
        "Model": "X1",
        "Serial Number": "",
        "Location": "Ward 3",
        "Receive Date": "2024-01-01",
        "Register Date": "2024-01-02",
        "Purchase Year": "2023",
        "Asset Status": "Active",
    }
    row.update(overrides)
    return row


def _upload(rows: list[dict[str, str]], filename: str = "inventory.xlsx"):
    content = _build_workbook(rows)
    return {"file": (filename, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


async def _preview(client, headers, rows, *, update_existing: bool = False):
    return await client.post(
        "/api/v1/import/preview",
        headers=headers,
        files=_upload(rows),
        data={"update_existing": "true" if update_existing else "false"},
    )


async def _commit(client, headers, rows, *, update_existing: bool = False):
    return await client.post(
        "/api/v1/import/commit",
        headers=headers,
        files=_upload(rows),
        data={"update_existing": "true" if update_existing else "false"},
    )


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def test_non_admin_forbidden_from_preview(client, seeded_users):
    for role in (ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        resp = await _preview(client, headers, [_base_row()])
        assert resp.status_code == 403


async def test_non_admin_forbidden_from_commit(client, seeded_users):
    headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await _commit(client, headers, [_base_row()])
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Header validation
# ---------------------------------------------------------------------------


async def test_missing_required_header_rejects_whole_file(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    wb = Workbook()
    ws = wb.active
    incomplete_headers = [h for h in REQUIRED_HEADERS if h != "Asset Status"]
    ws.append(incomplete_headers)
    ws.append(["x"] * len(incomplete_headers))
    buf = io.BytesIO()
    wb.save(buf)
    resp = await client.post(
        "/api/v1/import/preview",
        headers=headers,
        files={"file": ("bad.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"update_existing": "false"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"
    assert "Asset Status" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Row-level validation (Part G.4)
# ---------------------------------------------------------------------------


async def test_missing_bcm_code_fails_row(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await _preview(client, headers, [_base_row(**{"ID CODE": ""})])
    assert resp.status_code == 200
    body = resp.json()
    assert body["failed"] == 1
    assert body["rows"][0]["status"] == "failed"
    assert "BCM Code" in body["rows"][0]["reason"]


async def test_duplicate_bcm_code_within_file_flags_all_occurrences(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    rows = [_base_row(**{"ID CODE": "777"}), _base_row(**{"ID CODE": "777"})]
    resp = await _preview(client, headers, rows)
    body = resp.json()
    assert body["failed"] == 2
    assert all(r["status"] == "failed" and "Duplicate BCM Code" in r["reason"] for r in body["rows"])


async def test_leading_zero_bcm_code_round_trip(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await _commit(client, headers, [_base_row(**{"ID CODE": "00042"})])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["succeeded"] == 1
    assert body["rows"][0]["bcm_code"] == "BCM00042"


async def test_unrecognized_asset_status_fails_row(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await _preview(client, headers, [_base_row(**{"Asset Status": "Mystery Value"})])
    body = resp.json()
    assert body["failed"] == 1
    assert "Unrecognized Asset Status" in body["rows"][0]["reason"]


async def test_duplicate_serial_number_within_file_flagged(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    rows = [
        _base_row(**{"ID CODE": "101", "Serial Number": "SN-1"}),
        _base_row(**{"ID CODE": "102", "Serial Number": "SN-1"}),
    ]
    resp = await _preview(client, headers, rows)
    body = resp.json()
    assert body["failed"] == 2
    assert all("Duplicate Serial Number" in r["reason"] for r in body["rows"])


async def test_partial_row_failure_still_commits_valid_rows(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    rows = [
        _base_row(**{"ID CODE": "201"}),
        _base_row(**{"ID CODE": ""}),  # invalid, missing BCM
        _base_row(**{"ID CODE": "202"}),
    ]
    resp = await _commit(client, headers, rows)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 1

    result = await db_session.execute(select(Equipment).where(Equipment.bcm_code.in_(["BCM201", "BCM202"])))
    assert len(result.scalars().all()) == 2


# ---------------------------------------------------------------------------
# Database-duplicate handling / update mode
# ---------------------------------------------------------------------------


async def test_db_duplicate_bcm_skipped_when_update_mode_off(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    row = _base_row(**{"ID CODE": "301"})
    first = await _commit(client, headers, [row])
    assert first.json()["succeeded"] == 1

    second = await _commit(client, headers, [row], update_existing=False)
    body = second.json()
    assert body["skipped"] == 1
    assert body["succeeded"] == 0
    assert "update mode is off" in body["rows"][0]["reason"]


async def test_db_duplicate_bcm_updates_master_data_when_update_mode_on(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    row = _base_row(**{"ID CODE": "302", "Model": "Original"})
    first = await _commit(client, headers, [row])
    equipment_id = first.json()["rows"][0]["equipment_id"]

    updated_row = _base_row(**{"ID CODE": "302", "Model": "Revised"})
    second = await _commit(client, headers, [updated_row], update_existing=True)
    body = second.json()
    assert body["succeeded"] == 1
    assert body["rows"][0]["action"] == "update"
    assert body["rows"][0]["equipment_id"] == equipment_id

    result = await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
    equipment = result.scalar_one()
    assert equipment.model == "Revised"


async def test_update_mode_never_touches_status_or_legacy_status(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    row = _base_row(**{"ID CODE": "303", "Asset Status": "Active"})
    first = await _commit(client, headers, [row])
    equipment_id = first.json()["rows"][0]["equipment_id"]

    result = await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
    equipment = result.scalar_one()
    equipment.status = EquipmentStatus.UNAVAILABLE_DEFECTIVE
    equipment.legacy_status = "manually_set"
    await db_session.commit()

    # Re-import the same BCM Code with a *different* Asset Status in update
    # mode -- status/legacy_status must remain exactly as manually set above.
    updated_row = _base_row(**{"ID CODE": "303", "Asset Status": "Decommissioned"})
    second = await _commit(client, headers, [updated_row], update_existing=True)
    assert second.json()["succeeded"] == 1

    result2 = await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
    equipment2 = result2.scalar_one()
    assert equipment2.status.value == "unavailable_defective"
    assert equipment2.legacy_status == "manually_set"


async def test_update_mode_rejects_row_whose_item_no_belongs_to_a_different_record(client, seeded_users):
    """Review finding PR12-H3: Create mode has always rejected an Item No
    that belongs to a different equipment record; update mode must apply
    the same cross-record check, even though it never writes Item No
    itself."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _commit(client, headers, [_base_row(**{"ID CODE": "901", "Item No.": "ITEM-OTHER"})])
    await _commit(client, headers, [_base_row(**{"ID CODE": "902"})])

    conflicting_row = _base_row(**{"ID CODE": "902", "Item No.": "ITEM-OTHER"})
    resp = await _commit(client, headers, [conflicting_row], update_existing=True)
    body = resp.json()
    assert body["failed"] == 1
    assert "Item No" in body["rows"][0]["reason"]


async def test_update_mode_rejects_row_whose_serial_number_belongs_to_a_different_record(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _commit(client, headers, [_base_row(**{"ID CODE": "903", "Serial Number": "SN-OTHER"})])
    await _commit(client, headers, [_base_row(**{"ID CODE": "904"})])

    conflicting_row = _base_row(**{"ID CODE": "904", "Serial Number": "SN-OTHER"})
    resp = await _commit(client, headers, [conflicting_row], update_existing=True)
    body = resp.json()
    assert body["failed"] == 1
    assert "Serial Number" in body["rows"][0]["reason"]


async def test_update_mode_allows_row_whose_item_no_and_serial_number_belong_to_the_same_record(
    client, seeded_users, db_session
):
    """A value that already belongs to the *same* BCM-matched record is
    not a conflict -- re-importing an unchanged row in update mode must
    still succeed."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    row = _base_row(**{"ID CODE": "905", "Item No.": "ITEM905", "Serial Number": "SN905"})
    first = await _commit(client, headers, [row])
    equipment_id = first.json()["rows"][0]["equipment_id"]

    second = await _commit(client, headers, [row], update_existing=True)
    body = second.json()
    assert body["succeeded"] == 1
    assert body["rows"][0]["action"] == "update"
    assert body["rows"][0]["equipment_id"] == equipment_id


# ---------------------------------------------------------------------------
# Asset ID conservative duplicate detection (approved treatment)
# ---------------------------------------------------------------------------


async def test_asset_id_duplicate_in_file_flagged_but_others_unaffected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    rows = [
        _base_row(**{"ID CODE": "401", "Asset ID": "A-1"}),
        _base_row(**{"ID CODE": "402", "Asset ID": "A-1"}),
        _base_row(**{"ID CODE": "403", "Asset ID": "A-2"}),
    ]
    resp = await _commit(client, headers, rows)
    body = resp.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 2
    by_bcm = {r["bcm_code"]: r for r in body["rows"]}
    assert by_bcm["BCM401"]["status"] == "failed"
    assert by_bcm["BCM402"]["status"] == "failed"
    assert by_bcm["BCM403"]["status"] == "success"


async def test_asset_id_duplicate_against_existing_db_row_flagged(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _commit(client, headers, [_base_row(**{"ID CODE": "501", "Asset ID": "DUP-ASSET"})])

    resp = await _commit(client, headers, [_base_row(**{"ID CODE": "502", "Asset ID": "DUP-ASSET"})])
    body = resp.json()
    assert body["failed"] == 1
    assert "Asset ID" in body["rows"][0]["reason"]


async def test_no_unique_constraint_added_for_asset_id(db_session):
    """Roadmap PR12 approved treatment: asset_id must never gain a
    database uniqueness constraint (hospital-wide uniqueness unconfirmed).
    Two equipment rows sharing an asset_id must be a valid database
    state -- only application-layer import validation flags it."""
    from app.crud import equipment as equipment_crud

    e1 = await equipment_crud.create(
        db_session,
        data={"asset_number": "AST-D1", "equipment_name": "A", "asset_id": "SHARED"},
    )
    e2 = await equipment_crud.create(
        db_session,
        data={"asset_number": "AST-D2", "equipment_name": "B", "asset_id": "SHARED"},
    )
    await db_session.commit()
    assert e1.asset_id == e2.asset_id == "SHARED"


# ---------------------------------------------------------------------------
# asset_number placeholder policy (review finding PR12-H1 / ADR-002)
# ---------------------------------------------------------------------------


async def test_new_equipment_asset_number_is_random_placeholder_not_derived_from_bcm_or_item_no(
    client, seeded_users, db_session
):
    """ADR-002: Asset Number must never be "merged with, or inferred
    from, BCM Code or Item No." The import source file has no Asset
    Number column, so a newly created row gets an opaque random
    placeholder token, never a value derived from its own BCM Code or
    Item No."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await _commit(client, headers, [_base_row(**{"ID CODE": "601", "Item No.": "ITEM601"})])
    equipment_id = resp.json()["rows"][0]["equipment_id"]
    result = await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
    equipment = result.scalar_one()
    assert equipment.bcm_code == "BCM601"
    assert equipment.item_no == "ITEM601"
    assert equipment.asset_number.startswith("IMPORT-")
    assert "601" not in equipment.asset_number
    assert equipment.asset_number != equipment.bcm_code
    assert equipment.asset_number != equipment.item_no


async def test_asset_number_placeholders_are_unique_across_a_batch(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    rows = [_base_row(**{"ID CODE": "611"}), _base_row(**{"ID CODE": "612"}), _base_row(**{"ID CODE": "613"})]
    resp = await _commit(client, headers, rows)
    body = resp.json()
    assert body["succeeded"] == 3
    equipment_ids = [uuid.UUID(r["equipment_id"]) for r in body["rows"]]
    result = await db_session.execute(select(Equipment).where(Equipment.id.in_(equipment_ids)))
    asset_numbers = {e.asset_number for e in result.scalars().all()}
    assert len(asset_numbers) == 3


# ---------------------------------------------------------------------------
# Preview vs. commit isolation
# ---------------------------------------------------------------------------


async def test_preview_performs_zero_database_writes(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    before_equipment = (await db_session.execute(select(Equipment))).scalars().all()
    before_audit = (await db_session.execute(select(AuditLog))).scalars().all()

    resp = await _preview(client, headers, [_base_row(**{"ID CODE": "701"})])
    assert resp.status_code == 200
    assert resp.json()["succeeded"] == 1

    after_equipment = (await db_session.execute(select(Equipment))).scalars().all()
    after_audit = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(after_equipment) == len(before_equipment)
    assert len(after_audit) == len(before_audit)


async def test_commit_does_not_require_a_prior_preview_call(client, seeded_users):
    """Commit independently re-parses/re-validates the raw uploaded file
    -- it never depends on or trusts a client-supplied preview result."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await _commit(client, headers, [_base_row(**{"ID CODE": "702"})])
    assert resp.status_code == 200
    assert resp.json()["succeeded"] == 1


async def test_commit_produces_exactly_one_audit_log_entry_per_batch(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    before = (await db_session.execute(select(AuditLog).where(AuditLog.action == "import"))).scalars().all()

    rows = [_base_row(**{"ID CODE": "801"}), _base_row(**{"ID CODE": "802"}), _base_row(**{"ID CODE": ""})]
    resp = await _commit(client, headers, rows)
    body = resp.json()
    assert body["audit_log_id"] is not None

    after = (await db_session.execute(select(AuditLog).where(AuditLog.action == "import"))).scalars().all()
    assert len(after) == len(before) + 1
    entry = [a for a in after if str(a.id) == body["audit_log_id"]][0]
    assert entry.after_data["succeeded"] == 2
    assert entry.after_data["failed"] == 1


# ---------------------------------------------------------------------------
# Upload bounds (review finding PR12-H2)
# ---------------------------------------------------------------------------


async def test_oversized_upload_rejected_before_parsing(client, seeded_users):
    from app.services import import_service

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    oversized = b"x" * (import_service.MAX_UPLOAD_BYTES + 1)
    resp = await client.post(
        "/api/v1/import/preview",
        headers=headers,
        files={"file": ("big.xlsx", oversized, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"update_existing": "false"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"
    assert "maximum allowed size" in resp.json()["detail"]


async def test_too_many_rows_rejected(client, seeded_users):
    from app.services import import_service

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    rows = [_base_row(**{"ID CODE": str(1000 + i)}) for i in range(import_service.MAX_IMPORT_ROWS + 1)]
    resp = await _preview(client, headers, rows)
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"
    assert "maximum a single import batch" in resp.json()["detail"]


async def test_filename_exceeding_max_length_rejected(client, seeded_users):
    from app.services import import_service

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    long_name = ("a" * (import_service.MAX_FILENAME_LENGTH + 1)) + ".xlsx"
    content = _build_workbook([_base_row()])
    resp = await client.post(
        "/api/v1/import/preview",
        headers=headers,
        files={"file": (long_name, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"update_existing": "false"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"
    assert "Filename exceeds" in resp.json()["detail"]


async def test_non_xlsx_extension_rejected(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    content = _build_workbook([_base_row()])
    resp = await client.post(
        "/api/v1/import/preview",
        headers=headers,
        files={"file": ("inventory.csv", content, "text/csv")},
        data={"update_existing": "false"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"
    assert "Only .xlsx files are supported" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Preview-phase field length validation (review finding PR12-H4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,header",
    [
        ("Asset ID", "Asset ID"),
        ("Serial Number", "Serial Number"),
        ("Equipment Name", "Equipment Name"),
        ("Manufacturer", "Manufacturer"),
        ("Model", "Model"),
        ("Asset Status", "Asset Status"),
    ],
)
async def test_overlength_field_fails_in_preview_not_just_commit(client, seeded_users, field, header):
    from app.services.import_service import FIELD_MAX_LENGTHS

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    overlength_value = "x" * (FIELD_MAX_LENGTHS[field] + 1)
    row = _base_row(**{"ID CODE": "951", header: overlength_value})

    preview_resp = await _preview(client, headers, [row])
    preview_body = preview_resp.json()
    assert preview_body["failed"] == 1
    assert field in preview_body["rows"][0]["reason"]

    # Committing the same row must fail the same way (never a raw DB
    # DataError) -- preview and commit never disagree on whether a row
    # will fit the database.
    commit_resp = await _commit(client, headers, [row])
    commit_body = commit_resp.json()
    assert commit_body["failed"] == 1
    assert field in commit_body["rows"][0]["reason"]
