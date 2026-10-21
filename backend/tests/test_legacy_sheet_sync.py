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
from app.models.equipment import Equipment
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_EQUIPMENT_POOL_STAFF, Role, User
from app.services.legacy_sheet_sync import __main__ as cli
from app.services.legacy_sheet_sync import runner
from app.services.legacy_sheet_sync.config import BANGKOK, SyncConfig, SyncConfigError, load_config
from app.services.legacy_sheet_sync.sheet_parser import (
    KIND_DISPATCH,
    KIND_RECEIPT,
    HeaderError,
    parse_tab,
)
from app.services.legacy_sheet_sync.sheets_client import GoogleSheetsReader, SheetsError

DISPATCH_HEADER = [
    "ลำดับ", "วันที่", "เลขที่ใบส่ง", "SCAN CODE (nsmart)", "ME.Code", "", "Equipment", "", "", "", "",
    "แผนกที่ส่ง", "หน้าจอไม่แตก", "สายชาร์จ", "ขาจับเสา", "จำนวน", "หมายเหตุ", "เวลา", "ชื่อ BME", "ชื่อ (User)",
]
RECEIPT_HEADER = [
    "ลำดับ", "วันที่", "เลขที่ใบรับเครื่อง", "SCAN CODE (nsmart)", "ME.Code", "", "Equipment", "", "", "",
    "แผนกที่รับ", "หน้าจอไม่แตก", "สายชาร์จ", "ขาจับเสา", "จำนวน", "หมายเหตุ", "เวลา", "ชื่อ BME", "ชื่อ (User)",
]
WARD_SIDE_NAME = "Nickname-Zed"  # column T: must never be stored


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
        assert tx.status.value == "open"
    reader.tabs["ข้อมูลรับเครื่องมือ"].append(rrow("0a1b2c3e", 1))
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["applied"] == 1 and rep.counts["already_applied"] == 1
    async with world() as db:
        tx = (await db.execute(select(BorrowTransaction))).scalar_one()
        assert tx.status.value == "closed"
        ops = (await db.execute(select(ClientOperation))).scalars().all()
        assert {o.status for o in ops} == {"applied"} and {o.device_id for o in ops} == {runner.DEVICE_ID}
        assert WARD_SIDE_NAME not in json.dumps([o.payload for o in ops])


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


async def test_dispatch_of_already_issued_item_lands_in_review(world):
    reader = FakeReader(dispatch=[drow("0a1b2c3d", 4), drow("0a1b2c3e", 3, ward="Ward 5A")])
    rep = await runner.run_once(world, reader, make_cfg())
    assert rep.counts["applied"] == 1 and rep.counts["conflict"] == 1
    assert rep.review == [{"tab": "dispatch", "row_id": "0a1b2c3e", "result": "conflict", "code": "EQUIPMENT_NOT_AVAILABLE"}]
    async with world() as db:
        row = await db.get(ClientOperation, runner.op_id_for("dispatch", "0a1b2c3e"))
        assert row.status == "conflict"  # existing review list reads this
    rep = await runner.run_once(world, reader, make_cfg())  # not resubmitted
    assert rep.counts["already_conflict"] == 1 and await count(world, BorrowTransaction) == 1


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
