"""Reports-usable: BCM filter, keyer labels, Bangkok date+time, and the Thai
/reports/export (columns, date/category filter, BOM, no HN)."""
import csv
import io
from datetime import date, datetime, timezone

from openpyxl import load_workbook
from sqlalchemy import update

from app.models.transaction import BorrowTransaction
from app.services import report_export_service, report_service
from tests.test_pr27_28_backend import _category, _dispatch, _equipment, _receive, ctx, _row  # noqa: F401

EXPECTED_HEADERS = [
    "เลขที่รายการ", "วันที่จ่าย", "เวลาจ่าย", "รหัส BCM", "ประเภท", "ชื่อเครื่อง", "แหล่งที่มา", "Ward",
    "BME ผู้จ่าย", "ผู้รับ (Ward)", "วันที่รับคืน", "เวลารับคืน", "BME ผู้รับคืน", "ผู้ส่งคืน (Ward)",
    "สถานะ", "สภาพตอนคืน", "ตรวจตอนจ่าย", "ตรวจตอนคืน",
]


async def _closed_tx(client, ctx, db_session, n, bcm, **kw):
    eq = await _equipment(client, ctx["admin"], n, category=kw.get("category"), bcm=bcm)
    extra = {}
    if kw.get("category") is not ctx["cryo_cat"]:
        extra["dispatch_checks"] = {"kind": "standard", "screen_ok": True, "charger_ok": False, "clamp_ok": True}
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], ward_contact_name="Khun Dispatch", **extra)
    assert (await _receive(client, ctx["staff"], tx["id"], ward_contact_name="Khun Receipt")).status_code == 200
    return tx


async def _rows(db_session, **filters):
    parsed = list(csv.reader(io.StringIO((await report_service.export_csv(db_session, **filters)).decode("utf-8-sig"))))
    return parsed[0], parsed[1:]


async def test_export_columns_labels_and_bom(client, ctx, db_session):
    tx = await _closed_tx(client, ctx, db_session, "u1", "BCM-U1", category=ctx["std_cat"])
    await db_session.execute(
        update(BorrowTransaction).where(BorrowTransaction.id == (await _row(db_session, tx["id"])).id).values(
            borrowed_at=datetime(2026, 11, 20, 18, 30, tzinfo=timezone.utc),  # 21/11 01:30 Bangkok
            dispatch_keyer_label="BME Somchai\n[Dispatch] legacy sheet dispatch row 5",
            receipt_keyer_label="BME Malee",
        )
    )
    await db_session.commit()
    raw = await report_service.export_csv(db_session)
    assert raw.startswith(b"\xef\xbb\xbf")
    header, rows = await _rows(db_session)
    assert header == EXPECTED_HEADERS
    r = dict(zip(header, rows[0]))
    assert (r["วันที่จ่าย"], r["เวลาจ่าย"]) == ("21/11/2026", "01:30")
    assert r["รหัส BCM"] == "BCM-U1" and r["ประเภท"] == "Infusion Pump" and r["แหล่งที่มา"] == "Pool"
    assert r["Ward"] == "Ward Alpha"
    assert r["BME ผู้จ่าย"] == "BME Somchai" and r["BME ผู้รับคืน"] == "BME Malee"
    assert r["ผู้รับ (Ward)"] == "Khun Dispatch" and r["ผู้ส่งคืน (Ward)"] == "Khun Receipt"
    assert r["สถานะ"] == "รับคืนแล้ว" and r["สภาพตอนคืน"] == "ใช้งานได้"
    assert r["ตรวจตอนจ่าย"] == "✓/✗/✓"
    assert "legacy sheet" not in " ".join(rows[0])
    ws = load_workbook(io.BytesIO(await report_service.export_xlsx(db_session))).active
    assert [c.value for c in ws[1]] == EXPECTED_HEADERS


async def test_export_keyer_label_falls_back_to_user_name(client, ctx, db_session):
    await _closed_tx(client, ctx, db_session, "u2", "BCM-U2")
    header, rows = await _rows(db_session)
    r = dict(zip(header, rows[0]))
    assert r["BME ผู้จ่าย"] and r["BME ผู้รับคืน"]


async def test_export_date_and_category_filters(client, ctx, db_session):
    old = await _closed_tx(client, ctx, db_session, "u3", "BCM-OLD", category=ctx["cryo_cat"])
    await _closed_tx(client, ctx, db_session, "u4", "BCM-NEW", category=ctx["std_cat"])
    await db_session.execute(
        update(BorrowTransaction).where(BorrowTransaction.id == (await _row(db_session, old["id"])).id).values(
            # 2026-11-01 23:30 UTC == 02/11 06:30 Bangkok
            borrowed_at=datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)
        )
    )
    await db_session.commit()
    h, rows = await _rows(db_session, date_from=date(2026, 11, 2), date_to=date(2026, 11, 2))
    assert [dict(zip(h, r))["รหัส BCM"] for r in rows] == ["BCM-OLD"]
    h, rows = await _rows(db_session, date_from=date(2026, 11, 1), date_to=date(2026, 11, 1))
    assert rows == []
    import uuid
    h, rows = await _rows(db_session, category_id=uuid.UUID(ctx["std_cat"]["id"]))
    assert [dict(zip(h, r))["รหัส BCM"] for r in rows] == ["BCM-NEW"]


async def test_export_endpoint_accepts_filters(client, ctx):
    r = await client.get("/api/v1/reports/export", headers=ctx["admin"],
                         params={"format": "csv", "date_from": "2026-01-01", "date_to": "2026-01-02"})
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf")
    bad = await client.get("/api/v1/reports/export", headers=ctx["admin"],
                           params={"date_from": "2026-02-01", "date_to": "2026-01-02"})
    assert bad.status_code == 400


async def test_bcm_filter_ilike_and_wildcards_escaped(client, ctx):
    for n, bcm in (("b1", "BCM-AB_1"), ("b2", "BCM-ABX1")):
        eq = await _equipment(client, ctx["admin"], n, bcm=bcm)
        tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"])
        assert (await _receive(client, ctx["staff"], tx["id"])).status_code == 200
    for path in ("receive", "issue"):
        hit = await client.get(f"/api/v1/reports/{path}", headers=ctx["admin"], params={"bcm_code": "bcm-ab_"})
        assert [i["equipment"]["bcm_code"] for i in hit.json()["items"]] == ["BCM-AB_1"]
        allm = await client.get(f"/api/v1/reports/{path}", headers=ctx["admin"], params={"bcm_code": "ab"})
        assert allm.json()["total"] == 2
        pct = await client.get(f"/api/v1/reports/{path}", headers=ctx["admin"], params={"bcm_code": "%"})
        assert pct.json()["total"] == 0


async def test_print_document_uses_bcm_keyer_and_bangkok_time(client, ctx, db_session, seeded_users):
    tx = await _closed_tx(client, ctx, db_session, "p1", "BCM-P1", category=ctx["std_cat"])
    await db_session.execute(
        update(BorrowTransaction).where(BorrowTransaction.id == (await _row(db_session, tx["id"])).id).values(
            borrowed_at=datetime(2026, 11, 20, 18, 30, tzinfo=timezone.utc), receipt_keyer_label="BME Malee",
        )
    )
    await db_session.commit()
    admin = seeded_users["administrator"]
    await db_session.refresh(admin)
    for build, side in ((report_export_service.build_receive_report_document, "ผู้ส่งคืน (Ward)"),
                        (report_export_service.build_issue_report_document, "ผู้รับ (Ward)")):
        doc = await build(db_session, generated_by=admin, bcm_code="p1")
        labels = {c.key: c.label_th for c in doc.columns}
        assert labels["ward_name"] == "Ward" and labels["ward_contact_name"] == side
        v = doc.rows[0].values
        assert v["bcm_code"] == "BCM-P1" and v["category_name"] == "Infusion Pump"
        assert v["dispatch_at"] == "21/11/2026 01:30"
    assert doc.rows[0].values["receipt_operator_display_name"] == "BME Malee"


async def test_no_hn_anywhere_in_exports_or_print_documents(client, ctx, db_session, seeded_users, monkeypatch):
    from cryptography.fernet import Fernet

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    eq = await _equipment(client, ctx["admin"], "h1", bcm="BCM-H1")
    hn = "HN-7391/66"
    tx = await _dispatch(client, ctx["staff"], eq, ctx["ward_a"], hn=hn)
    await _receive(client, ctx["staff"], tx["id"])
    header, rows = await _rows(db_session)
    assert not any("hn" in h.lower() for h in header)
    assert hn not in "".join(",".join(r) for r in rows)
    ws = load_workbook(io.BytesIO(await report_service.export_xlsx(db_session))).active
    assert not any("hn" in str(c.value).lower() for c in ws[1])
    admin = seeded_users["administrator"]
    for build in (report_export_service.build_receive_report_document, report_export_service.build_issue_report_document):
        doc = await build(db_session, generated_by=admin)
        assert not any("hn" in c.key.lower() for c in doc.columns)
        assert all("hn" not in k.lower() for row in doc.rows for k in row.values)
        assert hn not in doc.model_dump_json()
