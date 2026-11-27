"""Demo-only legacy pool sheet shadow sync (Governance 2026-10-21).

Synthetic data only: fake ward/equipment names, a throw-away RSA key
generated inside the test, and a mocked HTTP transport -- no real hospital
data, no real credentials, no network.
"""
import base64
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.client_operation import ClientOperation
from app.models.equipment import Equipment, EquipmentStatus
from app.models.master_data import Ward
from app.models.transaction import CLOSE_REASON_REDISPATCH, BorrowTransaction
from app.models.user import ROLE_EQUIPMENT_POOL_STAFF, Role, User
from app.services.legacy_sheet_sync import __main__ as cli
from app.services.legacy_sheet_sync import runner
from app.services.legacy_sheet_sync.config import BANGKOK, SyncConfig, SyncConfigError, load_config
from app.services.legacy_sheet_sync.sheet_parser import (
    KIND_DISPATCH,
    KIND_RECEIPT,
    HeaderError,
    _parse_date,
    _parse_time,
    parse_tab,
)
from app.services.system_notes import is_system_note, operator_note
from app.services.legacy_sheet_sync.sheets_client import GoogleSheetsReader, SheetsError

DISPATCH_HEADER = [
    "ลำดับ", "วันที่", "เลขที่ใบส่ง", "SCAN CODE (nsmart)", "ME.Code", "", "Equipment", "", "", "", "",
    "แผนกที่ส่ง", "หน้าจอไม่แตก", "สายชาร์จ", "ขาจับเสา", "จำนวน", "หมายเหตุ", "เวลา", "ชื่อ BME", "ชื่อ (User)",
]
RECEIPT_HEADER = [
    "ลำดับ", "วันที่", "เลขที่ใบรับเครื่อง", "SCAN CODE (nsmart)", "ME.Code", "", "Equipment", "", "", "",
    "แผนกที่รับ", "หน้าจอไม่แตก", "สายชาร์จ", "ขาจับเสา", "จำนวน", "หมายเหตุ", "เวลา", "ชื่อ BME", "ชื่อ (User)",
]
WARD_SIDE_NAME = "Nickname-Zed"  # column T: stored ONLY as the D7 ward contact name, never in a note


def when(hours_ago: float) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(second=0, microsecond=0)


def drow(row_id, hours_ago, bcm="BCM01078", ward="ICU3", marks=("✓", "✓", "✓"), note="", doc="Borrow1000000009210"):
    t = when(hours_ago).astimezone(BANGKOK)
    return [row_id, t.strftime("%d/%m/%Y"), doc, "https://nsmart.example/x", bcm, "", "Pump", "", "", "", "",
            ward, *marks, "1", note, t.strftime("%H:%M"), "Somchai", WARD_SIDE_NAME]


def rrow(row_id, hours_ago, bcm="BCM01078", ward="ICU3", marks=("✓", "✓", "✓"), note="", doc="Return100000009891"):
    t = when(hours_ago).astimezone(BANGKOK)
    return [row_id, t.strftime("%d/%m/%Y"), doc, "https://nsmart.example/x", bcm, "", "Pump", "", "", "",
            ward, *marks, "1", note, t.strftime("%H:%M"), "Somchai", WARD_SIDE_NAME]


class FakeReader:
    def __init__(self, dispatch=(), receipt=()):
        self.tabs = {"ข้อมูลส่งเครื่องมือ": [DISPATCH_HEADER, *dispatch], "ข้อมูลรับเครื่องมือ": [RECEIPT_HEADER, *receipt]}

    async def read_tab(self, title):
        return self.tabs[title]


def make_cfg(**kw):
    base = dict(enabled=True, key_file="k", spreadsheet_id="s", interval_seconds=300, start_override=None,
                employee_code="LEGACY-SYNC")
    base.update(kw)
    return SyncConfig(**base)


@pytest.fixture
async def world(db_engine, db_session, seeded_users):
    role = (await db_session.execute(select(Role).where(Role.name == ROLE_EQUIPMENT_POOL_STAFF))).scalar_one()
    db_session.add_all([
        User(employee_code="LEGACY-SYNC", full_name="Legacy Sync", email="legacy-sync@test.dev",
             password_hash="x", role_id=role.id),
        Ward(code="ICU3", name="ICU3"),
        Ward(code="W5A", name="Ward 5A"),
        Equipment(asset_number="AST-L1", equipment_name="Pump", bcm_code="BCM01078"),
        Equipment(asset_number="AST-L2", equipment_name="Pump", bcm_code="BCM01079"),
    ])
    await db_session.commit()
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


async def count(maker, model, *where):
    async with maker() as db:
        return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


# ---------------------------------------------------------------- parsing

async def test_header_detection_by_text_and_clear_failure():
    parsed = parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, drow("0a1b2c3d", 1)])
    assert len(parsed.rows) == 1 and parsed.rows[0].bcm_raw == "BCM01078"
    # reordered columns still work: located by header text, not by letter
    shuffled = list(reversed(DISPATCH_HEADER))
    cells = list(reversed(drow("0a1b2c3d", 1)))
    assert parse_tab(KIND_DISPATCH, [shuffled, cells]).rows[0].row_id == "0a1b2c3d"
    broken = [h if not h.startswith("ME.") else "รหัส" for h in DISPATCH_HEADER]
    with pytest.raises(HeaderError, match="bcm"):
        parse_tab(KIND_DISPATCH, [broken])
    with pytest.raises(HeaderError):
        parse_tab(KIND_RECEIPT, [DISPATCH_HEADER])  # receipt needs 'เลขที่ใบรับ'


async def test_timezone_bangkok_to_utc_and_buddhist_year():
    row = drow("0a1b2c3d", 1)
    row[1], row[17] = "21/10/2026", "08:30"
    r = parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, row]).rows[0]
    assert r.occurred_at == datetime(2026, 10, 21, 1, 30, tzinfo=timezone.utc)
    row[1] = "21/10/2569"
    assert parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, row]).rows[0].occurred_at.year == 2026


async def test_patient_like_and_bad_rows_skipped_without_echo():
    hn = drow("0a1b2c3d", 1, note="HN 1234567 bed 4")
    dup = drow("0a1b2c3e", 1)
    parsed = parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, hn, dup, dup, drow("zz", 1)])
    assert [s.reason for s in parsed.skipped] == ["possible_patient_identifier", "duplicate_row_id", "bad_row_id"]
    assert "1234567" not in json.dumps([s.__dict__ for s in parsed.skipped])
    assert len(parsed.rows) == 1


async def test_ward_side_name_parsed_as_contact_name_only():
    r = parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, drow("0a1b2c3d", 1)]).rows[0]
    assert r.user_name == WARD_SIDE_NAME and WARD_SIDE_NAME not in runner.build_note(r)
    old_header = [h for h in DISPATCH_HEADER if "(User)" not in h]  # older sheet without the column
    row = drow("0a1b2c3d", 1)[:-1]
    assert parse_tab(KIND_DISPATCH, [old_header, row]).rows[0].user_name == ""
    hn = drow("0a1b2c3e", 1)
    hn[-1] = "HN 1234567"
    assert parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, hn]).rows == []  # still HN-screened


async def test_system_note_filter():
    assert is_system_note(runner.build_note(parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, drow("0a1b2c3d", 1)]).rows[0]))
    assert operator_note("Legacy sheet receipt row 0a1b2c3d; BME x") is None
    assert operator_note("ฝาเครื่องร้าว") == "ฝาเครื่องร้าว" and operator_note(None) is None


async def test_accessory_flags_only_in_summary_and_notes_not_imported():
    r = parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, drow("0a1b2c3d", 1, marks=("✓", "✗", "✓"), note="secret free text")]).rows[0]
    note = runner.build_note(r)
    assert "สายชาร์จ ✗" in note and "secret free text" not in note
    assert "Somchai" in note and WARD_SIDE_NAME not in note


# ---------------------------------------------------------------- identifiers

async def test_op_id_is_stable_v4_and_device_seq_unique_increasing():
    a = runner.op_id_for("dispatch", "0A1B2C3D")
    assert a == runner.op_id_for("dispatch", "0a1b2c3d") and a.version == 4
    assert a != runner.op_id_for("receipt", "0a1b2c3d")
    assert runner.DEVICE_ID.version == 4
    rows = parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, drow("0a1b2c3d", 5), drow("0a1b2c3e", 5), drow("0a1b2c3f", 2)]).rows
    seqs = [runner.device_seq_for("dispatch", r) for r in rows]
    assert len(set(seqs)) == 3 and seqs[2] > seqs[0] and max(seqs) < 2**62
    rec = parse_tab(KIND_RECEIPT, [RECEIPT_HEADER, rrow("0a1b2c3d", 5)]).rows[0]
    assert runner.device_seq_for("receipt", rec) != seqs[0]


# ---------------------------------------------------------------- end to end

async def test_dispatch_applied_then_return_applied_against_it(world):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 3, marks=("✓", "✗", "✓"))])
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["applied"] == 1 and not rep.skipped
    async with world() as db:
        tx = (await db.execute(select(BorrowTransaction))).scalar_one()
        assert tx.id == runner.op_id_for("dispatch", "0a1b2c3d")  # dispatch tx id == op_id
        assert "BME Somchai" in tx.notes and "สายชาร์จ ✗" in tx.notes and WARD_SIDE_NAME not in tx.notes
        assert tx.dispatch_contact_name == WARD_SIDE_NAME  # D7: the sheet's "ชื่อ (User)"
        assert tx.dispatch_keyer_label == "Somchai"  # D22: display-only BME label
        assert tx.borrower_user_id is not None  # the actor stays the sync service user
        assert is_system_note(tx.notes) and operator_note(tx.notes) is None  # never printed
        assert tx.status.value == "open"
    reader.tabs["ข้อมูลรับเครื่องมือ"].append(rrow("0a1b2c3e", 1))
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["applied"] == 1 and rep.counts["already_applied"] == 1
    async with world() as db:
        tx = (await db.execute(select(BorrowTransaction))).scalar_one()
        assert tx.status.value == "closed"
        assert tx.receipt_contact_name == WARD_SIDE_NAME
        assert tx.receipt_keyer_label == "Somchai" and tx.dispatch_keyer_label == "Somchai"
        ops = (await db.execute(select(ClientOperation))).scalars().all()
        assert {o.status for o in ops} == {"applied"} and {o.device_id for o in ops} == {runner.DEVICE_ID}
        for o in ops:  # the name travels only as the contact name, never inside a note
            body = o.payload.get("dispatch") or o.payload.get("receipt") or {}
            assert WARD_SIDE_NAME not in (body.get("notes") or "")


async def test_run_once_survives_expiring_sessions_commit_and_rollback(db_engine, world, monkeypatch):
    """Regression: with expire_on_commit=True (SQLAlchemy default) and a row
    that errors (rollback), cached ORM objects used to be expired and the next
    sync attribute access raised MissingGreenlet."""
    expiring = async_sessionmaker(db_engine, class_=AsyncSession)  # expire_on_commit=True
    bad_op = runner.op_id_for("dispatch", "0a1b2c3f")
    real = runner.sync_service.process_operation

    async def flaky(db, op, user, **kw):
        if op.op_id == bad_op:
            raise RuntimeError("boom")
        return await real(db, op, user, **kw)

    monkeypatch.setattr(runner.sync_service, "process_operation", flaky)
    reader = FakeReader(
        dispatch=[
            drow("0a1b2c3d", 5, bcm="BCM01078"),
            drow("0a1b2c3f", 4, bcm="BCM01079"),  # errors -> rollback
            drow("0a1b2c40", 3, bcm="BCM01079"),  # good row after the rollback
        ],
        receipt=[rrow("0a1b2c3e", 1, bcm="BCM01078")],
    )
    rep = await runner.run_once(expiring, reader, make_cfg())
    assert rep.counts["applied"] == 3 and rep.counts["error"] == 1
    assert not any("MissingGreenlet" in r["reason"] for r in rep.skipped)
    assert await count(world, BorrowTransaction) == 2


async def test_rerun_is_idempotent(world):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 3)], receipt=[rrow("0a1b2c3e", 1)])
    await runner.run_once(world, reader, make_cfg())
    before = (await count(world, BorrowTransaction), await count(world, ClientOperation))
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["already_applied"] == 2 and "applied" not in rep.counts
    assert (await count(world, BorrowTransaction), await count(world, ClientOperation)) == before == (1, 2)


async def test_return_without_sheet_dispatch_uses_open_transaction(world):
    await runner.run_once(world, FakeReader(dispatch=[drow("0a1b2c3d", 3)]), make_cfg())
    rep = await runner.run_once(world, FakeReader(receipt=[rrow("0a1b2c3e", 1)]), make_cfg())
    assert rep.counts["applied"] == 1
    # and with nothing open it is skipped and reported, not guessed
    rep = await runner.run_once(world, FakeReader(receipt=[rrow("0a1b2c3f", 0.5, bcm="BCM01079")]), make_cfg())
    assert rep.skipped[0]["reason"] == "no_open_transaction"


async def test_unknown_ward_and_bcm_skipped_and_reported(world):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 3, ward="Nowhere"), drow("0a1b2c3e", 3, bcm="BKN1741"),
                                  drow("0a1b2c3f", 3, ward="ward  5a"),
                                  drow("0a1b2c41", 3, bcm="BCM01079", ward="Nowhere")])
    rep = await runner.run_once(world, reader, make_cfg())
    reasons = sorted(s["reason"].split(":")[0] for s in rep.skipped)
    assert reasons == ["unknown_bcm", "unknown_ward", "unknown_ward"] and rep.counts["applied"] == 1  # 'ward  5a' normalised
    # a return whose dispatch was skipped is not applied to something else
    reader.tabs["ข้อมูลรับเครื่องมือ"].append(rrow("0a1b2c40", 1, bcm="BCM01079"))
    rep = await runner.run_once(world, reader, make_cfg())
    assert any(s["reason"].startswith("matching_dispatch_skipped") for s in rep.skipped)


async def test_dispatch_of_already_issued_item_redispatches_per_d8(world):
    """D8 applies to the sheet path: a dispatch row for an item still out is
    applied (previous open transaction closed by re-dispatch), not a conflict."""
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 4), drow("0a1b2c3e", 3, ward="Ward 5A")])
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["applied"] == 2 and not rep.counts["conflict"] and not rep.review
    async with world() as db:
        first = await db.get(BorrowTransaction, runner.op_id_for("dispatch", "0a1b2c3d"))
        second = await db.get(BorrowTransaction, runner.op_id_for("dispatch", "0a1b2c3e"))
        assert first.status.value == "closed" and first.close_reason == CLOSE_REASON_REDISPATCH
        assert second.status.value == "open"
        for key in ("0a1b2c3d", "0a1b2c3e"):
            row = await db.get(ClientOperation, runner.op_id_for("dispatch", key))
            assert row.status == "applied" and row.occurred_at is not None
    # a later sheet receipt closes the NEW transaction
    reader.tabs["ข้อมูลรับเครื่องมือ"].append(rrow("0a1b2c3f", 1, ward="Ward 5A"))
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["applied"] == 1


async def test_conflict_row_records_occurred_at_and_decommissioned_still_blocked(world):
    async with world() as db:
        eq = (await db.execute(select(Equipment).where(Equipment.bcm_code == "BCM01078"))).scalar_one()
        eq.status = EquipmentStatus.DECOMMISSIONED
        await db.commit()
    rep = await runner.run_once(world, FakeReader(dispatch=[drow("0a1b2c3d", 3)]), make_cfg())
    assert rep.review == [{"tab": "dispatch", "row_id": "0a1b2c3d", "result": "conflict", "code": "EQUIPMENT_NOT_AVAILABLE"}]
    async with world() as db:
        row = await db.get(ClientOperation, runner.op_id_for("dispatch", "0a1b2c3d"))
        assert row.status == "conflict" and row.occurred_at is not None
        assert abs((row.occurred_at.replace(tzinfo=timezone.utc) - when(3)).total_seconds()) < 1


async def test_dry_run_writes_nothing_and_backfill_start_applies(world):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 3), drow("0a1b2c3e", 24 * 9, bcm="BCM01079")],
                        receipt=[rrow("0a1b2c3f", 1)])
    rep = await runner.run_once(world, reader, make_cfg(), dry_run=True)
    assert rep.counts["would_apply"] == 2 and rep.counts["before_start"] == 1  # 9-day-old row outside now-7d
    assert await count(world, ClientOperation) == 0 and await count(world, BorrowTransaction) == 0
    early = make_cfg(start_override=datetime.now(timezone.utc) - timedelta(days=30))
    rep = await runner.run_once(world, reader, early)
    assert rep.counts["conflict"] == 1  # OP_TOO_OLD goes to review
    assert rep.review[0]["code"] == "OP_TOO_OLD"


async def test_missing_sync_user_fails_clearly(world):
    with pytest.raises(SyncConfigError, match="NOPE"):
        await runner.run_once(world, FakeReader(), make_cfg(employee_code="NOPE"))


# ---------------------------------------------------------------- config / safety

def test_disabled_by_default(monkeypatch, capsys):
    assert load_config({}).enabled is False
    assert load_config({"LEGACY_SHEET_SYNC_ENABLED": "true"}).enabled is True
    for name in ("LEGACY_SHEET_SYNC_ENABLED", "LEGACY_SHEET_SYNC_KEY_FILE", "LEGACY_SHEET_SYNC_SPREADSHEET_ID"):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["--once"]) == 2
    assert "disabled" in capsys.readouterr().out
    idled = []
    monkeypatch.setattr(cli, "_idle", lambda: idled.append(True))
    assert cli.main(["--loop"]) == 0 and idled  # disabled loop idles, never syncs


async def test_interval_and_start_parsing():
    c = load_config({"LEGACY_SHEET_SYNC_INTERVAL_SECONDS": "5", "LEGACY_SHEET_SYNC_START_DATE": "2026-10-01"})
    assert c.interval_seconds == 60  # floor
    assert c.start_override == datetime(2026, 9, 30, 17, 0, tzinfo=timezone.utc)
    with pytest.raises(SyncConfigError):
        load_config({"LEGACY_SHEET_SYNC_START_DATE": "yesterday"})


def _write_key(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    path = tmp_path / "super-secret-key-location.json"
    path.write_text(json.dumps({"type": "service_account", "client_email": "svc@example.iam.gserviceaccount.com",
                                "private_key": pem, "private_key_id": "k1", "token_uri": "https://evil.example/token"}))
    return str(path)


async def test_reader_uses_readonly_scope_only_get_and_never_logs_key_path(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    key_file = _write_key(tmp_path)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.url.host == "oauth2.googleapis.com":
            form = dict(p.split("=", 1) for p in request.content.decode().split("&"))
            payload = form["assertion"].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            assert claims["scope"] == "https://www.googleapis.com/auth/spreadsheets.readonly"
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"values": [["a", 1], ["b"]]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        reader = GoogleSheetsReader(key_file, "sheet-id", http)
        assert await reader.read_tab("ข้อมูลส่งเครื่องมือ") == [["a", "1"], ["b"]]
    assert seen[0][1] == "https://oauth2.googleapis.com/token"  # token_uri in the file is ignored
    assert all(m in ("POST", "GET") for m, _ in seen) and [m for m, u in seen if "sheets.googleapis" in u] == ["GET"]
    assert "super-secret-key-location" not in caplog.text


async def test_unreadable_key_error_and_http_error_do_not_leak_path(tmp_path):
    bad = str(tmp_path / "super-secret-missing.json")
    with pytest.raises(SyncConfigError) as e:
        await GoogleSheetsReader(bad, "s").read_tab("t")
    assert "super-secret" not in str(e.value) and str(tmp_path) not in str(e.value)
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json")
    with pytest.raises(SyncConfigError) as e:
        await GoogleSheetsReader(str(corrupt), "s").read_tab("t")
    assert "corrupt" not in str(e.value)
    ok_key = _write_key(tmp_path)
    forbidden = httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "t", "expires_in": 9})
                                    if r.url.host == "oauth2.googleapis.com" else httpx.Response(403))
    async with httpx.AsyncClient(transport=forbidden) as http:
        with pytest.raises(SheetsError, match="HTTP 403") as e:
            await GoogleSheetsReader(ok_key, "s", http).read_tab("t")
    assert ok_key not in str(e.value)


def test_compose_service_is_profile_gated_readonly_and_unpublished():
    import pathlib

    import yaml

    compose = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[2] / "deployment/local-staging/compose.yml").read_text(encoding="utf-8")
    )
    svc = compose["services"]["legacy-sheet-sync"]
    assert svc["profiles"] == ["legacy-sheet-sync"]  # never starts with a plain `up`
    assert "ports" not in svc
    assert svc["environment"]["LEGACY_SHEET_SYNC_ENABLED"].endswith(":-false}")
    assert all(v.endswith(":ro") for v in svc["volumes"])
    assert svc["volumes"][0].startswith("./secrets/legacy-sheet:")
    assert svc["restart"] == "unless-stopped"


def test_update_and_stop_scripts_handle_the_profile_service():
    """Static guard: the profile-gated service must be stopped before the
    pre-update backup/migration, rebuilt, restarted afterwards, and stopped by
    stop.ps1 (a plain `compose stop` skips profile services)."""
    import pathlib

    base = pathlib.Path(__file__).resolve().parents[2] / "deployment/local-staging"
    ops = (base / "lib/Operations.ps1").read_text(encoding="utf-8")
    update = ops[ops.index("function Invoke-MepUpdate"):ops.index("function Invoke-MepStart")]
    assert update.index("Stop-MepLegacySync") < update.index("Invoke-MepBackup -Reason 'pre-update'")
    assert "Start-MepApplication" in update  # which calls Start-MepLegacySync
    assert "Start-MepLegacySync\n}" in ops
    assert "'build', 'legacy-sheet-sync'" in ops
    stop = ops[ops.index("function Invoke-MepStop"):ops.index("function Invoke-MepUninstall")]
    assert "'--profile', $Script:LegacySyncProfile, 'stop'" in stop
    enable = (base / "lib/LegacySheetSync.ps1").read_text(encoding="utf-8")
    assert "Set-MepEnvValue -Name 'COMPOSE_PROFILES'" in enable
    assert "Remove-MepEnvValue -Name 'COMPOSE_PROFILES'" in enable


def test_runtime_lock_is_installed_with_require_hashes():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    assert "pip install --no-cache-dir --require-hashes -r requirements.runtime.lock" in (
        root / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "google-auth==" in (root / "backend/requirements.runtime.lock").read_text(encoding="utf-8")


def test_cli_error_output_has_no_key_path(monkeypatch, capsys, tmp_path):
    missing = str(tmp_path / "super-secret-missing.json")
    monkeypatch.setenv("LEGACY_SHEET_SYNC_ENABLED", "true")
    monkeypatch.setenv("LEGACY_SHEET_SYNC_KEY_FILE", missing)
    monkeypatch.setenv("LEGACY_SHEET_SYNC_SPREADSHEET_ID", "sheet")
    assert cli.main(["--once", "--dry-run"]) == 1
    out = capsys.readouterr()
    assert "super-secret" not in out.out + out.err and "ERROR" in out.err


@pytest.mark.parametrize(
    "text,expected",
    [
        ("24/Nov/2026", (2026, 11, 24)),
        ("25-nov-2026", (2026, 11, 25)),
        ("1/SEPT/2026", (2026, 9, 1)),
        ("3/September/2026", (2026, 9, 3)),
        ("5/Jan/2569", (2026, 1, 5)),
        ("24/พ.ย./2569", (2026, 11, 24)),
        ("24 พ. ย. 2569", (2026, 11, 24)),
        ("2/ม.ค./2026", (2026, 1, 2)),
        ("24/11/2026", (2026, 11, 24)),
        ("2026-11-24", (2026, 11, 24)),
    ],
)
def test_parse_date_formats(text, expected):
    assert _parse_date(text).timetuple()[:3] == expected


@pytest.mark.parametrize("text", ["24/Foo/2026", "24/Nove/2026", "24/Nov/", "Nov/2026", ""])
def test_parse_date_rejects_invalid(text):
    with pytest.raises(ValueError):
        _parse_date(text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("22:07:30", (22, 7, 30)),
        ("7:42:11", (7, 42, 11)),
        ("7:42 PM", (19, 42, 0)),
        ("12:05:00 am", (0, 5, 0)),
        ("12:05 PM", (12, 5, 0)),
        ("08.30 น.", (8, 30, 0)),
    ],
)
def test_parse_time_formats(text, expected):
    t = _parse_time(text)
    assert (t.hour, t.minute, t.second) == expected


def test_parse_time_rejects_bad_ampm_hour():
    with pytest.raises(ValueError):
        _parse_time("13:00 PM")


# ---------------------------------------------------------------- D19 duplicate receipts

async def _dup_setup(world, ward="ICU3", receipt_hours=1):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 60, ward=ward)], receipt=[rrow("0a1b2c3e", receipt_hours, ward=ward)])
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["applied"] == 2
    return reader


async def test_d19_duplicate_receipt_same_ward_within_window_is_skipped(world):
    reader = await _dup_setup(world)
    reader.tabs["ข้อมูลรับเครื่องมือ"].append(rrow("0a1b2c3f", 0.5))
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["already_received"] == 1 and not rep.review and not rep.counts["conflict"]
    assert await count(world, ClientOperation) == 2  # nothing filed for the duplicate


async def test_d19_receipt_outside_window_still_conflicts(world):
    reader = await _dup_setup(world, receipt_hours=40)
    reader.tabs["ข้อมูลรับเครื่องมือ"].append(rrow("0a1b2c3f", 0.5))
    rep = await runner.run_once(world, reader, make_cfg())
    assert "already_received" not in rep.counts
    assert rep.review and rep.review[0]["code"] == "TRANSACTION_ALREADY_RETURNED"


async def test_d19_window_is_configurable(world):
    reader = await _dup_setup(world, receipt_hours=4)
    reader.tabs["ข้อมูลรับเครื่องมือ"].append(rrow("0a1b2c3f", 0.5))
    rep = await runner.run_once(world, reader, make_cfg(receipt_dedupe_window_hours=1))
    assert "already_received" not in rep.counts and rep.review


async def test_d19_different_ward_still_conflicts(world):
    reader = await _dup_setup(world)
    reader.tabs["ข้อมูลรับเครื่องมือ"].append(rrow("0a1b2c3f", 0.5, ward="Ward 5A"))
    rep = await runner.run_once(world, reader, make_cfg())
    assert "already_received" not in rep.counts
    assert rep.review and rep.review[0]["code"] == "TRANSACTION_ALREADY_RETURNED"


async def test_d19_closed_by_redispatch_is_not_a_receipt(world):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 5), drow("0a1b2c3e", 4, ward="Ward 5A")])
    await runner.run_once(world, reader, make_cfg())  # first tx closed by re-dispatch
    reader.tabs["ข้อมูลรับเครื่องมือ"].append(rrow("0a1b2c3f", 4.5, ward="ICU3"))
    rep = await runner.run_once(world, reader, make_cfg())
    assert "already_received" not in rep.counts
    assert rep.review and rep.review[0]["code"] == "TRANSACTION_CLOSED_BY_REDISPATCH"


# ---------------------------------------------------------------- sheet checks (D4/D10)

def test_parser_maps_check_marks():
    r = parse_tab(KIND_DISPATCH, [DISPATCH_HEADER, drow("0a1b2c3d", 1, marks=("✓", "✗", ""))]).rows[0]
    assert r.check_marks == {"screen": True, "charger": False, "clamp": None}
    odd = [h if h != "ขาจับเสา" else "อื่นๆ" for h in DISPATCH_HEADER]
    assert parse_tab(KIND_DISPATCH, [odd, drow("0a1b2c3d", 1)]).rows[0].check_marks == {}  # no clean mapping


async def _only_tx(world):
    async with world() as db:
        return (await db.execute(select(BorrowTransaction))).scalar_one()


async def test_standard_checks_written_for_check_and_cross(world):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 3, marks=("✓", "✗", "✓"))], receipt=[rrow("0a1b2c3e", 1, marks=("✓", "✓", "✗"))])
    await runner.run_once(world, reader, make_cfg())
    tx = await _only_tx(world)
    assert tx.dispatch_checks == {"kind": "standard", "screen_ok": True, "charger_ok": False, "clamp_ok": True}
    assert tx.receipt_checks == {"kind": "standard", "screen_ok": True, "charger_ok": True, "clamp_ok": False}


async def test_blank_mark_leaves_checks_null(world):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 3, marks=("✓", "", "✓"))])
    await runner.run_once(world, reader, make_cfg())
    assert (await _only_tx(world)).dispatch_checks is None


async def test_cryo_cuff_category_leaves_checks_null(world):
    from app.models.master_data import EquipmentCategory
    async with world() as db:
        cat = EquipmentCategory(name="Cryo Cuff", checklist_kind="cryo_cuff")
        db.add(cat)
        await db.flush()
        eq = (await db.execute(select(Equipment).where(Equipment.bcm_code == "BCM01078"))).scalar_one()
        eq.category_id = cat.id
        await db.commit()
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 3, marks=("✓", "✗", "✓"))])
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["applied"] == 1
    assert (await _only_tx(world)).dispatch_checks is None


def test_receipt_tab_role_labelled_headers_are_mapped():
    header = list(RECEIPT_HEADER)
    header[-2], header[-1] = "ผู้รับเครื่อง (BME)", "ผู้ส่งเครื่องยืม (User)"
    r = parse_tab(KIND_RECEIPT, [header, rrow("0a1b2c3d", 5)]).rows[0]
    assert r.bme_name == "Somchai" and r.user_name == WARD_SIDE_NAME


REAL_CHECKS = ["ตัวเครื่องหน้าจอไม่แตกร้าว", "สายชาร์จ (สายไม่ขาด)", "Pole Clamp (ไม่แตกหักไม่งอ)"]
REAL_DISPATCH_HEADER = [
    "ลำดับ", "วันที่", "เลขที่ใบส่งเครื่อง", "SCAN CODE ส่ง", "ME.Code", "", "Equipment", "", "", "", "", "แผนกที่ส่ง",
    *REAL_CHECKS, "จำนวน", "หมายเหตุ", "เวลา", "ชื่อ BME", "ชื่อ (User)",
]
REAL_RECEIPT_HEADER = [
    "ลำดับ", "วันที่", "เลขที่ใบรับเครื่อง", "SCAN CODE รับ", "ME.Code", "", "Equipment", "", "", "", "แผนกที่รับ",
    *REAL_CHECKS, "จำนวน", "หมายเหตุ", "เวลา", "ชื่อ BME", "ชื่อ (User)",
]


def test_real_sheet_headers_map_checks_and_marks():
    d = parse_tab(KIND_DISPATCH, [REAL_DISPATCH_HEADER, drow("0a1b2c3d", 3, marks=("✔", "❌", "✔️"))]).rows[0]
    assert d.check_marks == {"screen": True, "charger": False, "clamp": True}
    r = parse_tab(KIND_RECEIPT, [REAL_RECEIPT_HEADER, rrow("0a1b2c3e", 1, marks=("✔", "✖", "✔"))]).rows[0]
    assert r.check_marks == {"screen": True, "charger": False, "clamp": True}
    assert r.bme_name == "Somchai" and r.user_name == WARD_SIDE_NAME
    assert list(r.failed_accessories) == [REAL_CHECKS[1]]


async def test_receipt_end_to_end_with_real_headers(world):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 3)], receipt=[rrow("0a1b2c3e", 1, marks=("✔", "✔", "✔"))])
    reader.tabs["ข้อมูลส่งเครื่องมือ"][0] = REAL_DISPATCH_HEADER
    reader.tabs["ข้อมูลรับเครื่องมือ"][0] = REAL_RECEIPT_HEADER
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["applied"] == 2 and not rep.skipped
    async with world() as db:
        tx = (await db.execute(select(BorrowTransaction))).scalar_one()
        assert tx.status.value == "closed"
        assert tx.receipt_keyer_label == "Somchai" and tx.receipt_contact_name == WARD_SIDE_NAME
        assert tx.receipt_checks is not None and tx.receipt_checks["screen_ok"] is True
        assert not is_system_note(tx.receipt_keyer_label)
