"""One-time master-data loader (scripts/load_master_data.py)."""
import re
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.audit import AuditLog
from app.models.master_data import Department, EquipmentCategory, Ward
from scripts import load_master_data as lmd

WARD_HDR = "ward_name,nsmart_department,phone\n"


@pytest.fixture
def session_maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(autouse=True)
def patched_session_local(monkeypatch, session_maker):
    monkeypatch.setattr(lmd, "AsyncSessionLocal", session_maker)


def _write(tmp_path, name, text, bom=False):
    p = tmp_path / name
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return p


WARDS = (
    WARD_HDR
    + '"ICU 2",ICU 2,02-1234\n'
    + '"ICU 2 (CCU)",ICU 2,02-1234\n'
    + '"Ward 6 B",Ward 6,\n'
    + '"คลินิกท่าแพ",,053-111\n'
)
CATS = 'category_name\n"INFUSION PUMPS, SYRINGE"\nVENTILATOR\n'


async def _load(tmp_path, wards=WARDS, cats=CATS, **kw):
    out = []
    code = await lmd.run(
        _write(tmp_path, "w.csv", wards, bom=True), _write(tmp_path, "c.csv", cats, bom=True),
        out=out.append, apply=kw.get("apply", False), overwrite_phones=kw.get("overwrite_phones", False),
    )
    return code, "\n".join(out)


async def _counts(session_maker):
    async with session_maker() as db:
        return tuple(
            [len((await db.execute(select(m))).scalars().all()) for m in (Department, Ward, EquipmentCategory, AuditLog)]
        )


async def test_dry_run_writes_nothing(tmp_path, session_maker):
    code, out = await _load(tmp_path)
    assert code == 0 and "DRY RUN" in out and "CREATE" in out
    assert await _counts(session_maker) == (0, 0, 0, 0)


async def test_apply_creates_everything_with_one_audit(tmp_path, session_maker):
    code, _ = await _load(tmp_path, apply=True)
    assert code == 0
    async with session_maker() as db:
        depts = {d.name: d for d in (await db.execute(select(Department))).scalars()}
        wards = {w.name: w for w in (await db.execute(select(Ward))).scalars()}
        cats = {c.name for c in (await db.execute(select(EquipmentCategory))).scalars()}
        audits = (await db.execute(select(AuditLog))).scalars().all()
    assert set(depts) == {"ICU 2", "Ward 6"}  # shared department created once
    assert depts["ICU 2"].phone == "02-1234" and depts["Ward 6"].phone is None
    assert wards["ICU 2"].department_id == wards["ICU 2 (CCU)"].department_id == depts["ICU 2"].id
    assert wards["คลินิกท่าแพ"].department_id is None and wards["คลินิกท่าแพ"].phone == "053-111"
    assert "INFUSION PUMPS, SYRINGE" in cats and len(cats) == 2
    assert len(audits) == 1 and audits[0].action == "import" and audits[0].user_id is None


async def test_codes_deterministic_unique_and_short(tmp_path, session_maker):
    await _load(tmp_path, apply=True)
    async with session_maker() as db:
        w = {x.name: x.code for x in (await db.execute(select(Ward))).scalars()}
        d = {x.name: x.code for x in (await db.execute(select(Department))).scalars()}
    assert d == {"ICU 2": "D001", "Ward 6": "D002"}
    assert w == {"ICU 2": "W001", "ICU 2 (CCU)": "W002", "Ward 6 B": "W003", "คลินิกท่าแพ": "W004"}
    assert all(len(c) <= 20 for c in [*w.values(), *d.values()])


async def test_rerun_is_idempotent_and_keeps_codes(tmp_path, session_maker):
    await _load(tmp_path, apply=True)
    before = await _counts(session_maker)
    code, out = await _load(tmp_path, apply=True)
    assert code == 0 and "CREATE" not in out and "EXISTS" in out
    assert await _counts(session_maker) == before  # no writes, no extra audit entry
    # a new ward appended later gets the next number; existing ones keep theirs
    await _load(tmp_path, wards=WARDS + "Ward 9,,\n", apply=True)
    async with session_maker() as db:
        w = {x.name: x.code for x in (await db.execute(select(Ward))).scalars()}
    assert w["Ward 9"] == "W005" and w["ICU 2"] == "W001"


async def test_existing_codes_respected_and_phone_rules(tmp_path, session_maker):
    async with session_maker() as db:
        db.add(Ward(code="W010", name="Ward 6 B", phone="099-000"))
        db.add(Ward(code="LEGACY", name="ICU 2", phone=None))
        await db.commit()
    wards = WARD_HDR + "Ward 6 B,,02-5555\nICU 2,,02-1234\nNew One,,\n"
    code, out = await _load(tmp_path, wards=wards, cats=CATS, apply=True)
    assert code == 0 and "use --overwrite-phones" in out
    async with session_maker() as db:
        w = {x.name: x for x in (await db.execute(select(Ward))).scalars()}
    assert w["Ward 6 B"].phone == "099-000" and w["Ward 6 B"].code == "W010"  # kept
    assert w["ICU 2"].phone == "02-1234" and w["ICU 2"].code == "LEGACY"  # filled
    assert w["New One"].code == "W011"
    await _load(tmp_path, wards=wards, apply=True, overwrite_phones=True)
    async with session_maker() as db:
        assert (await db.execute(select(Ward.phone).where(Ward.name == "Ward 6 B"))).scalar_one() == "02-5555"


async def test_department_phone_conflict_reported_and_skipped(tmp_path, session_maker):
    wards = WARD_HDR + "A1,Dept A,02-111\nA2,Dept A,02-222\nB1,Dept B,\n"
    code, out = await _load(tmp_path, wards=wards, apply=True)
    assert code == 0 and "phone conflict" in out
    async with session_maker() as db:
        d = {x.name: x.phone for x in (await db.execute(select(Department))).scalars()}
        w = {x.name: x.phone for x in (await db.execute(select(Ward))).scalars()}
    assert d["Dept A"] is None
    assert w["A1"] == "02-111" and w["A2"] == "02-222"


@pytest.mark.parametrize(
    "wards,cats,needle",
    [
        (WARD_HDR + "X,,\nX,,\n", CATS, "duplicate ward_name"),
        (WARDS, "category_name\nA\nA\n", "duplicate category_name"),
        (WARD_HDR + "X,,abc\n", CATS, "phone"),
        (WARD_HDR + "X,,١٢٣-٤٥٦\n", CATS, "phone"),  # non-ASCII digits rejected
        (WARD_HDR + ("N" * 151) + ",,\n", CATS, "longer than 150"),
        ("name,dept,phone\nX,,\n", CATS, "header must be exactly"),
    ],
)
async def test_invalid_input_rejected_before_any_write(tmp_path, session_maker, wards, cats, needle):
    code, out = await _load(tmp_path, wards=wards, cats=cats, apply=True)
    assert code == 2 and needle in out
    assert await _counts(session_maker) == (0, 0, 0, 0)


def test_wrapper_script_is_dry_run_by_default_and_mounts_read_only():
    text = (Path(__file__).resolve().parents[2] / "deployment/local-staging/load-master-data.ps1").read_text()
    code = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    assert "[switch]$Apply" in code and "[switch]$OverwritePhones" in code
    assert "$toolArgs += '--apply'" in code and re.search(r"if \(\$Apply\) \{ \$toolArgs", code)
    assert ":/mep-input/wards.csv:ro" in code and ":/mep-input/categories.csv:ro" in code
    assert "Invoke-Expression" not in code
