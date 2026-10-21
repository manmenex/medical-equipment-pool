"""Pool equipment loader (scripts/load_equipment.py). SYNTHETIC workbooks only."""
import zipfile

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.audit import AuditLog
from app.models.equipment import Equipment, EquipmentStatus
from app.models.master_data import EquipmentCategory
from scripts import load_equipment as le

HEADER = ["ลำดับ", "อนุญาต", "ยังไม่ส่งคืน", "Item No.", "ID CODE", "Asset ID", "ชื่อเครื่องมือ", "ยี่ห้อ", "รุ่น",
          "S/N", "สถานที่ตั้ง(อาคาร/ชั้น/ห้อง)", None, None, "Receive date", "Register date", "Purchase year",
          "Asset status"]


def row(bcm, item, name="Syringe Pump", status="Active", asset="FA-1", brand="Acme", model="M1", sn="-", nr=None):
    r = [None] * len(HEADER)
    r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[16] = nr, item, bcm, asset, name, brand, model, sn, status
    return r


def make_book(path, rows, header=HEADER, summary_rows=1, template=False):
    wb = Workbook()
    ws = wb.active
    for _ in range(summary_rows):
        ws.append(["รวมจำนวนรายการ : %d รายการ" % len(rows)])
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)
    if template:  # mimic Excel template content type
        tmp = path.with_suffix(".tmp")
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == "[Content_Types].xml":
                    data = data.replace(b"sheet.main+xml", b"template.main+xml")
                zout.writestr(info, data)
        tmp.replace(path)
    return path


ROWS = [
    row("BCM90001", "0001", sn="SN-A", nr="ยังไม่ส่งคืน"),
    row("bcm90002", "0002", status="Defective"),
    row("BCM90003", "0003", status="Decommission"),
    row("BCM90004", "0004", status="wait decom", name="ventilator "),
]


@pytest.fixture
def session_maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(autouse=True)
def patched_session_local(monkeypatch, session_maker):
    monkeypatch.setattr(le, "AsyncSessionLocal", session_maker)


@pytest.fixture(autouse=True)
async def categories(session_maker):
    async with session_maker() as db:
        db.add_all([EquipmentCategory(name="Syringe Pump"), EquipmentCategory(name="VENTILATOR")])
        await db.commit()


async def _load(path, **kw):
    out = []
    code = await le.run(path, apply=kw.get("apply", False), update_existing=kw.get("update_existing", False), out=out.append)
    return code, "\n".join(out)


async def _equipment(session_maker):
    async with session_maker() as db:
        return {e.bcm_code: e for e in (await db.execute(select(Equipment))).scalars()}


async def _audits(session_maker):
    async with session_maker() as db:
        return (await db.execute(select(AuditLog))).scalars().all()


async def test_header_detection_with_extra_summary_rows(tmp_path):
    p = make_book(tmp_path / "pool.xlsx", ROWS, summary_rows=3)
    code, out = await _load(p)
    assert code == 0 and "create=4" in out


async def test_missing_required_header_fails_clearly(tmp_path):
    hdr = [h for h in HEADER if h != "Asset status"]
    p = make_book(tmp_path / "pool.xlsx", [], header=hdr)
    code, out = await _load(p)
    assert code == 2 and "Asset status" in out and "header row not found" in out


async def test_dry_run_writes_nothing(tmp_path, session_maker):
    code, out = await _load(make_book(tmp_path / "pool.xlsx", ROWS))
    assert code == 0 and "DRY RUN" in out and "CREATE" in out
    assert await _equipment(session_maker) == {} and await _audits(session_maker) == []


async def test_apply_maps_fields_status_and_one_audit(tmp_path, session_maker):
    code, out = await _load(make_book(tmp_path / "pool.xlsx", ROWS), apply=True)
    assert code == 0 and "APPLIED" in out
    eq = await _equipment(session_maker)
    assert set(eq) == {"BCM90001", "BCM90002", "BCM90003", "BCM90004"}
    a = eq["BCM90001"]
    assert a.item_no == "0001" and a.asset_id == "FA-1" and a.asset_number is None
    assert a.status == EquipmentStatus.AVAILABLE_AT_POOL and a.raw_source_status == "Active"
    assert a.serial_number == "SN-A" and a.brand == "Acme" and a.model == "M1"
    assert eq["BCM90002"].serial_number is None  # '-' -> None
    assert eq["BCM90002"].status == EquipmentStatus.UNAVAILABLE_DEFECTIVE
    assert eq["BCM90003"].status == EquipmentStatus.DECOMMISSIONED
    assert eq["BCM90004"].status == EquipmentStatus.DECOMMISSIONED
    assert eq["BCM90004"].equipment_name == "VENTILATOR"  # category match is case/space-insensitive
    audits = await _audits(session_maker)
    assert len(audits) == 1 and audits[0].action == "import" and audits[0].user_id is None


async def test_not_returned_counted_but_status_unaffected(tmp_path, session_maker):
    code, out = await _load(make_book(tmp_path / "pool.xlsx", ROWS), apply=True)
    assert "(not returned): 1" in out and "WARNING" in out
    assert (await _equipment(session_maker))["BCM90001"].status == EquipmentStatus.AVAILABLE_AT_POOL


async def test_unknown_category_and_status_are_errors_and_nothing_written(tmp_path, session_maker):
    rows = [row("BCM90001", "1"), row("BCM90002", "2", name="Nope"), row("BCM90003", "3", status="Lost")]
    code, out = await _load(make_book(tmp_path / "pool.xlsx", rows), apply=True)
    assert code == 2 and "no existing category" in out and "unknown Asset status" in out
    assert await _equipment(session_maker) == {}


async def test_duplicates_in_file(tmp_path, session_maker):
    rows = [row("BCM90001", "1"), row("BCM90001", "2"), row("BCM90003", "1")]
    code, out = await _load(make_book(tmp_path / "pool.xlsx", rows), apply=True)
    assert code == 2 and "duplicate BCM" in out and "duplicate Item No" in out
    assert await _equipment(session_maker) == {}


async def test_item_no_conflict_with_db(tmp_path, session_maker):
    await _load(make_book(tmp_path / "a.xlsx", [row("BCM90001", "0001")]), apply=True)
    code, out = await _load(make_book(tmp_path / "b.xlsx", [row("BCM90009", "0001")]), apply=True)
    assert code == 2 and "already used by BCM90001" in out
    assert set(await _equipment(session_maker)) == {"BCM90001"}


async def test_leading_zero_item_no_kept_as_text(tmp_path, session_maker):
    await _load(make_book(tmp_path / "a.xlsx", [row("BCM90001", "000123")]), apply=True)
    assert (await _equipment(session_maker))["BCM90001"].item_no == "000123"


async def test_rerun_is_idempotent(tmp_path, session_maker):
    p = make_book(tmp_path / "pool.xlsx", ROWS)
    await _load(p, apply=True)
    code, out = await _load(p, apply=True)
    assert code == 0 and "create=0" in out and "unchanged=4" in out
    assert len(await _audits(session_maker)) == 1  # no extra audit on a no-op


async def test_update_existing_flag(tmp_path, session_maker):
    await _load(make_book(tmp_path / "a.xlsx", ROWS), apply=True)
    changed = [row("BCM90001", "0001", brand="NewBrand", sn="SN-B"), row("BCM90002", "0002", status="Active")]
    p = make_book(tmp_path / "b.xlsx", changed)
    code, out = await _load(p, apply=True)  # default: skip
    assert code == 0 and "skip=1" in out
    assert (await _equipment(session_maker))["BCM90001"].brand == "Acme"
    assert "differs in" in out and "SKIP" in out
    code, out = await _load(p, apply=True, update_existing=True)
    assert code == 0 and "update=1" in out
    eq = await _equipment(session_maker)
    assert eq["BCM90001"].brand == "NewBrand" and eq["BCM90001"].serial_number == "SN-B"
    # status of an existing row is never changed by the loader
    assert eq["BCM90002"].status == EquipmentStatus.UNAVAILABLE_DEFECTIVE
    assert len(await _audits(session_maker)) == 2


async def test_xltx_template_is_readable(tmp_path):
    p = make_book(tmp_path / "pool.xltx", ROWS, template=True)
    code, out = await _load(p)
    assert code == 0 and "create=4" in out


async def test_unsupported_extension(tmp_path):
    p = tmp_path / "pool.csv"
    p.write_text("x")
    code, out = await _load(p)
    assert code == 2 and "unsupported file type" in out


async def test_numeric_item_no_cells_warn_and_load(tmp_path, session_maker):
    rows = [row("BCM90001", 123), row("BCM90002", 123456.0), row("BCM90003", "0007")]
    code, out = await _load(make_book(tmp_path / "pool.xlsx", rows), apply=True)
    assert code == 0 and "2 Item No cells were numbers" in out and "leading zeros may have been lost" in out
    assert "item_no=123456" in out and "item_no=0007" in out
    eq = await _equipment(session_maker)
    assert eq["BCM90001"].item_no == "123" and eq["BCM90002"].item_no == "123456"


@pytest.mark.parametrize("bad", [2**53, 10**20, 1e20, 12.5])
async def test_unsafe_numeric_item_no_is_error(tmp_path, session_maker, bad):
    code, out = await _load(make_book(tmp_path / "pool.xlsx", [row("BCM90001", bad)]), apply=True)
    assert code == 2 and "non-integer or >= 2^53" in out
    assert await _equipment(session_maker) == {}


async def test_numeric_bcm_cell_warns(tmp_path):
    code, out = await _load(make_book(tmp_path / "pool.xlsx", [row(90001, "1")]))
    assert code == 0 and "1 ID CODE cells were numbers" in out and "BCM90001" in out


@pytest.mark.parametrize("ph", ["-", "—", "N/A", "NA", "n/a", "ไม่มี", "none", "None", "  "])
async def test_serial_placeholders_are_blank(tmp_path, session_maker, ph):
    rows = [row("BCM90001", "1", sn=ph), row("BCM90002", "2", sn=ph)]  # duplicates if kept
    code, out = await _load(make_book(tmp_path / "pool.xlsx", rows), apply=True)
    assert code == 0, out
    assert all(e.serial_number is None for e in (await _equipment(session_maker)).values())


def test_powershell_wrapper_static_contract():
    """No PowerShell on CI: assert the wrapper's contract statically."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "deployment/local-staging/load-equipment.ps1").read_text(encoding="utf-8")
    assert ". (Join-Path $PSScriptRoot 'lib/Common.ps1')" in text
    for needle in ("[switch]$Apply", "[switch]$UpdateExisting", "[Parameter(Mandatory)] [string]$PoolFile",
                   "scripts/load_equipment.py", "if ($Apply) { $toolArgs += '--apply' }",
                   "if ($UpdateExisting) { $toolArgs += '--update-existing' }", ":ro"):
        assert needle in text
    assert "'--apply'" not in text.split("$toolArgs = @(")[1].split("\n")[0]  # dry-run is the default
