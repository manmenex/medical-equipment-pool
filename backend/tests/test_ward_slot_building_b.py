"""Ward -> layout slot matching: building B wards are never captured by the
building A "Ward N" slots (daily Excel and Standby share build_ward_rows)."""

import uuid

from app.services import daily_report_service as drs


def _slots(names):
    maps = {}
    for n in names:
        wid = uuid.uuid4()
        maps[wid] = drs.WardMapping(wid, n, None, n, "", "", 0, False)
    out = {}
    for r in drs.build_ward_rows(maps, set(maps)):
        if r.ward_id is not None:
            out[maps[r.ward_id].ward_name] = r.treatment
    return out


def test_building_b_wards_not_in_building_a():
    got = _slots(["Ward 5A", "Ward 5B", "Ward 6 B", "Ward6B", "W6B", "Ward 7", "Ward 70", "Ward 4B", "Ward 12B"])
    assert got["Ward 5A"] == "IPD ตึก A"
    assert got["Ward 5B"] == "IPD ตึก B"
    assert got["Ward 6 B"] == "IPD ตึก B"
    assert got["Ward6B"] == "IPD ตึก B"
    assert got["W6B"] == "IPD ตึก B"
    assert got["Ward 7"] == "IPD ตึก A"
    assert got["Ward 4B"] == "IPD ตึก B"
    assert got["Ward 70"] != "IPD ตึก A"
    assert got["Ward 12B"] == "อื่น ๆ"


def test_prefix_needs_word_boundary():
    got = _slots(["Orthopedic Unit", "OR 2", "ERX", "OBGYN", "Ward 10A", "Ward 1", "ICU 1", "ICU2 CCU", "Eye Clinic"])
    assert got["Orthopedic Unit"] == "อื่น ๆ"
    assert got["ERX"] == "อื่น ๆ" and got["OBGYN"] == "อื่น ๆ"
    assert got["OR 2"] == "Clinical Care"
    assert got["Eye Clinic"] == "OPD"
    assert got["Ward 10A"] == "IPD ตึก A"
    assert got["Ward 1"] == "อื่น ๆ"
    assert got["ICU 1"] == "Clinical Care"
    assert got["ICU2 CCU"] == "Clinical Care"
