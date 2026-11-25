"""Synthetic workbooks only -- never real hospital data."""
from datetime import datetime

from openpyxl import Workbook, load_workbook

from app.scripts import prepare_legacy_history as prep
from app.services.import_adapters.legacy_history import issue, receive

I_HEAD = list(issue._HEADER_GOVERNED_HEADERS)
I_LINE = list(issue._LINE_GOVERNED_HEADERS)
R_HEAD = list(receive._HEADER_GOVERNED_HEADERS)
R_LINE = list(receive._LINE_GOVERNED_HEADERS)


def _row(headers, **kw):
    return [kw.get(h) for h in headers]


def _build(path):
    wb = Workbook()
    wb.remove(wb.active)
    for i in range(30):
        wb.create_sheet(f"extra{i}").append(["x"])
    spec = [
        (issue.HEADER_SHEET_NAME, I_HEAD, "เลขที่ใบยืม", issue.LINE_SHEET_NAME, I_LINE, "เลขที่ใบส่ง", "I"),
        (receive.HEADER_SHEET_NAME, R_HEAD, "เลขที่ใบคืน", receive.LINE_SHEET_NAME, R_LINE, "เลขที่ใบรับเครื่อง", "R"),
    ]
    for hs, hh, hd, ls, lh, ld, p in spec:
        h, l = wb.create_sheet(hs), wb.create_sheet(ls)
        h.append(hh)
        l.append(lh)
        l.append(_row(lh, **{"ลำดับ": "1", "วันที่": datetime(2026, 11, 24), ld: f"{p}1"}))
        l.append(_row(lh, **{"ลำดับ": "2", "วันที่": "24/Nov/2026", ld: f"{p}2"}))
        l.append(_row(lh, **{"ลำดับ": "3", "วันที่": "24/11/2569", ld: f"{p}3"}))  # BE
        l.append(_row(lh, **{"ลำดับ": "4", "วันที่": "2026-01-01", ld: f"{p}OLD"}))
        l.append(_row(lh, **{"ลำดับ": "5", "วันที่": "garbage", ld: f"{p}BAD"}))
        l.append([None] * len(lh))
        for ref in (f"{p}1", f"{p}2", f"{p}3", f"{p}OLD", f"{p}NOLINE"):
            h.append(_row(hh, **{"วันที่": datetime(2026, 11, 24), hd: ref}))
    wb.save(path)


def _run(tmp_path, *extra):
    src, out = tmp_path / "in.xlsx", tmp_path / "out.xlsx"
    _build(src)
    rc = prep.main(["--input", str(src), "--output", str(out), "--since", "2026-05-25", *extra])
    return rc, out


def test_filters_rows_and_validates(tmp_path, capsys):
    rc, out = _run(tmp_path)
    assert rc == 0
    wb = load_workbook(out)
    assert len(wb.sheetnames) == 4
    assert set(wb.sheetnames) == {issue.HEADER_SHEET_NAME, issue.LINE_SHEET_NAME,
                                  receive.HEADER_SHEET_NAME, receive.LINE_SHEET_NAME}
    for name in (issue.LINE_SHEET_NAME, receive.LINE_SHEET_NAME):
        assert wb[name].max_row == 4  # header + 3 kept
    for name, col in ((issue.HEADER_SHEET_NAME, I_HEAD.index("เลขที่ใบยืม")),
                      (receive.HEADER_SHEET_NAME, R_HEAD.index("เลขที่ใบคืน"))):
        refs = {r[col] for r in wb[name].iter_rows(min_row=2, values_only=True)}
        assert len(refs) == 3
        assert not any("OLD" in x or "NOLINE" in x for x in refs)
    content = out.read_bytes()
    assert len(issue.parse_workbook(content)[1]) == 3
    assert len(receive.parse_workbook(content)[1]) == 3
    printed = capsys.readouterr().out
    assert "unparseable_date=1" in printed and "I1" not in printed


def test_until_excludes_later_rows(tmp_path):
    rc, out = _run(tmp_path, "--until", "2026-11-23")
    assert rc == 0
    assert load_workbook(out)[issue.LINE_SHEET_NAME].max_row == 1


def test_missing_sheet_fails(tmp_path):
    src = tmp_path / "in.xlsx"
    wb = Workbook()
    wb.active.title = "other"
    wb.save(src)
    rc = prep.main(["--input", str(src), "--output", str(tmp_path / "o.xlsx"), "--since", "2026-05-25"])
    assert rc == 1
