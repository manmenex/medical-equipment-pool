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
        for w in r.ward_ids:
            out[maps[w].ward_name] = r.treatment
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
    got = _slots(["ORTHO", "OR 2", "ERX", "OBGYN", "Ward 10A", "Ward 1", "ICU 1", "ICU2 CCU", "Eye Clinic"])
    assert got["ORTHO"] == "อื่น ๆ"
    assert got["ERX"] == "อื่น ๆ" and got["OBGYN"] == "อื่น ๆ"
    assert got["OR 2"] == "Clinical Care"
    assert got["Eye Clinic"] == "OPD"
    assert got["Ward 10A"] == "IPD ตึก A"
    assert got["Ward 1"] == "อื่น ๆ"
    assert got["ICU 1"] == "Clinical Care"
    assert got["ICU2 CCU"] == "Clinical Care"


def test_orthopedic_unit_alias_goes_to_surgery_ortho():
    """Owner-confirmed alias: Orthopedic Unit is counted in the "Surgery +Ortho" row."""
    maps = {}
    wid = uuid.uuid4()
    maps[wid] = drs.WardMapping(wid, "Orthopedic Unit", None, "Orthopedic Unit", "", "", 0, False)
    rows = [r for r in drs.build_ward_rows(maps, set(maps)) if r.ward_id == wid]
    assert len(rows) == 1
    assert rows[0].label == "Surgery +Ortho"
    assert rows[0].treatment == "OPD"
    all_rows = drs.build_ward_rows(maps, set(maps))
    labels = [r.label for r in all_rows]
    # The ward fills the Surgery +Ortho slot (no empty placeholder left for it),
    # right after Pre Surgery, and is not in "อื่น ๆ".
    assert "Surgery +Ortho" not in [r.label for r in all_rows if r.ward_id is None]
    assert labels[labels.index("Pre Surgery") + 1] == rows[0].label


_ALIASED = {
    "Ward 5A": "Ward 5", "Ward 6A": "Ward 6", "Ward 7A": "Ward 7", "Ward 8A": "Ward 8",
    "Ward 9A": "Ward 9", "Ward 10A": "Ward 10", "Ward 11A": "Ward 11", "Ward 4B": "W4B",
    "Ward 5B": "W5B", "Ward 6 B": "W6B", "Recovery Room": "RR", "Emergency/Trauma Center": "ER",
    "Obstetrics and Gynecology Clinic": "OB", "X-RAY Department": "X-Ray",
    "Skin & Aesthetic Clinic": "Skin", "Eye Center": "Eye", "Wellness Center": "Wellness",
    "Neurology": "Neuro", "Labor and Delivery Room": "LR", "Orthopedic Unit": "Surgery +Ortho",
}


def _maps(names):
    maps = {}
    for n in names:
        wid = uuid.uuid4()
        maps[wid] = drs.WardMapping(wid, n, None, n, "", "", 0, False)
    return maps


def test_hospital_names_land_in_legacy_slot_with_slot_label():
    maps = _maps(list(_ALIASED))
    rows = drs.build_ward_rows(maps, set(maps))
    by_ward = {w: r for r in rows for w in r.ward_ids}
    for wid, m in maps.items():
        assert by_ward[wid].label == _ALIASED[m.ward_name], m.ward_name
        assert by_ward[wid].treatment != "อื่น ๆ"
    assert not [r for r in rows if r.treatment == "อื่น ๆ"]


def test_stale_admin_label_does_not_override_alias():
    maps = _maps(["Ward 5B", "Orthopedic Unit"])
    for m in maps.values():
        object.__setattr__(m, "report_row_label", "Ward 5" if m.ward_name == "Ward 5B" else "OR")
    rows = drs.build_ward_rows(maps, set(maps))
    got = {maps[r.ward_id].ward_name: r.label for r in rows if r.ward_id}
    assert got == {"Ward 5B": "W5B", "Orthopedic Unit": "Surgery +Ortho"}


def test_admin_label_never_merges_different_wards():
    maps = _maps(["Alpha Unit", "Beta Unit"])
    for m in maps.values():
        object.__setattr__(m, "report_row_label", "Ward 7")
    rows = [r for r in drs.build_ward_rows(maps, set(maps)) if r.ward_ids]
    assert len(rows) == 2 and {r.ward_ids for r in rows} == {(w,) for w in maps}


def test_gastroenterology_sums_into_clinic_row():
    maps = _maps(["Gastroenterology", "Gastroenterology Clinic"])
    rows = drs.build_ward_rows(maps, set(maps))
    g = [r for r in rows if r.label == "Gastroenterology Clinic"]
    assert len(g) == 1 and set(g[0].ward_ids) == set(maps)
    assert not [r for r in rows if r.treatment == "อื่น ๆ"]
