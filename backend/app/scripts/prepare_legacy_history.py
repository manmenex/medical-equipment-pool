"""Host-side helper: trim the Owner's full Google Sheet export down to the
four canonical legacy-history sheets, limited to a date range, so the
result passes the "นำเข้าข้อมูลเดิม" upload guards.

    python -m app.scripts.prepare_legacy_history \
        --input in.xlsx --output out.xlsx --since 2026-05-25 [--until 2026-11-25]

Needs no database. Reads cached cell values only. Prints COUNTS only --
never any cell value (the workbook is real hospital data).
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook

from app.services.import_adapters.legacy_history import issue, receive
from app.services.legacy_sheet_sync.sheet_parser import _parse_date

DATE_HEADER = "วันที่"
# (header sheet, header doc column, line sheet, line doc column)
_PAIRS = (
    (issue.HEADER_SHEET_NAME, "เลขที่ใบยืม", issue.LINE_SHEET_NAME, "เลขที่ใบส่ง"),
    (receive.HEADER_SHEET_NAME, "เลขที่ใบคืน", receive.LINE_SHEET_NAME, "เลขที่ใบรับเครื่อง"),
)


def _to_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if " " in text and ":" in text:  # drop a trailing time part
            text = text.split(" ")[0]
        try:
            return _parse_date(text)
        except (ValueError, OverflowError):
            return None
    return None


def _doc(value: object) -> str:
    return "" if value is None else str(value).strip()


def _blank(row: tuple) -> bool:
    return all(v is None or (isinstance(v, str) and not v.strip()) for v in row)


def _read(ws) -> tuple[tuple, list[tuple]]:
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    if header is None:
        raise ValueError("empty sheet")
    return header, [r for r in rows if not _blank(r)]


def _col(header: tuple, name: str) -> int:
    for i, h in enumerate(header):
        if isinstance(h, str) and h.strip() == name:
            return i
    raise ValueError("required column missing")


def prepare(src, since: date, until: date | None, out: Workbook, stats: dict) -> None:
    for hs, h_doc, ls, l_doc in _PAIRS:
        for name in (hs, ls):
            if name not in src.sheetnames:
                raise ValueError(f"missing sheet: {name}")
        l_header, l_rows = _read(src[ls])
        di, ci = _col(l_header, DATE_HEADER), _col(l_header, l_doc)
        kept, docs, unparse = [], set(), 0
        for r in l_rows:
            d = _to_date(r[di] if di < len(r) else None)
            if d is None:
                unparse += 1
            elif d >= since and (until is None or d <= until):
                kept.append(r)
                ref = _doc(r[ci] if ci < len(r) else None)
                if ref:
                    docs.add(ref)
        stats[ls] = (len(kept), len(l_rows) - len(kept) - unparse, unparse)

        h_header, h_rows = _read(src[hs])
        hi = _col(h_header, h_doc)
        h_kept = [r for r in h_rows if _doc(r[hi] if hi < len(r) else None) in docs]
        stats[hs] = (len(h_kept), len(h_rows) - len(h_kept), 0)

        for name, header, rows in ((hs, h_header, h_kept), (ls, l_header, kept)):
            ws = out.create_sheet(name)
            ws.append(list(header))
            for r in rows:
                ws.append(list(r))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--since", required=True, type=date.fromisoformat)
    p.add_argument("--until", type=date.fromisoformat, default=None)
    a = p.parse_args(argv)
    if a.until and a.until < a.since:
        print("ERROR: --until is before --since", file=sys.stderr)
        return 2
    try:
        src = load_workbook(a.input, read_only=True, data_only=True)
        out = Workbook()
        out.remove(out.active)
        stats: dict = {}
        try:
            prepare(src, a.since, a.until, out, stats)
        finally:
            src.close()
        buf = io.BytesIO()
        out.save(buf)
        content = buf.getvalue()
        a.output.write_bytes(content)
        i_h, i_l = issue.parse_workbook(content)
        r_h, r_l = receive.parse_workbook(content)
    except Exception as exc:  # message only; must not echo cell data
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for name, (kept, dropped, unparse) in stats.items():
        print(f"sheet[{name}] kept={kept} dropped={dropped} unparseable_date={unparse}")
    print(
        f"validated issue_headers={len(i_h)} issue_lines={len(i_l)} "
        f"receive_headers={len(r_h)} receive_lines={len(r_l)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
