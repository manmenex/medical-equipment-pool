"""Pool-table category->row mapping and standby pneumatic/infusion selection,
using the exact host category names."""
import io

import pytest
from openpyxl import load_workbook

from app.models.equipment import EquipmentStatus
from app.models.master_data import EquipmentCategory
from app.models.user import ROLE_EQUIPMENT_POOL_STAFF
from app.services import daily_report_service as svc
from tests import test_pr30_daily_report as p30
from tests import test_pr34_standby as p34
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio

HOST = {
    "ALARMS, OCCUPANCY, BED": "bed",
    "CRYOTHERAPY SYSTEMS": "cryo",
    "INFUSION PUMPS": "infusion",
    "INFUSION PUMPS, ANALGESIC, PATIENT-CONTROLLED": "pca",
    "INFUSION PUMPS, SYRINGE": "syringe",
    "MATTRESS SYSTEMS, ALTERNATING-PRESSURE": "mattress",
    "PNEUMATIC PUMP": "pneumatic",
    "RESPIRATORS, AIR-PURIFYING, PARTICULATE": "respirator",
}


async def test_host_category_names_map_to_explicit_roles():
    for name, role in HOST.items():
        assert svc.category_role(name) == role, name
        assert svc.category_role(f"  {name.lower()} ") == role


async def test_pool_table_counts_every_row(client, seeded_users, db_session):
    w = await p30._world(db_session, seeded_users)
    for i, name in enumerate(HOST):
        cat = EquipmentCategory(name=name)
        db_session.add(cat)
        await db_session.flush()
        await p30._tx(db_session, w, ward=w.w5a, category=cat, dispatched=p30.at(28, 10 + i), op_d=w.bme_b)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await p30._get_xlsx(client, staff, date="2026-07-28")
    assert resp.status_code == 200, resp.text
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb["รายงาน"]
    labels = {"INFUSION PUMP", "PCA", "INFUSION PUMP, SYRINGE", "MATTRESS SYSTEM,ALTERNATING-PRESSURE",
              "CRYO CUFF", "BED EXIT ALRM", "PNEUMATIC PUMP", "RESPIRATORS, AIR-PURIFYING, PARTICULATE"}
    rows = {}
    for r in range(1, ws.max_row + 1):
        label = ws.cell(r, 2).value
        if isinstance(label, str) and any(label.startswith(x) for x in labels):
            rows[label] = ws.cell(r, 8).value  # total dispatched
    assert len(rows) == 8 and all(v == 1 for v in rows.values()), rows
    # Category sheet uses the same mapping: PCA/Syringe are not folded into Infusion Pump.
    cat = {r[0].value: r[5].value for r in wb["ชนิดเครื่อง"].iter_rows(min_row=5, max_row=12)}
    assert cat["Infusion Pump"] == 1 and cat["PCA"] == 1 and cat["Syringe Pump"] == 1
    assert cat["Pneumatic Pump"] == 1 and cat["Respirator"] == 1


async def test_standby_uses_exact_categories(client, seeded_users, db_session):
    w = await p34._world(db_session)
    pn = EquipmentCategory(name="PNEUMATIC PUMP")
    inf = EquipmentCategory(name="INFUSION PUMPS")
    pca = EquipmentCategory(name="INFUSION PUMPS, ANALGESIC, PATIENT-CONTROLLED")
    syr = EquipmentCategory(name="INFUSION PUMPS, SYRINGE")
    db_session.add_all([pn, inf, pca, syr])
    await db_session.flush()
    ISS = EquipmentStatus.ISSUED_TO_WARD
    for cat in (inf, pca, syr):
        e = await p34._eq(db_session, w, cat, ISS)
        await p34._tx(db_session, w, e, w.w5a, p34.at(27, 23))
    p1 = await p34._eq(db_session, w, pn, ISS)
    p2 = await p34._eq(db_session, w, pn, ISS)
    await p34._tx(db_session, w, p1, w.w5a, p34.at(27, 23))
    await p34._tx(db_session, w, p2, w.w5a, p34.at(27, 10), p34.at(28, 3))
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    body = (await p34._get(client, staff, "night")).json()
    assert "PNEUMATIC PUMP" in body["pneumatic"]["categories"]
    assert body["pneumatic"]["in_use"]["system_value"] == 1
    assert body["pneumatic"]["returned"]["system_value"] == 1
    assert "INFUSION PUMPS" in body["infusion"]["categories"] and not any("SYRINGE" in c or "ANALGESIC" in c for c in body["infusion"]["categories"])


def _pool_rows(ws):
    """(label, row) of the pool table lines plus the row of its total line."""
    start = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 2).value == "ชนิดเครื่องมือ Equipment Pool")
    labels, r = [], start + 2
    while isinstance(ws.cell(r, 1).value, int):
        labels.append(ws.cell(r, 2).value)
        r += 1
    return labels, r, ws


async def test_respirator_row_only_with_activity(client, seeded_users, db_session):
    w = await p30._world(db_session, seeded_users)
    cat = EquipmentCategory(name="INFUSION PUMPS")
    db_session.add(cat)
    await db_session.flush()
    await p30._tx(db_session, w, ward=w.w5a, category=cat, dispatched=p30.at(28, 10), op_d=w.bme_b)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await p30._get_xlsx(client, staff, date="2026-07-28")
    ws = load_workbook(io.BytesIO(resp.content))["รายงาน"]
    labels, total_row, _ = _pool_rows(ws)
    assert len(labels) == 7 and not any(x.startswith("RESPIRATORS") for x in labels)
    assert ws.cell(total_row, 8).value == 1  # total line directly follows the 7 rows

    rcat = EquipmentCategory(name="RESPIRATORS, AIR-PURIFYING, PARTICULATE")
    db_session.add(rcat)
    await db_session.flush()
    await p30._tx(db_session, w, ward=w.w5a, category=rcat, dispatched=p30.at(28, 11), op_d=w.bme_b)
    await db_session.commit()
    resp = await p30._get_xlsx(client, staff, date="2026-07-28")
    ws = load_workbook(io.BytesIO(resp.content))["รายงาน"]
    labels, total_row, _ = _pool_rows(ws)
    assert len(labels) == 8 and labels[-1].startswith("RESPIRATORS")
    assert ws.cell(total_row, 8).value == 2
