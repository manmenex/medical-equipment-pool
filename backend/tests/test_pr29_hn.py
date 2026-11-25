"""Roadmap PR29 (Owner Governance 2026-11-25 D1): optional patient HN on a
dispatch -- encrypted at rest, never returned except by the audited reveal.

SQLite; the PostgreSQL migration proof lives in test_pr29_postgres.py.
"""
import json
import logging
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text

from app.core import hn_crypto
from app.core.audit import redact_sensitive
from app.core.config import get_settings
from app.core.exceptions import HnUnavailableError
from app.core.logging import JsonFormatter, redact_hn_text
from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.schemas.sync import SyncOperation
from app.services import sync_service
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward
from tests.test_pr25e_b2_sync_ops import _send, _user, dispatch_op

pytestmark = pytest.mark.asyncio

HN = "HN-7391/66"  # unique, greppable marker; valid under the format rule


@pytest.fixture
def hn_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", key)
    return key


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", None)


@pytest.fixture
async def ctx(client, seeded_users, hn_key):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    return {
        "admin": admin,
        "staff": staff,
        "ro": ro,
        "staff_id": await _user(client, staff),
        "ward": await _create_ward(client, admin, "W-29", "Ward 29"),
        "ward_b": await _create_ward(client, admin, "W-29B", "Ward 29B"),
    }


async def _equipment(client, admin, n):
    r = await client.post(
        "/api/v1/equipment",
        headers=admin,
        json={"asset_number": f"AST-29-{n}", "equipment_name": f"Dev {n}", "bcm_code": f"BCM-29-{n}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _borrow(client, headers, eq, ward, **extra):
    return await client.post("/api/v1/borrow", headers=headers, json={"equipment_id": eq, "ward_id": ward, **extra})


async def _row(db_session, tx_id) -> BorrowTransaction:
    db_session.expire_all()
    return (
        await db_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx_id)))
    ).scalar_one()


async def _ciphertext(db_session, tx_id) -> str | None:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(BorrowTransaction.hn_ciphertext).where(BorrowTransaction.id == uuid.UUID(tx_id))
        )
    ).scalar_one()


# --------------------------------------------------------------------------
# Encryption primitives
# --------------------------------------------------------------------------


async def test_encryption_round_trip_and_ciphertext_is_not_plaintext(hn_key):
    token = hn_crypto.encrypt_hn(HN)
    assert HN not in token and token != HN
    assert hn_crypto.decrypt_hn(token) == HN
    # Fernet is randomised: same value, different token.
    assert hn_crypto.encrypt_hn(HN) != token


async def test_key_rotation_old_key_still_decrypts(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", old)
    token = hn_crypto.encrypt_hn("12345")
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", f"{new},{old}")
    assert hn_crypto.decrypt_hn(token) == "12345"
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", new)
    with pytest.raises(HnUnavailableError):
        hn_crypto.decrypt_hn(token)


@pytest.mark.parametrize("bad", [None, "", "   ", "not-a-fernet-key", "short"])
async def test_missing_or_malformed_key_is_unavailable(monkeypatch, bad):
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", bad)
    assert hn_crypto.hn_available() is False
    with pytest.raises(HnUnavailableError):
        hn_crypto.encrypt_hn("12345")
    with pytest.raises(HnUnavailableError):
        hn_crypto.decrypt_hn("anything")


@pytest.mark.parametrize("value,expected", [(None, None), ("", None), ("  ", None), (" 12345 ", "12345"), ("AB-12/3", "AB-12/3")])
async def test_normalize_hn(value, expected):
    assert hn_crypto.normalize_hn(value) == expected


@pytest.mark.parametrize("bad", ["x" * 21, "12 34", "12;34", "12.34", "ก123", "1\n2"])
async def test_normalize_hn_rejects_bad_format_without_echoing_value(bad):
    with pytest.raises(ValueError) as exc:
        hn_crypto.normalize_hn(bad)
    assert bad.strip() not in str(exc.value)


# --------------------------------------------------------------------------
# Dispatch + storage
# --------------------------------------------------------------------------


async def test_borrow_with_hn_stores_ciphertext_only_and_exposes_has_hn(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 1)
    r = await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=f"  {HN} ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["has_hn"] is True
    assert "hn" not in body and "hn_ciphertext" not in body
    assert HN not in r.text

    token = await _ciphertext(db_session, body["id"])
    assert token and HN not in token
    assert hn_crypto.decrypt_hn(token) == HN  # trimmed before encryption
    assert (await _row(db_session, body["id"])).has_hn is True


async def test_borrow_without_hn_or_blank_hn_records_none(client, ctx, db_session):
    e1, e2 = await _equipment(client, ctx["admin"], 2), await _equipment(client, ctx["admin"], 3)
    a = (await _borrow(client, ctx["staff"], e1, ctx["ward"])).json()
    b = (await _borrow(client, ctx["staff"], e2, ctx["ward"], hn="   ")).json()
    for tx in (a, b):
        assert tx["has_hn"] is False
        assert await _ciphertext(db_session, tx["id"]) is None


async def test_borrow_rejects_bad_hn_format_with_422_that_does_not_echo_it(client, ctx):
    eq = await _equipment(client, ctx["admin"], 4)
    for bad in ("x" * 21, "12 34"):
        r = await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=bad)
        assert r.status_code == 422
        assert bad not in r.text


async def test_missing_key_rejects_hn_write_and_writes_nothing_but_app_otherwise_works(client, ctx, db_session, no_key):
    eq = await _equipment(client, ctx["admin"], 5)
    r = await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)
    assert r.status_code == 503
    assert r.json()["code"] == "HN_UNAVAILABLE"
    assert HN not in r.text
    assert (await db_session.execute(select(BorrowTransaction))).scalars().all() == []
    # No HN -> ordinary dispatch works with no key at all.
    ok = await _borrow(client, ctx["staff"], eq, ctx["ward"])
    assert ok.status_code == 201 and ok.json()["has_hn"] is False


async def test_missing_key_reveal_reports_unavailable_without_audit(client, ctx, db_session, monkeypatch):
    eq = await _equipment(client, ctx["admin"], 6)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)).json()
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", None)
    r = await client.post(f"/api/v1/transactions/{tx['id']}/reveal-hn", headers=ctx["staff"])
    assert r.status_code == 503 and r.json()["code"] == "HN_UNAVAILABLE"
    assert (await db_session.execute(select(AuditLog).where(AuditLog.action == "hn_reveal"))).scalars().all() == []
    # Reads of the transaction still work and still show only the indicator.
    got = await client.get(f"/api/v1/transactions/{tx['id']}", headers=ctx["staff"])
    assert got.status_code == 200 and got.json()["has_hn"] is True


async def test_batch_dispatch_items_carry_hn_per_equipment(client, ctx, db_session):
    e1, e2, e3 = [await _equipment(client, ctx["admin"], n) for n in (7, 8, 9)]
    r = await client.post(
        "/api/v1/transactions/dispatch-batch",
        headers=ctx["staff"],
        json={
            "ward_id": ctx["ward"],
            "items": [{"equipment_id": e1, "hn": HN}, {"equipment_id": e2}, {"equipment_id": e3, "hn": "9988"}],
        },
    )
    assert r.status_code == 200, r.text
    assert HN not in r.text and "9988" not in r.text
    results = r.json()["results"]
    assert [x["ok"] for x in results] == [True, True, True]
    flags = []
    for x in results:
        flags.append((await _row(db_session, x["transaction_id"])).has_hn)
    assert flags == [True, False, True]
    assert hn_crypto.decrypt_hn(await _ciphertext(db_session, results[2]["transaction_id"])) == "9988"


async def test_batch_bad_hn_is_a_422_for_the_whole_request(client, ctx):
    e1 = await _equipment(client, ctx["admin"], 10)
    r = await client.post(
        "/api/v1/transactions/dispatch-batch",
        headers=ctx["staff"],
        json={"ward_id": ctx["ward"], "items": [{"equipment_id": e1, "hn": "bad hn!"}]},
    )
    assert r.status_code == 422 and "bad hn!" not in r.text


async def test_receipt_schemas_still_forbid_hn(client, ctx):
    eq = await _equipment(client, ctx["admin"], 11)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"])).json()
    r = await client.post(f"/api/v1/return/{tx['id']}", headers=ctx["staff"], json={"receipt_outcome": "usable", "hn": "1"})
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Reveal endpoint, roles, audit
# --------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["staff", "admin"])
async def test_reveal_returns_plaintext_and_audits_actor_without_value(client, ctx, db_session, role):
    eq = await _equipment(client, ctx["admin"], 12)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)).json()
    r = await client.post(f"/api/v1/transactions/{tx['id']}/reveal-hn", headers=ctx[role])
    assert r.status_code == 200, r.text
    assert r.json() == {"hn": HN}
    assert r.headers["cache-control"] == "no-store"

    db_session.expire_all()
    rows = (await db_session.execute(select(AuditLog).where(AuditLog.action == "hn_reveal"))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.entity_type == "borrow_transaction" and str(row.entity_id) == tx["id"]
    assert row.user_id is not None and row.created_at is not None
    assert HN not in json.dumps([row.before_data, row.after_data], default=str)
    me = (await client.get("/api/v1/auth/me", headers=ctx[role])).json()["id"]
    assert str(row.user_id) == me


async def test_reveal_denied_for_read_only_and_anonymous_and_unaudited(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 13)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)).json()
    url = f"/api/v1/transactions/{tx['id']}/reveal-hn"
    assert (await client.post(url, headers=ctx["ro"])).status_code == 403
    assert (await client.post(url)).status_code == 401
    assert (await db_session.execute(select(AuditLog).where(AuditLog.action == "hn_reveal"))).scalars().all() == []


async def test_reveal_errors_for_no_hn_and_unknown_transaction(client, ctx):
    eq = await _equipment(client, ctx["admin"], 14)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"])).json()
    r = await client.post(f"/api/v1/transactions/{tx['id']}/reveal-hn", headers=ctx["staff"])
    assert r.status_code == 404 and r.json()["code"] == "HN_NOT_RECORDED"
    r = await client.post(f"/api/v1/transactions/{uuid.uuid4()}/reveal-hn", headers=ctx["staff"])
    assert r.status_code == 404 and r.json()["code"] == "TRANSACTION_NOT_FOUND"


async def test_every_reveal_is_audited_separately(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 15)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)).json()
    for _ in range(3):
        assert (await client.post(f"/api/v1/transactions/{tx['id']}/reveal-hn", headers=ctx["staff"])).status_code == 200
    db_session.expire_all()
    rows = (await db_session.execute(select(AuditLog).where(AuditLog.action == "hn_reveal"))).scalars().all()
    assert len(rows) == 3


async def test_audit_redacts_hn_keys_and_borrow_audit_has_only_the_indicator(client, ctx, db_session):
    assert redact_sensitive({"hn": HN, "patient_hn": HN, "hn_ciphertext": "x", "has_hn": True, "n": [{"hn": HN}]}) == {
        "hn": "***REDACTED***",
        "patient_hn": "***REDACTED***",
        "hn_ciphertext": "***REDACTED***",
        "has_hn": True,
        "n": [{"hn": "***REDACTED***"}],
    }
    eq = await _equipment(client, ctx["admin"], 16)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)).json()
    db_session.expire_all()
    audit = (await db_session.execute(select(AuditLog).where(AuditLog.action == "borrow"))).scalar_one()
    assert audit.after_data["has_hn"] is True
    r = await client.get("/api/v1/audit-logs", headers=ctx["admin"])
    assert r.status_code == 200 and HN not in r.text and "hn_ciphertext" not in r.text


# --------------------------------------------------------------------------
# HN absent from every read surface (grep-style)
# --------------------------------------------------------------------------


async def test_hn_absent_from_every_response_export_report_and_monitor(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 17)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)).json()
    rec = await client.post(f"/api/v1/return/{tx['id']}", headers=ctx["staff"], json={"receipt_outcome": "usable"})
    assert rec.status_code == 200
    eq2 = await _equipment(client, ctx["admin"], 18)
    open_tx = (await _borrow(client, ctx["staff"], eq2, ctx["ward_b"], hn=HN)).json()

    token = await _ciphertext(db_session, open_tx["id"])
    paths = [
        f"/api/v1/transactions/{tx['id']}",
        f"/api/v1/transactions/{open_tx['id']}",
        "/api/v1/transactions",
        "/api/v1/transactions?event=receipt",
        "/api/v1/borrow/active",
        f"/api/v1/equipment/{eq}",
        f"/api/v1/equipment/{eq2}",
        f"/api/v1/equipment/{eq2}/history",
        f"/api/v1/equipment/{eq2}/dispatch-check",
        "/api/v1/equipment",
        "/api/v1/monitor/events?kind=dispatch",
        "/api/v1/monitor/events?kind=receipt",
        "/api/v1/reports/receive",
        "/api/v1/reports/issue",
        "/api/v1/reports/issue-report/print-data",
        "/api/v1/reports/receive-report/print-data",
        "/api/v1/reports/issue-report/xlsx",
        "/api/v1/reports/issue-report/pdf",
        "/api/v1/reports/export",
        "/api/v1/audit-logs",
        "/api/v1/notifications",
        "/api/v1/dashboard/summary",
        "/api/v1/sync/snapshot",
        "/api/v1/sync/conflicts",
        f"/api/v1/sync/equipment/{eq2}/timeline",
    ]
    seen = 0
    for path in paths:
        r = await client.get(path, headers=ctx["admin"])
        if r.status_code >= 500:
            pytest.fail(f"{path}: {r.status_code}")
        blob = r.content.decode("utf-8", errors="ignore")
        assert HN not in blob, path
        assert "hn_ciphertext" not in blob, path
        assert token not in blob, path
        seen += r.status_code == 200
    assert seen >= 15  # most surfaces really answered; none leaked

    key = (await client.post("/api/v1/export-keys", headers=ctx["admin"], json={"name": "hn-test"})).json()["key"]
    ev = await client.get("/api/v1/export/events", headers={"X-API-Key": key})
    assert ev.status_code == 200 and ev.json()["events"]
    assert HN not in ev.text and "has_hn" not in ev.text and "hn" not in json.dumps(ev.json()).lower().replace("hn-test", "")

    # Binary renderings: xlsx is a zip (strings are deflated) so also check the
    # decoded workbook; pdf text is checked through the generating service in
    # test_pr18d. Column keys themselves must not include an HN column.
    mon = (await client.get("/api/v1/monitor/events?kind=dispatch", headers=ctx["staff"])).json()
    flagged = [e for e in mon["items"] if e["id"] == open_tx["id"]]
    assert flagged and flagged[0]["has_hn"] is True


async def test_reports_csv_and_xlsx_services_have_no_hn(client, ctx, db_session):
    from io import BytesIO

    from openpyxl import load_workbook

    from app.services import report_service

    eq = await _equipment(client, ctx["admin"], 19)
    await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)
    csv_text = (await report_service.export_csv(db_session)).decode("utf-8-sig")
    assert HN not in csv_text
    assert "hn" not in csv_text.splitlines()[0].lower().replace("has_hn", "").split(",")  # no HN column
    ws = load_workbook(BytesIO(await report_service.export_xlsx(db_session))).active
    cells = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert not any(HN in c for c in cells)


# --------------------------------------------------------------------------
# Logs
# --------------------------------------------------------------------------


async def test_hn_never_reaches_any_log_record(client, ctx, caplog):
    caplog.set_level(logging.DEBUG)
    eq = await _equipment(client, ctx["admin"], 20)
    r = await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)
    tx = r.json()
    await _borrow(client, ctx["staff"], await _equipment(client, ctx["admin"], 21), ctx["ward"], hn="bad hn value")
    await client.post(f"/api/v1/transactions/{tx['id']}/reveal-hn", headers=ctx["staff"])
    fmt = JsonFormatter()
    for rec in caplog.records:
        out = fmt.format(rec)
        assert HN not in out and "bad hn value" not in out
        assert HN not in rec.getMessage()


async def test_log_formatter_redacts_stray_hn_in_messages_and_tracebacks():
    assert "7391" not in redact_hn_text("saved hn=7391 for tx")
    assert "7391" not in redact_hn_text("input_value={'hn': '7391', 'ward_id': 'x'}")
    assert redact_hn_text("has_hn=True") == "has_hn=True"
    log = logging.getLogger("hn-redaction-test")
    try:
        raise ValueError("bad {'hn': 'SECRET-HN-1'}")
    except ValueError:
        rec = log.makeRecord("x", logging.ERROR, __file__, 1, "failed hn=SECRET-HN-2", (), __import__("sys").exc_info())
    out = JsonFormatter().format(rec)
    assert "SECRET-HN-1" not in out and "SECRET-HN-2" not in out


# --------------------------------------------------------------------------
# Offline sync
# --------------------------------------------------------------------------


async def test_sync_dispatch_with_hn_stored_encrypted_and_ledger_has_no_hn(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 22)
    op = dispatch_op(ctx["staff_id"], eq, ctx["ward"], hn=HN)
    [res] = await _send(client, ctx["staff"], op)
    assert res["result"] == "applied", res
    assert HN not in json.dumps(res)

    tx = (await db_session.execute(select(BorrowTransaction))).scalar_one()
    assert tx.has_hn is True
    assert hn_crypto.decrypt_hn(await _ciphertext(db_session, str(tx.id))) == HN

    row = (await db_session.execute(select(ClientOperation))).scalar_one()
    assert "hn" not in row.payload["dispatch"]
    assert HN not in json.dumps(row.payload, default=str)
    # Raw columns of the ledger row: grep-style across the whole table.
    dump = (await db_session.execute(text("SELECT * FROM client_operations"))).all()
    assert HN not in json.dumps([[str(c) for c in r] for r in dump])
    audit_dump = (await db_session.execute(text("SELECT before_data, after_data FROM audit_logs"))).all()
    assert HN not in json.dumps([[str(c) for c in r] for r in audit_dump])


async def test_sync_payload_hash_ignores_hn_so_old_and_retried_ops_still_match(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 23)
    with_hn = dispatch_op(ctx["staff_id"], eq, ctx["ward"], hn=HN)
    without = json.loads(json.dumps(with_hn))
    del without["dispatch"]["hn"]
    h1 = sync_service.payload_hash(SyncOperation.model_validate(with_hn).business_payload())
    h2 = sync_service.payload_hash(SyncOperation.model_validate(without).business_payload())
    assert h1 == h2  # an op queued before PR29 hashes exactly as before
    assert "hn" not in SyncOperation.model_validate(with_hn).business_payload()["dispatch"]
    assert HN not in repr(SyncOperation.model_validate(with_hn))

    [first] = await _send(client, ctx["staff"], with_hn)
    assert first["result"] == "applied"
    # Client retry after clearing its local HN (post-ack cleanup) is a plain duplicate.
    [again] = await _send(client, ctx["staff"], without)
    assert again["result"] == "duplicate"
    [again2] = await _send(client, ctx["staff"], with_hn)
    assert again2["result"] == "duplicate"


async def test_sync_dispatch_with_hn_but_no_key_is_rejected_and_clear(client, ctx, db_session, no_key):
    eq = await _equipment(client, ctx["admin"], 24)
    [res] = await _send(client, ctx["staff"], dispatch_op(ctx["staff_id"], eq, ctx["ward"], hn=HN))
    assert res["result"] in ("rejected", "conflict")
    assert res["code"] == "HN_UNAVAILABLE"
    assert HN not in json.dumps(res)
    assert (await db_session.execute(select(BorrowTransaction))).scalars().all() == []
    dump = (await db_session.execute(text("SELECT payload FROM client_operations"))).all()
    assert HN not in json.dumps([[str(c) for c in r] for r in dump])


async def test_sync_bad_hn_format_is_422_without_echo(client, ctx):
    eq = await _equipment(client, ctx["admin"], 25)
    r = await client.post(
        "/api/v1/sync/operations",
        headers=ctx["staff"],
        json={"operations": [dispatch_op(ctx["staff_id"], eq, ctx["ward"], hn="no good!!")]},
    )
    assert r.status_code == 422 and "no good!!" not in r.text


# --------------------------------------------------------------------------
# Deployment wiring (static): key generated by install/update, never printed
# --------------------------------------------------------------------------


def _repo(*parts) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[2].joinpath(*parts)).read_text(encoding="utf-8")


async def test_deployment_scripts_generate_but_never_print_or_overwrite_the_hn_key():
    common = _repo("deployment", "local-staging", "lib", "Common.ps1")
    ops = _repo("deployment", "local-staging", "lib", "Operations.ps1")
    compose = _repo("deployment", "local-staging", "compose.yml")
    example = _repo("deployment", "local-staging", ".env.example")
    assert 'HN_ENCRYPTION_KEY=$hnKey' in common  # fresh install writes it with the rest of .env
    assert "function Initialize-HnEncryptionKey" in common
    body = common.split("function Initialize-HnEncryptionKey", 1)[1].split("# ----", 1)[0]
    assert "IsNullOrWhiteSpace" in body  # only generated when absent/blank, never replaced
    for forbidden in ("Write-Host", "Write-Output", "Out-Host"):
        assert forbidden not in body
    assert "$key" not in body.split("Write-InstallLog", 1)[1].splitlines()[0]  # the log line never interpolates the key
    # install (existing .env) and update both ensure the key; compose passes it through.
    assert ops.count("Initialize-HnEncryptionKey") == 2
    assert 'HN_ENCRYPTION_KEY: "${HN_ENCRYPTION_KEY:-}"' in compose
    line = next(line for line in example.splitlines() if line.startswith("HN_ENCRYPTION_KEY="))
    assert line == "HN_ENCRYPTION_KEY="  # no secret shipped


async def test_install_runbook_documents_key_loss_and_separate_env_backup():
    text = _repo("docs", "runbooks", "CES_BCM_INSTALL_TH.md")
    assert "HN_ENCRYPTION_KEY" in text
    assert "อ่านไม่ได้ตลอดไป" in text and "สำรองไฟล์ `.env` แยกต่างหาก" in text
