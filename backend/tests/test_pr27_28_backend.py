"""Roadmap PR27/PR28 backend: ward contact name (D7), accessory + Cryo-Cuff
checklists (D4/D10), cuff tracking (D11), ward-first batch dispatch/receipt
(D3), expected_status on dispatch, and offline-sync carriage of the new fields.
SQLite; PostgreSQL-only proofs live in test_pr27_28_postgres.py."""
import csv
import io
import uuid

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.audit import AuditLog
from app.models.cuff import TransactionCuff
from app.models.equipment import Equipment, EquipmentStatus
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.schemas.checklist import report_columns
from app.schemas.sync import SyncOperation
from app.services import report_service
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward
from tests.test_pr25e_b2_sync_ops import _send, _user, dispatch_op, receipt_op


CRYO = {"kind": "cryo_cuff"}
STD = {"kind": "standard"}


@pytest.fixture
async def ctx(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    cryo_cat = await _category(client, admin, "Cryo-Cuff Machine")
    std_cat = await _category(client, admin, "Infusion Pump")
    return {
        "admin": admin,
        "staff": staff,
        "ro": ro,
        "cryo_cat": cryo_cat,
        "std_cat": std_cat,
        "ward_a": await _create_ward(client, admin, "W-27A", "Ward Alpha"),
        "ward_b": await _create_ward(client, admin, "W-27B", "Ward Beta"),
    }


async def _category(client, admin, name, **extra):
    r = await client.post("/api/v1/categories", headers=admin, json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def _equipment(client, admin, n, category=None, bcm=None):
    body = {"asset_number": f"AST-2728-{n}", "equipment_name": f"Dev {n}"}
    if category is not None:
        body["category_id"] = category["id"]
    if bcm:
        body["bcm_code"] = bcm
    r = await client.post("/api/v1/equipment", headers=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _dispatch_body(eq, ward, **extra):
    return {"equipment_id": eq, "ward_id": ward, **extra}


async def _dispatch(client, headers, eq, ward, **extra):
    r = await client.post("/api/v1/borrow", headers=headers, json=_dispatch_body(eq, ward, **extra))
    assert r.status_code == 201, r.text
    return r.json()


async def _receive(client, headers, tx_id, outcome="usable", **extra):
    return await client.post(
        f"/api/v1/return/{tx_id}", headers=headers, json={"receipt_outcome": outcome, **extra}
    )


async def _row(db_session, tx_id) -> BorrowTransaction:
    db_session.expire_all()
    return (
        await db_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx_id)))
    ).scalar_one()


async def _eq_status(db_session, eq):
    db_session.expire_all()
    return (await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(eq)))).scalar_one().status


async def _outstanding(client, headers, ward=None):
    r = await client.get("/api/v1/cuffs/outstanding", headers=headers, params={"ward_id": ward} if ward else {})
    assert r.status_code == 200, r.text
    return r.json()


async def _tx_count(db_session):
    return (await db_session.execute(select(func.count()).select_from(BorrowTransaction))).scalar_one()


# --------------------------------------------------------------------------
# D7 ward contact name
# --------------------------------------------------------------------------


async def test_dispatch_contact_name_is_trimmed_stored_and_returned(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "c1")
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], ward_contact_name="  Nurse Somsri  ")
    assert tx["dispatch_contact_name"] == "Nurse Somsri"
    assert tx["receipt_contact_name"] is None
    assert (await _row(db_session, tx["id"])).dispatch_contact_name == "Nurse Somsri"

    got = await client.get(f"/api/v1/transactions/{tx['id']}", headers=ctx["staff"])
    assert got.json()["dispatch_contact_name"] == "Nurse Somsri"

    r = await _receive(client, ctx["staff"], tx["id"], ward_contact_name="Nurse Malee")
    assert r.status_code == 200, r.text
    assert r.json()["receipt_contact_name"] == "Nurse Malee"
    assert r.json()["dispatch_contact_name"] == "Nurse Somsri"


async def test_contact_name_is_optional_blank_is_null_and_validated(client, ctx):
    eq1 = await _equipment(client, ctx["admin"], "c2")
    assert (await _dispatch(client, ctx["staff"], eq1, ctx["ward_a"]))["dispatch_contact_name"] is None
    eq2 = await _equipment(client, ctx["admin"], "c3")
    assert (await _dispatch(client, ctx["staff"], eq2, ctx["ward_a"], ward_contact_name="   "))[
        "dispatch_contact_name"
    ] is None

    eq3 = await _equipment(client, ctx["admin"], "c4")
    too_long = await client.post(
        "/api/v1/borrow", headers=ctx["staff"], json=_dispatch_body(eq3, ctx["ward_a"], ward_contact_name="x" * 101)
    )
    assert too_long.status_code == 422
    exactly = await client.post(
        "/api/v1/borrow", headers=ctx["staff"], json=_dispatch_body(eq3, ctx["ward_a"], ward_contact_name="x" * 100)
    )
    assert exactly.status_code == 201
    eq4 = await _equipment(client, ctx["admin"], "c5")
    ctrl = await client.post(
        "/api/v1/borrow", headers=ctx["staff"], json=_dispatch_body(eq4, ctx["ward_a"], ward_contact_name="a\nb")
    )
    assert ctrl.status_code == 422


async def test_contact_name_in_monitor_events_and_search(client, ctx):
    eq = await _equipment(client, ctx["admin"], "m1", bcm="BCM-2728-M1")
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], ward_contact_name="Khun Pranee")
    await _receive(client, ctx["staff"], tx["id"], ward_contact_name="Khun Wipa")

    d = (await client.get("/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "dispatch"})).json()
    r = (await client.get("/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "receipt"})).json()
    assert d["items"][0]["ward_contact_name"] == "Khun Pranee"
    assert r["items"][0]["ward_contact_name"] == "Khun Wipa"

    hit = await client.get(
        "/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "dispatch", "q": "pranee"}
    )
    assert hit.json()["total"] == 1
    miss = await client.get(
        "/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "dispatch", "q": "wipa"}
    )
    assert miss.json()["total"] == 0


async def test_contact_name_in_reports_and_exports(client, ctx, db_session, seeded_users):
    eq = await _equipment(client, ctx["admin"], "r1")
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], ward_contact_name="Khun Dispatch")
    assert (await _receive(client, ctx["staff"], tx["id"], ward_contact_name="Khun Receipt")).status_code == 200

    for path in ("issue", "receive"):
        page = await client.get(f"/api/v1/reports/{path}", headers=ctx["admin"])
        assert page.status_code == 200, page.text
        row = page.json()["items"][0]
        assert row["dispatch_contact_name"] == "Khun Dispatch"
        assert row["receipt_contact_name"] == "Khun Receipt"

    # PR17 export documents: one "ward user" column on the report's own side.
    from app.services import report_export_service

    admin = seeded_users[ROLE_ADMINISTRATOR]
    issue = await report_export_service.build_issue_report_document(db_session, generated_by=admin)
    receive = await report_export_service.build_receive_report_document(db_session, generated_by=admin)
    assert "ward_contact_name" in [c.key for c in issue.columns]
    assert issue.rows[0].values["ward_contact_name"] == "Khun Dispatch"
    assert receive.rows[0].values["ward_contact_name"] == "Khun Receipt"

    # Legacy CSV / XLSX builders.
    parsed = list(csv.reader(io.StringIO((await report_service.export_csv(db_session)).decode("utf-8-sig"))))
    header, first = parsed[0], parsed[1]
    assert first[header.index("dispatch_contact_name")] == "Khun Dispatch"
    assert first[header.index("receipt_contact_name")] == "Khun Receipt"
    ws = load_workbook(io.BytesIO(await report_service.export_xlsx(db_session))).active
    xl_header = [c.value for c in ws[1]]
    assert ws[2][xl_header.index("dispatch_contact_name")].value == "Khun Dispatch"


async def test_contact_name_never_in_application_logs(client, ctx, caplog):
    eq = await _equipment(client, ctx["admin"], "l1")
    with caplog.at_level("DEBUG"):
        await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], ward_contact_name="Secret Contact Name")
    # Application loggers only (the driver's own DEBUG echo of bound SQL
    # parameters is not application logging).
    app_lines = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
    assert app_lines and "Secret Contact Name" not in app_lines


# --------------------------------------------------------------------------
# D4/D10 checklists
# --------------------------------------------------------------------------


async def test_category_checklist_kind_default_by_name_and_edit(client, ctx):
    assert ctx["cryo_cat"]["checklist_kind"] == "cryo_cuff"
    assert ctx["std_cat"]["checklist_kind"] == "standard"
    lower = await _category(client, ctx["admin"], "my CRYO cuff lower")
    assert lower["checklist_kind"] == "cryo_cuff"
    explicit = await _category(client, ctx["admin"], "Cryo Special", checklist_kind="standard")
    assert explicit["checklist_kind"] == "standard"

    cats = {c["name"]: c for c in (await client.get("/api/v1/categories", headers=ctx["staff"])).json()}
    assert cats["Cryo-Cuff Machine"]["checklist_kind"] == "cryo_cuff"

    patched = await client.patch(
        f"/api/v1/categories/{explicit['id']}", headers=ctx["admin"], json={"checklist_kind": "cryo_cuff"}
    )
    assert patched.status_code == 200 and patched.json()["checklist_kind"] == "cryo_cuff"
    assert (
        await client.patch(
            f"/api/v1/categories/{explicit['id']}", headers=ctx["staff"], json={"checklist_kind": "standard"}
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/categories/{explicit['id']}", headers=ctx["admin"], json={"checklist_kind": "bogus"}
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/categories/{uuid.uuid4()}", headers=ctx["admin"], json={"checklist_kind": "standard"}
        )
    ).status_code == 404


async def test_dispatch_check_reports_checklist_kind(client, ctx):
    cryo = await _equipment(client, ctx["admin"], "k1", ctx["cryo_cat"])
    std = await _equipment(client, ctx["admin"], "k2", ctx["std_cat"])
    none = await _equipment(client, ctx["admin"], "k3")
    for eq, kind in ((cryo, "cryo_cuff"), (std, "standard"), (none, "standard")):
        r = await client.get(f"/api/v1/equipment/{eq}/dispatch-check", headers=ctx["staff"])
        assert r.json()["checklist_kind"] == kind


async def test_standard_checks_defaults_explicit_values_and_not_recorded(client, ctx, db_session):
    eq1 = await _equipment(client, ctx["admin"], "s1", ctx["std_cat"])
    tx = await _dispatch(client, ctx["staff"], eq1, ctx["ward_a"], dispatch_checks=STD)
    assert tx["checklist_kind"] == "standard"
    assert tx["dispatch_checks"] == {"kind": "standard", "screen_ok": True, "charger_ok": True, "clamp_ok": True}

    eq2 = await _equipment(client, ctx["admin"], "s2", ctx["std_cat"])
    tx2 = await _dispatch(
        client, ctx["staff"], eq2, ctx["ward_a"], dispatch_checks={**STD, "screen_ok": False, "clamp_ok": False}
    )
    assert tx2["dispatch_checks"] == {"kind": "standard", "screen_ok": False, "charger_ok": True, "clamp_ok": False}

    # Omitted entirely: NULL = not recorded (still a kind snapshot).
    eq3 = await _equipment(client, ctx["admin"], "s3", ctx["std_cat"])
    tx3 = await _dispatch(client, ctx["staff"], eq3, ctx["ward_a"])
    assert tx3["dispatch_checks"] is None and tx3["checklist_kind"] == "standard"
    row = await _row(db_session, tx3["id"])
    assert row.dispatch_checks is None and row.receipt_checks is None

    # Equipment without a category uses the standard checklist.
    eq4 = await _equipment(client, ctx["admin"], "s4")
    assert (await _dispatch(client, ctx["staff"], eq4, ctx["ward_a"], dispatch_checks=STD))["checklist_kind"] == "standard"


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "standard", "screen_ok": "yes"},
        {"kind": "standard", "screen_ok": 1},
        {"kind": "standard", "unknown": True},
        {"screen_ok": True},
        {"kind": "mystery"},
        {"kind": "cryo_cuff", "cuffs": {"knee": -1}},
        {"kind": "cryo_cuff", "cuffs": {"knee": 100}},
        {"kind": "cryo_cuff", "cuffs": {"elbow": 1}},
        {"kind": "cryo_cuff", "cuffs": {"knee": 1.5}},
    ],
)
async def test_checks_validation_rejects_malformed_payloads(client, ctx, db_session, bad):
    eq = await _equipment(client, ctx["admin"], "v1", ctx["cryo_cat"])
    r = await client.post("/api/v1/borrow", headers=ctx["staff"], json=_dispatch_body(eq, ctx["ward_a"], dispatch_checks=bad))
    assert r.status_code == 422, r.text
    assert await _tx_count(db_session) == 0


async def test_cryo_checklist_enforced_by_category(client, ctx, db_session):
    cryo = await _equipment(client, ctx["admin"], "e1", ctx["cryo_cat"])
    std = await _equipment(client, ctx["admin"], "e2", ctx["std_cat"])

    wrong1 = await client.post("/api/v1/borrow", headers=ctx["staff"], json=_dispatch_body(cryo, ctx["ward_a"], dispatch_checks=STD))
    assert wrong1.status_code == 400
    assert wrong1.json()["code"] == "CHECKLIST_KIND_MISMATCH"
    assert wrong1.json()["details"] == {"expected_kind": "cryo_cuff", "received_kind": "standard"}
    wrong2 = await client.post("/api/v1/borrow", headers=ctx["staff"], json=_dispatch_body(std, ctx["ward_a"], dispatch_checks=CRYO))
    assert wrong2.status_code == 400 and wrong2.json()["code"] == "CHECKLIST_KIND_MISMATCH"
    # No side effects.
    assert await _tx_count(db_session) == 0
    assert await _eq_status(db_session, cryo) == EquipmentStatus.AVAILABLE_AT_POOL

    ok = await _dispatch(
        client,
        ctx["staff"],
        cryo,
        ctx["ward_a"],
        dispatch_checks={**CRYO, "lid_without_charger_ok": False, "cuffs": {"knee": 2}},
    )
    assert ok["checklist_kind"] == "cryo_cuff"
    assert ok["dispatch_checks"] == {
        "kind": "cryo_cuff",
        "body_ok": True,
        "charger_ok": True,
        "lid_with_charger_ok": True,
        "lid_without_charger_ok": False,
        "hose_oring_ok": True,
        "cuff_ok": True,
        "cuffs": {"back_hip_rib": 0, "knee": 2, "shoulder": 0, "ankle": 0},
    }


async def test_receipt_checks_stored_and_kind_enforced(client, ctx, db_session):
    std = await _equipment(client, ctx["admin"], "rc1", ctx["std_cat"])
    tx = await _dispatch(client, ctx["staff"], std, ctx["ward_a"], dispatch_checks=STD)

    bad = await _receive(client, ctx["staff"], tx["id"], receipt_checks=CRYO)
    assert bad.status_code == 400 and bad.json()["code"] == "CHECKLIST_KIND_MISMATCH"
    assert (await _row(db_session, tx["id"])).status == TransactionStatus.OPEN
    assert await _eq_status(db_session, std) == EquipmentStatus.ISSUED_TO_WARD

    ok = await _receive(client, ctx["staff"], tx["id"], "defective", receipt_checks={**STD, "charger_ok": False})
    assert ok.status_code == 200, ok.text
    assert ok.json()["receipt_checks"] == {"kind": "standard", "screen_ok": True, "charger_ok": False, "clamp_ok": True}
    assert ok.json()["dispatch_checks"]["charger_ok"] is True
    assert ok.json()["receipt_outcome"] == "defective"


async def test_receipt_without_checks_leaves_null_and_historical_rows_use_category_kind(client, ctx, db_session):
    cryo = await _equipment(client, ctx["admin"], "rc2", ctx["cryo_cat"])
    tx = await _dispatch(client, ctx["staff"], cryo, ctx["ward_a"])
    row = await _row(db_session, tx["id"])
    # Simulate a pre-PR28 row: no kind snapshot.
    row.checklist_kind = None
    await db_session.commit()
    mismatch = await _receive(client, ctx["staff"], tx["id"], receipt_checks=STD)
    assert mismatch.status_code == 400 and mismatch.json()["code"] == "CHECKLIST_KIND_MISMATCH"
    ok = await _receive(client, ctx["staff"], tx["id"])
    assert ok.status_code == 200
    assert ok.json()["receipt_checks"] is None and ok.json()["receipt_contact_name"] is None


async def test_category_edit_does_not_reinterpret_existing_transactions(client, ctx):
    eq = await _equipment(client, ctx["admin"], "snap", ctx["std_cat"])
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks=STD)
    patched = await client.patch(
        f"/api/v1/categories/{ctx['std_cat']['id']}", headers=ctx["admin"], json={"checklist_kind": "cryo_cuff"}
    )
    assert patched.status_code == 200
    # The open transaction keeps its dispatch-time kind.
    ok = await _receive(client, ctx["staff"], tx["id"], receipt_checks=STD)
    assert ok.status_code == 200, ok.text


def test_report_column_mapping_for_pr30():
    assert report_columns({"kind": "standard", "screen_ok": False, "charger_ok": True, "clamp_ok": True}) == {
        "screen": False,
        "charger": True,
        "clamp": True,
    }
    # Cryo-Cuff: screen<-body_ok, charger<-charger_ok, clamp<-lid_with_charger_ok; items 4-6 not reported.
    assert report_columns(
        {"kind": "cryo_cuff", "body_ok": False, "charger_ok": True, "lid_with_charger_ok": False,
         "lid_without_charger_ok": True, "hose_oring_ok": False, "cuff_ok": False}
    ) == {"screen": False, "charger": True, "clamp": False}
    assert report_columns(None) == {"screen": None, "charger": None, "clamp": None}


# --------------------------------------------------------------------------
# D11 cuff tracking
# --------------------------------------------------------------------------


async def _cuff_rows(db_session, tx_id):
    db_session.expire_all()
    rows = (
        await db_session.execute(select(TransactionCuff).where(TransactionCuff.transaction_id == uuid.UUID(tx_id)))
    ).scalars().all()
    return {r.cuff_type: (r.issued_count, r.returned_count) for r in rows}


async def test_dispatch_issues_cuffs_and_outstanding_is_by_ward(client, ctx, db_session):
    eq1 = await _equipment(client, ctx["admin"], "u1", ctx["cryo_cat"], bcm="BCM-U1")
    eq2 = await _equipment(client, ctx["admin"], "u2", ctx["cryo_cat"])
    tx1 = await _dispatch(
        client, ctx["staff"], eq1, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"back_hip_rib": 2, "knee": 1}}
    )
    await _dispatch(client, ctx["staff"], eq2, ctx["ward_b"], dispatch_checks={**CRYO, "cuffs": {"ankle": 3}})
    # No cuffs issued -> no rows.
    eq3 = await _equipment(client, ctx["admin"], "u3", ctx["cryo_cat"])
    tx3 = await _dispatch(client, ctx["staff"], eq3, ctx["ward_a"], dispatch_checks=CRYO)
    assert await _cuff_rows(db_session, tx3["id"]) == {}
    assert await _cuff_rows(db_session, tx1["id"]) == {"back_hip_rib": (2, 0), "knee": (1, 0)}

    allw = await _outstanding(client, ctx["staff"])
    assert allw["total_outstanding"] == 6
    by_name = {w["ward_name"]: w for w in allw["items"]}
    assert by_name["Ward Alpha"]["cuffs"] == {"back_hip_rib": 2, "knee": 1, "shoulder": 0, "ankle": 0}
    assert by_name["Ward Alpha"]["total"] == 3
    tx_row = by_name["Ward Alpha"]["transactions"][0]
    assert tx_row["transaction_id"] == tx1["id"] and tx_row["bcm_code"] == "BCM-U1"
    assert tx_row["device_received"] is False
    assert by_name["Ward Beta"]["cuffs"]["ankle"] == 3

    only_a = await _outstanding(client, ctx["staff"], ctx["ward_a"])
    assert [w["ward_name"] for w in only_a["items"]] == ["Ward Alpha"] and only_a["total_outstanding"] == 3

    # Cuffs have no equipment state of their own: equipment is simply issued.
    assert await _eq_status(db_session, eq1) == EquipmentStatus.ISSUED_TO_WARD

    issue_audit = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "cuff_issue", AuditLog.entity_id == uuid.UUID(tx1["id"])))
    ).scalars().all()
    assert len(issue_audit) == 1 and issue_audit[0].after_data["cuffs_issued"]["back_hip_rib"] == 2


async def test_device_only_receipt_then_partial_then_full_receive_cuffs(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "p1", ctx["cryo_cat"])
    tx = await _dispatch(
        client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"back_hip_rib": 2, "knee": 2, "ankle": 1}}
    )

    # Device-only receipt (cuffs wet / not returned): no cuffs_returned, no checklist.
    r = await _receive(client, ctx["staff"], tx["id"])
    assert r.status_code == 200
    assert await _eq_status(db_session, eq) == EquipmentStatus.AVAILABLE_AT_POOL
    assert await _cuff_rows(db_session, tx["id"]) == {"back_hip_rib": (2, 0), "knee": (2, 0), "ankle": (1, 0)}
    out = await _outstanding(client, ctx["staff"], ctx["ward_a"])
    assert out["total_outstanding"] == 5 and out["items"][0]["transactions"][0]["device_received"] is True

    # Partial.
    p = await client.post(
        f"/api/v1/transactions/{tx['id']}/receive-cuffs",
        headers=ctx["staff"],
        json={"cuffs": {"back_hip_rib": 1, "knee": 2}, "ward_contact_name": "Khun Lek"},
    )
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["cuffs_issued"] == {"back_hip_rib": 2, "knee": 2, "shoulder": 0, "ankle": 1}
    assert body["cuffs_returned"] == {"back_hip_rib": 1, "knee": 2, "shoulder": 0, "ankle": 0}
    assert body["cuffs_outstanding"] == {"back_hip_rib": 1, "knee": 0, "shoulder": 0, "ankle": 1}
    assert (await _outstanding(client, ctx["staff"]))["total_outstanding"] == 2

    # More than outstanding: refused, nothing changes (all-or-nothing across types).
    over = await client.post(
        f"/api/v1/transactions/{tx['id']}/receive-cuffs",
        headers=ctx["staff"],
        json={"cuffs": {"back_hip_rib": 1, "knee": 1}},
    )
    assert over.status_code == 409 and over.json()["code"] == "CUFF_RETURN_EXCEEDS_OUTSTANDING"
    assert over.json()["details"]["exceeded"] == {"knee": {"requested": 1, "outstanding": 0}}
    assert await _cuff_rows(db_session, tx["id"]) == {"back_hip_rib": (2, 1), "knee": (2, 2), "ankle": (1, 0)}

    # Rest.
    rest = await client.post(
        f"/api/v1/transactions/{tx['id']}/receive-cuffs",
        headers=ctx["staff"],
        json={"cuffs": {"back_hip_rib": 1, "ankle": 1}},
    )
    assert rest.status_code == 200 and rest.json()["cuffs_outstanding"] == {
        "back_hip_rib": 0, "knee": 0, "shoulder": 0, "ankle": 0
    }
    assert (await _outstanding(client, ctx["staff"])) == {"items": [], "total_outstanding": 0}

    # Every movement is audited (receive-cuffs carries the contact name).
    audits = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "cuff_return", AuditLog.entity_id == uuid.UUID(tx["id"])).order_by(AuditLog.created_at)
        )
    ).scalars().all()
    assert len(audits) == 2
    assert {a.after_data["source"] for a in audits} == {"receive_cuffs"}
    assert any(a.after_data.get("ward_contact_name") == "Khun Lek" for a in audits)
    # Device-only equipment stays usable throughout: no extra state ever.
    assert await _eq_status(db_session, eq) == EquipmentStatus.AVAILABLE_AT_POOL


async def test_receive_cuffs_validation_and_not_allowed_cases(client, ctx):
    eq = await _equipment(client, ctx["admin"], "n1", ctx["cryo_cat"])
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"knee": 1}})
    url = f"/api/v1/transactions/{tx['id']}/receive-cuffs"

    # Device still out: record cuffs with the device receipt instead.
    early = await client.post(url, headers=ctx["staff"], json={"cuffs": {"knee": 1}})
    assert early.status_code == 409 and early.json()["code"] == "CUFF_RECEIVE_NOT_ALLOWED"

    await _receive(client, ctx["staff"], tx["id"])
    empty = await client.post(url, headers=ctx["staff"], json={"cuffs": {}})
    assert empty.status_code == 400 and empty.json()["code"] == "INVALID_INPUT"
    assert (await client.post(url, headers=ctx["staff"], json={"cuffs": {"knee": -1}})).status_code == 422
    assert (await client.post(url, headers=ctx["staff"], json={"cuffs": {"knee": 1}, "extra": 1})).status_code == 422
    missing = await client.post(
        f"/api/v1/transactions/{uuid.uuid4()}/receive-cuffs", headers=ctx["staff"], json={"cuffs": {"knee": 1}}
    )
    assert missing.status_code == 404

    # A type that was never issued has nothing outstanding.
    never = await client.post(url, headers=ctx["staff"], json={"cuffs": {"shoulder": 1}})
    assert never.status_code == 409 and never.json()["code"] == "CUFF_RETURN_EXCEEDS_OUTSTANDING"

    # A transaction that never issued cuffs.
    std = await _equipment(client, ctx["admin"], "n2", ctx["std_cat"])
    stx = await _dispatch(client, ctx["staff"], std, ctx["ward_a"])
    await _receive(client, ctx["staff"], stx["id"])
    none = await client.post(f"/api/v1/transactions/{stx['id']}/receive-cuffs", headers=ctx["staff"], json={"cuffs": {"knee": 1}})
    assert none.status_code == 409


async def test_cuffs_returned_at_receipt_partial_and_via_checklist_counts(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "w1", ctx["cryo_cat"])
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"knee": 2, "shoulder": 2}})
    r = await _receive(client, ctx["staff"], tx["id"], cuffs_returned={"knee": 1}, ward_contact_name="Khun Ploy")
    assert r.status_code == 200, r.text
    assert await _cuff_rows(db_session, tx["id"]) == {"knee": (2, 1), "shoulder": (2, 0)}
    audits = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "cuff_return", AuditLog.entity_id == uuid.UUID(tx["id"])))
    ).scalars().all()
    assert len(audits) == 1 and audits[0].after_data["source"] == "receipt"

    # Second device cycle: counts come from the receipt checklist when cuffs_returned is omitted,
    # and the stored checklist carries the applied counts.
    tx2 = await _dispatch(client, ctx["staff"], eq, ctx["ward_b"], dispatch_checks={**CRYO, "cuffs": {"ankle": 2}})
    r2 = await _receive(client, ctx["staff"], tx2["id"], receipt_checks={**CRYO, "cuffs": {"ankle": 2}, "cuff_ok": False})
    assert r2.status_code == 200, r2.text
    assert r2.json()["receipt_checks"]["cuffs"] == {"back_hip_rib": 0, "knee": 0, "shoulder": 0, "ankle": 2}
    assert r2.json()["receipt_checks"]["cuff_ok"] is False
    assert await _cuff_rows(db_session, tx2["id"]) == {"ankle": (2, 2)}

    # Explicit cuffs_returned wins over (and normalises) the checklist counts.
    tx3 = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"ankle": 2}})
    r3 = await _receive(client, ctx["staff"], tx3["id"], receipt_checks={**CRYO, "cuffs": {"ankle": 2}}, cuffs_returned={"ankle": 1})
    assert r3.status_code == 200
    assert r3.json()["receipt_checks"]["cuffs"]["ankle"] == 1
    assert await _cuff_rows(db_session, tx3["id"]) == {"ankle": (2, 1)}


async def test_receipt_returning_more_cuffs_than_outstanding_is_refused_without_side_effects(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "x1", ctx["cryo_cat"])
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"knee": 1}})
    r = await _receive(client, ctx["staff"], tx["id"], cuffs_returned={"knee": 2})
    assert r.status_code == 409 and r.json()["code"] == "CUFF_RETURN_EXCEEDS_OUTSTANDING"
    # Whole receipt refused: transaction still open, equipment still issued, nothing recorded.
    row = await _row(db_session, tx["id"])
    assert row.status == TransactionStatus.OPEN and row.returned_at is None and row.receipt_contact_name is None
    assert await _eq_status(db_session, eq) == EquipmentStatus.ISSUED_TO_WARD
    assert await _cuff_rows(db_session, tx["id"]) == {"knee": (1, 0)}

    # Equipment whose dispatch issued no cuffs cannot return any.
    std = await _equipment(client, ctx["admin"], "x2", ctx["std_cat"])
    stx = await _dispatch(client, ctx["staff"], std, ctx["ward_a"])
    r2 = await _receive(client, ctx["staff"], stx["id"], cuffs_returned={"knee": 1})
    assert r2.status_code == 409 and (await _row(db_session, stx["id"])).status == TransactionStatus.OPEN


async def test_redispatch_while_cuffs_outstanding_keeps_them_with_the_earlier_ward(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "rd1", ctx["cryo_cat"])
    first = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"knee": 2}})
    second = await _dispatch(
        client, ctx["staff"], eq, ctx["ward_b"], acknowledge_status_warning=True, dispatch_checks={**CRYO, "cuffs": {"shoulder": 1}}
    )
    prev = await _row(db_session, first["id"])
    assert prev.status == TransactionStatus.CLOSED and prev.close_reason is not None

    out = await _outstanding(client, ctx["staff"])
    by_name = {w["ward_name"]: w for w in out["items"]}
    assert by_name["Ward Alpha"]["cuffs"]["knee"] == 2  # still attributed to the first ward/transaction
    assert by_name["Ward Beta"]["cuffs"]["shoulder"] == 1
    assert by_name["Ward Alpha"]["transactions"][0]["transaction_id"] == first["id"]

    # The re-dispatch-closed transaction can still receive its cuffs later.
    ok = await client.post(
        f"/api/v1/transactions/{first['id']}/receive-cuffs", headers=ctx["staff"], json={"cuffs": {"knee": 2}}
    )
    assert ok.status_code == 200, ok.text
    assert (await _outstanding(client, ctx["staff"], ctx["ward_a"]))["total_outstanding"] == 0
    assert (await _outstanding(client, ctx["staff"], ctx["ward_b"]))["total_outstanding"] == 1
    # Receipt of the device against the closed-by-redispatch transaction stays refused.
    assert (await _receive(client, ctx["staff"], first["id"])).status_code == 409
    assert second["status"] == "open"


async def test_ward_correction_moves_outstanding_cuffs_with_the_transaction(client, ctx):
    eq = await _equipment(client, ctx["admin"], "wc1", ctx["cryo_cat"])
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"knee": 1}})
    fixed = await client.post(
        f"/api/v1/transactions/{tx['id']}/correct-ward",
        headers=ctx["admin"],
        json={"ward_id": ctx["ward_b"], "reason": "wrong ward keyed"},
    )
    assert fixed.status_code == 200, fixed.text
    assert [w["ward_name"] for w in (await _outstanding(client, ctx["staff"]))["items"]] == ["Ward Beta"]


async def test_cuff_balance_can_never_go_negative_or_exceed_issued(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "ng1", ctx["cryo_cat"])
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"knee": 1}})
    row = (
        await db_session.execute(select(TransactionCuff).where(TransactionCuff.transaction_id == uuid.UUID(tx["id"])))
    ).scalar_one()
    row.returned_count = 2  # DB CHECK is the backstop for application logic.
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    # And the conditional update is the guard in application code.
    from app.crud import cuff as cuff_crud

    assert await cuff_crud.apply_return(db_session, transaction_id=uuid.UUID(tx["id"]), cuff_type="knee", count=2) is False
    assert await cuff_crud.apply_return(db_session, transaction_id=uuid.UUID(tx["id"]), cuff_type="knee", count=1) is True
    assert await cuff_crud.apply_return(db_session, transaction_id=uuid.UUID(tx["id"]), cuff_type="knee", count=1) is False


async def test_monitor_shows_checks_and_outstanding_cuffs(client, ctx):
    eq = await _equipment(client, ctx["admin"], "mo1", ctx["cryo_cat"])
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"knee": 2}})
    await _receive(client, ctx["staff"], tx["id"], cuffs_returned={"knee": 1}, receipt_checks={**CRYO, "hose_oring_ok": False})
    d = (await client.get("/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "dispatch"})).json()["items"][0]
    r = (await client.get("/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "receipt"})).json()["items"][0]
    assert d["checklist_kind"] == "cryo_cuff" and d["checks"]["cuffs"]["knee"] == 2
    assert r["checks"]["hose_oring_ok"] is False and r["checks"]["cuffs"]["knee"] == 1
    assert d["cuffs_outstanding"] == r["cuffs_outstanding"] == {
        "back_hip_rib": 0, "knee": 1, "shoulder": 0, "ankle": 0
    }
    plain = await _equipment(client, ctx["admin"], "mo2", ctx["std_cat"])
    await _dispatch(client, ctx["staff"], plain, ctx["ward_a"])
    items = (await client.get("/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "dispatch"})).json()["items"]
    assert any(i["cuffs_outstanding"] is None and i["checks"] is None for i in items)


# --------------------------------------------------------------------------
# expected_status on single dispatch
# --------------------------------------------------------------------------


async def _set_status(client, admin, eq, status):
    r = await client.post(f"/api/v1/equipment/{eq}/status", headers=admin, json={"status": status})
    assert r.status_code == 200, r.text


async def test_expected_status_must_match_for_single_dispatch(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "es1", ctx["std_cat"])
    await _set_status(client, ctx["admin"], eq, "unavailable_defective")
    ok = await _dispatch(
        client, ctx["staff"], eq, ctx["ward_a"], acknowledge_status_warning=True, expected_status="unavailable_defective"
    )
    assert ok["dispatched_while_defective"] is True

    eq2 = await _equipment(client, ctx["admin"], "es2", ctx["std_cat"])
    await _set_status(client, ctx["admin"], eq2, "unavailable_defective")
    # Operator confirmed the defective warning, then someone repaired it.
    await _set_status(client, ctx["admin"], eq2, "available_at_pool")
    stale = await client.post(
        "/api/v1/borrow",
        headers=ctx["staff"],
        json=_dispatch_body(eq2, ctx["ward_a"], acknowledge_status_warning=True, expected_status="unavailable_defective"),
    )
    assert stale.status_code == 409 and stale.json()["code"] == "DISPATCH_WARNING_STALE"
    assert stale.json()["details"]["expected_status"] == "unavailable_defective"
    assert await _eq_status(db_session, eq2) == EquipmentStatus.AVAILABLE_AT_POOL
    # expected_status matching an available item is fine; unknown values are 422.
    assert (
        await client.post(
            "/api/v1/borrow",
            headers=ctx["staff"],
            json=_dispatch_body(eq2, ctx["ward_a"], expected_status="available_at_pool"),
        )
    ).status_code == 201
    eq3 = await _equipment(client, ctx["admin"], "es3", ctx["std_cat"])
    assert (
        await client.post(
            "/api/v1/borrow", headers=ctx["staff"], json=_dispatch_body(eq3, ctx["ward_a"], expected_status="nope")
        )
    ).status_code == 422


# --------------------------------------------------------------------------
# D3 batches
# --------------------------------------------------------------------------


async def test_dispatch_batch_partial_failure_isolation(client, ctx, db_session):
    ok1 = await _equipment(client, ctx["admin"], "b1", ctx["std_cat"])
    decom = await _equipment(client, ctx["admin"], "b2", ctx["std_cat"])
    defective = await _equipment(client, ctx["admin"], "b3", ctx["std_cat"])
    cryo = await _equipment(client, ctx["admin"], "b4", ctx["cryo_cat"])
    await _set_status(client, ctx["admin"], decom, "unavailable_defective")
    await _set_status(client, ctx["admin"], decom, "decommissioned")
    await _set_status(client, ctx["admin"], defective, "unavailable_defective")

    r = await client.post(
        "/api/v1/transactions/dispatch-batch",
        headers=ctx["staff"],
        json={
            "ward_id": ctx["ward_a"],
            "ward_contact_name": " Khun Batch ",
            "phone": "1234",
            "note": "batch note",
            "items": [
                {"equipment_id": ok1, "checks": {**STD, "clamp_ok": False}},
                {"equipment_id": decom},
                {"equipment_id": defective, "expected_status": "unavailable_defective"},
                {"equipment_id": cryo, "checks": {**CRYO, "cuffs": {"knee": 2}}},
                {"equipment_id": str(uuid.uuid4())},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    res = body["results"]
    assert (body["total"], body["succeeded"], body["failed"]) == (5, 2, 3)
    assert [x["index"] for x in res] == list(range(5))
    assert res[0]["ok"] and res[0]["transaction_id"] and res[0]["equipment_id"] == ok1
    assert res[1]["error"]["code"] == "EQUIPMENT_NOT_AVAILABLE" and res[1]["error"]["status"] == 409
    assert res[2]["error"]["code"] == "DISPATCH_STATUS_WARNING"
    assert res[2]["error"]["details"]["warning"] == "defective"
    assert res[3]["ok"] and res[3]["cuffs_outstanding"] == {"back_hip_rib": 0, "knee": 2, "shoulder": 0, "ankle": 0}
    assert res[4]["error"]["code"] == "EQUIPMENT_NOT_FOUND"

    # Successful items persisted independently of the failures around them.
    assert await _tx_count(db_session) == 2
    t1 = await _row(db_session, res[0]["transaction_id"])
    assert t1.ward_id == uuid.UUID(ctx["ward_a"]) and t1.dispatch_contact_name == "Khun Batch"
    assert t1.phone_number == "1234" and t1.notes == "batch note"
    assert t1.dispatch_checks["clamp_ok"] is False and t1.dispatch_type is None
    assert await _eq_status(db_session, ok1) == EquipmentStatus.ISSUED_TO_WARD
    assert await _eq_status(db_session, decom) == EquipmentStatus.DECOMMISSIONED
    assert await _eq_status(db_session, defective) == EquipmentStatus.UNAVAILABLE_DEFECTIVE
    assert await _cuff_rows(db_session, res[3]["transaction_id"]) == {"knee": (2, 0)}

    # The failed defective item is retried on its own with confirmation.
    again = await client.post(
        "/api/v1/transactions/dispatch-batch",
        headers=ctx["staff"],
        json={
            "ward_id": ctx["ward_a"],
            "items": [{"equipment_id": defective, "acknowledge_status_warning": True, "expected_status": "unavailable_defective"}],
        },
    )
    assert again.json()["results"][0]["ok"] is True
    assert (await _row(db_session, again.json()["results"][0]["transaction_id"])).dispatched_while_defective is True


async def test_dispatch_batch_request_validation(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "bv1", ctx["std_cat"])
    url = "/api/v1/transactions/dispatch-batch"
    h = ctx["staff"]
    assert (await client.post(url, headers=h, json={"ward_id": ctx["ward_a"], "items": []})).status_code == 422
    assert (
        await client.post(url, headers=h, json={"ward_id": ctx["ward_a"], "items": [{"equipment_id": eq}, {"equipment_id": eq}]})
    ).status_code == 422
    # HN belongs to PR29: not accepted anywhere yet.
    assert (
        await client.post(url, headers=h, json={"ward_id": ctx["ward_a"], "items": [{"equipment_id": eq, "hn": "123"}]})
    ).status_code == 422
    assert (
        await client.post(url, headers=h, json={"ward_id": ctx["ward_a"], "hn": "1", "items": [{"equipment_id": eq}]})
    ).status_code == 422
    too_many = [{"equipment_id": str(uuid.uuid4())} for _ in range(51)]
    assert (await client.post(url, headers=h, json={"ward_id": ctx["ward_a"], "items": too_many})).status_code == 422
    assert (
        await client.post(url, headers=h, json={"ward_id": ctx["ward_a"], "phone": "1" * 21, "items": [{"equipment_id": eq}]})
    ).status_code == 422
    assert (
        await client.post(url, headers=h, json={"ward_id": ctx["ward_a"], "ward_contact_name": "x" * 101, "items": [{"equipment_id": eq}]})
    ).status_code == 422
    bad_ward = await client.post(url, headers=h, json={"ward_id": str(uuid.uuid4()), "items": [{"equipment_id": eq}]})
    assert bad_ward.status_code == 400 and bad_ward.json()["code"] == "INVALID_INPUT"
    assert await _tx_count(db_session) == 0


async def test_batch_endpoints_require_pool_roles(client, ctx):
    for url, body in (
        ("/api/v1/transactions/dispatch-batch", {"ward_id": ctx["ward_a"], "items": [{"equipment_id": str(uuid.uuid4())}]}),
        ("/api/v1/transactions/receipt-batch", {"items": [{"transaction_id": str(uuid.uuid4()), "receipt_outcome": "usable"}]}),
        (f"/api/v1/transactions/{uuid.uuid4()}/receive-cuffs", {"cuffs": {"knee": 1}}),
    ):
        assert (await client.post(url, json=body)).status_code == 401
        assert (await client.post(url, headers=ctx["ro"], json=body)).status_code == 403
        assert (await client.post(url, headers=ctx["admin"], json=body)).status_code != 403
    assert (await client.get("/api/v1/cuffs/outstanding")).status_code == 401
    assert (await client.get("/api/v1/cuffs/outstanding", headers=ctx["ro"])).status_code == 403
    assert (await client.get("/api/v1/cuffs/outstanding", headers=ctx["admin"])).status_code == 200
    assert (await client.get("/api/v1/cuffs/outstanding", headers=ctx["admin"], params={"ward_id": "nope"})).status_code == 400


async def test_receipt_batch_mixed_targets_outcomes_and_isolation(client, ctx, db_session):
    a = await _equipment(client, ctx["admin"], "rb1", ctx["std_cat"])
    b = await _equipment(client, ctx["admin"], "rb2", ctx["cryo_cat"])
    c = await _equipment(client, ctx["admin"], "rb3", ctx["std_cat"])
    free = await _equipment(client, ctx["admin"], "rb4", ctx["std_cat"])
    ta = await _dispatch(client, ctx["staff"], a, ctx["ward_a"])
    tb = await _dispatch(client, ctx["staff"], b, ctx["ward_b"], dispatch_checks={**CRYO, "cuffs": {"knee": 3}})
    tc = await _dispatch(client, ctx["staff"], c, ctx["ward_a"])

    r = await client.post(
        "/api/v1/transactions/receipt-batch",
        headers=ctx["staff"],
        json={
            # Informational only: ta/tb/tc were dispatched to other wards, accepted without warning.
            "ward_id": ctx["ward_b"],
            "ward_contact_name": "Khun Return",
            "note": "returned together",
            "items": [
                {"transaction_id": ta["id"], "receipt_outcome": "usable", "checks": {**STD, "screen_ok": False}},
                {"equipment_id": b, "receipt_outcome": "defective", "checks": CRYO, "cuffs_returned": {"knee": 1}},
                {"equipment_id": free, "receipt_outcome": "usable"},
                {"transaction_id": tc["id"], "receipt_outcome": "usable", "checks": CRYO},
                {"transaction_id": str(uuid.uuid4()), "receipt_outcome": "usable"},
                {"equipment_id": c, "receipt_outcome": "usable"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    res = body["results"]
    assert (body["total"], body["succeeded"], body["failed"]) == (6, 3, 3)
    assert res[0]["ok"] and res[0]["transaction_id"] == ta["id"] and res[0]["equipment_id"] == a
    assert res[1]["ok"] and res[1]["transaction_id"] == tb["id"]
    assert res[1]["cuffs_outstanding"] == {"back_hip_rib": 0, "knee": 2, "shoulder": 0, "ankle": 0}
    assert res[2]["error"]["code"] == "TRANSACTION_NOT_FOUND" and res[2]["equipment_id"] == free
    assert res[3]["error"]["code"] == "CHECKLIST_KIND_MISMATCH"
    assert res[4]["error"]["code"] == "TRANSACTION_NOT_FOUND"
    assert res[5]["ok"] and res[5]["transaction_id"] == tc["id"]  # tc failed earlier at index 3 but stays open

    assert await _eq_status(db_session, a) == EquipmentStatus.AVAILABLE_AT_POOL
    assert await _eq_status(db_session, b) == EquipmentStatus.UNAVAILABLE_DEFECTIVE
    db_session.expire_all()
    ra = await db_session.get(BorrowTransaction, uuid.UUID(ta["id"]))
    rb = await db_session.get(BorrowTransaction, uuid.UUID(tb["id"]))
    assert ra.receipt_contact_name == rb.receipt_contact_name == "Khun Return"
    assert ra.receipt_checks["screen_ok"] is False and ra.condition_on_return == "usable"
    assert rb.condition_on_return == "defective" and "returned together" in rb.notes
    # Receipt keeps the dispatch ward (first receiving ward only; no transfer tracking).
    assert rb.ward_id == uuid.UUID(ctx["ward_b"]) and ra.ward_id == uuid.UUID(ctx["ward_a"])
    assert await _cuff_rows(db_session, tb["id"]) == {"knee": (3, 1)}

    # Already received: reported per item, others unaffected.
    again = await client.post(
        "/api/v1/transactions/receipt-batch",
        headers=ctx["staff"],
        json={"items": [{"transaction_id": ta["id"], "receipt_outcome": "usable"}]},
    )
    assert again.status_code == 200 and again.json()["results"][0]["error"]["code"] == "TRANSACTION_ALREADY_RETURNED"


async def test_receipt_batch_request_validation(client, ctx):
    url = "/api/v1/transactions/receipt-batch"
    h = ctx["staff"]
    tid = str(uuid.uuid4())
    for items in (
        [],
        [{"receipt_outcome": "usable"}],
        [{"transaction_id": tid, "equipment_id": tid, "receipt_outcome": "usable"}],
        [{"transaction_id": tid, "receipt_outcome": "usable"}, {"transaction_id": tid, "receipt_outcome": "usable"}],
        [{"transaction_id": tid, "receipt_outcome": "cleaning"}],
        [{"transaction_id": tid, "receipt_outcome": "usable", "hn": "1"}],
    ):
        assert (await client.post(url, headers=h, json={"items": items})).status_code == 422, items
    bad_ward = await client.post(
        url, headers=h, json={"ward_id": str(uuid.uuid4()), "items": [{"transaction_id": tid, "receipt_outcome": "usable"}]}
    )
    assert bad_ward.status_code == 400


# --------------------------------------------------------------------------
# Offline sync carries the new fields
# --------------------------------------------------------------------------


async def test_sync_ops_carry_contact_checks_and_cuffs(client, ctx, db_session):
    user_id = await _user(client, ctx["staff"])
    eq = await _equipment(client, ctx["admin"], "sy1", ctx["cryo_cat"])
    d = dispatch_op(
        user_id,
        eq,
        ctx["ward_a"],
        ward_contact_name="Khun Offline",
        dispatch_checks={**CRYO, "cuffs": {"knee": 2}},
    )
    res = await _send(client, ctx["staff"], d)
    assert res[0]["result"] == "applied", res
    tx_id = res[0]["transaction_id"]
    row = await _row(db_session, tx_id)
    assert row.dispatch_contact_name == "Khun Offline" and row.checklist_kind == "cryo_cuff"
    assert row.dispatch_checks["cuffs"]["knee"] == 2
    assert await _cuff_rows(db_session, tx_id) == {"knee": (2, 0)}

    rcp = receipt_op(user_id, tx_id, seq=2, device_id=d["device_id"])
    rcp["receipt"].update(
        {"ward_contact_name": "Khun Back", "receipt_checks": {**CRYO, "lid_with_charger_ok": False}, "cuffs_returned": {"knee": 1}}
    )
    res2 = await _send(client, ctx["staff"], rcp)
    assert res2[0]["result"] == "applied", res2
    row = await _row(db_session, tx_id)
    assert row.receipt_contact_name == "Khun Back" and row.receipt_checks["lid_with_charger_ok"] is False
    assert row.receipt_checks["cuffs"]["knee"] == 1
    assert await _cuff_rows(db_session, tx_id) == {"knee": (2, 1)}

    # Replay is a duplicate (hash stable across retries).
    again = await _send(client, ctx["staff"], d)
    assert again[0]["result"] == "duplicate"


async def test_sync_op_with_wrong_checklist_kind_lands_in_review_and_invalid_shapes_are_422(client, ctx, db_session):
    user_id = await _user(client, ctx["staff"])
    eq = await _equipment(client, ctx["admin"], "sy2", ctx["std_cat"])
    bad = dispatch_op(user_id, eq, ctx["ward_a"], dispatch_checks=CRYO)
    res = await _send(client, ctx["staff"], bad)
    assert res[0]["result"] == "conflict" and res[0]["code"] == "CHECKLIST_KIND_MISMATCH"
    assert await _tx_count(db_session) == 0
    malformed = dispatch_op(user_id, eq, ctx["ward_a"], seq=2, ward_contact_name="x" * 101)
    assert (await client.post("/api/v1/sync/operations", headers=ctx["staff"], json={"operations": [malformed]})).status_code == 422


async def test_sync_receipt_cuff_overreturn_is_a_conflict_not_a_partial_apply(client, ctx, db_session):
    user_id = await _user(client, ctx["staff"])
    eq = await _equipment(client, ctx["admin"], "sy3", ctx["cryo_cat"])
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], dispatch_checks={**CRYO, "cuffs": {"knee": 1}})
    rcp = receipt_op(user_id, tx["id"])
    rcp["receipt"]["cuffs_returned"] = {"knee": 5}
    res = await _send(client, ctx["staff"], rcp)
    assert res[0]["result"] == "conflict" and res[0]["code"] == "CUFF_RETURN_EXCEEDS_OUTSTANDING"
    assert (await _row(db_session, tx["id"])).status == TransactionStatus.OPEN
    assert await _cuff_rows(db_session, tx["id"]) == {"knee": (1, 0)}


def test_sync_payload_hash_is_unchanged_for_ops_without_the_new_fields():
    base = {
        "op_id": str(uuid.uuid4()),
        "device_id": str(uuid.uuid4()),
        "device_seq": 1,
        "user_id": str(uuid.uuid4()),
        "op_type": "dispatch",
        "occurred_at_local": "2026-11-25T10:00:00Z",
        "dispatch": {"equipment_id": str(uuid.uuid4()), "ward_id": str(uuid.uuid4())},
    }
    payload = SyncOperation.model_validate(base).business_payload()["dispatch"]
    for key in ("ward_contact_name", "dispatch_checks", "receipt_checks", "cuffs_returned", "expected_status"):
        assert key not in payload
    base["dispatch"]["ward_contact_name"] = "Khun A"
    assert SyncOperation.model_validate(base).business_payload()["dispatch"]["ward_contact_name"] == "Khun A"
