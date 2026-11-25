"""Host-side helper: trim the Owner's full Google Sheet export down to the
four canonical legacy-history sheets, limited to a date range, so the
result passes the "นำเข้าข้อมูลเดิม" upload guards.

    python -m app.scripts.prepare_legacy_history \
        --input in.xlsx --output out.xlsx --since 2026-05-25 [--until 2026-11-25]

Needs no database. Reads cached cell values only. Prints COUNTS only --
never any cell value (the workbook is real hospital data).

Only columns in each sheet's governed header schema are written; every other
column (e.g. a patient HN column) is dropped without being read into the
output. Dropped column NAMES (not values) and counts are printed.
"""
from __future__ import annotations

import argparse
import io
import os
import re
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


_DOC_KEY = re.compile(r"([A-Za-z]+)1(0*)(\d+)")


def _doc_key(doc: str) -> tuple[str, int] | None:
    """Padding-insensitive key: (alpha prefix, number after the leading 1 and zero padding)."""
    m = _DOC_KEY.fullmatch(doc)
    return (m.group(1), int(m.group(3))) if m else None


def _reconcile(h_rows: list[tuple], hi: int, docs: set[str]) -> tuple[list[tuple], int]:
    """Keep header rows whose doc is referenced by a kept line. A header with no exact
    match is rewritten to the line's doc string only when its normalized key matches
    exactly one kept line doc (without an exact header) and no other header doc shares
    the key; any ambiguity drops it as before."""
    def ref(r: tuple) -> str:
        return _doc(r[hi] if hi < len(r) else None)

    header_docs = {ref(r) for r in h_rows}
    line_keys: dict[tuple[str, int], list[str]] = {}
    for d in docs:
        k = _doc_key(d)
        if k is not None:
            line_keys.setdefault(k, []).append(d)
    header_keys: dict[tuple[str, int], set[str]] = {}
    for d in header_docs:
        k = _doc_key(d)
        if k is not None:
            header_keys.setdefault(k, set()).add(d)
    out, n = [], 0
    for r in h_rows:
        d = ref(r)
        if d in docs:
            out.append(r)
            continue
        k = _doc_key(d)
        cands = line_keys.get(k, []) if k is not None else []
        if len(cands) == 1 and len(header_keys[k]) == 1 and cands[0] not in header_docs:
            row = list(r)
            row[hi] = cands[0]
            out.append(tuple(row))
            n += 1
    return out, n


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


def _governed(sheet_name: str) -> tuple[str, ...]:
    for mod in (issue, receive):
        try:
            return mod.governed_columns(sheet_name)
        except KeyError:
            continue
    raise KeyError(sheet_name)


def _keep_indices(header: tuple, sheet_name: str, dropped: dict) -> list[int]:
    governed = set(_governed(sheet_name))
    keep, names, unnamed = [], [], 0
    for i, h in enumerate(header):
        if isinstance(h, str) and h.strip() in governed:
            keep.append(i)
        elif isinstance(h, str) and h.strip():
            names.append(h.strip())
        elif h is not None:
            names.append(f"<non-text header #{i + 1}>")
        else:
            unnamed += 1
    dropped[sheet_name] = (names, unnamed)
    return keep


def prepare(src, since: date, until: date | None, out: Workbook, stats: dict, dropped: dict,
            reconciled: dict | None = None) -> None:
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
        h_kept, n_rec = _reconcile(h_rows, hi, docs)
        if reconciled is not None:
            reconciled[hs] = n_rec
        stats[hs] = (len(h_kept), len(h_rows) - len(h_kept), 0)

        for name, header, rows in ((hs, h_header, h_kept), (ls, l_header, kept)):
            keep = _keep_indices(header, name, dropped)
            ws = out.create_sheet(name)
            ws.append([header[i] for i in keep])
            for r in rows:
                ws.append([r[i] if i < len(r) else None for i in keep])


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
    tmp = a.output.with_name(a.output.name + ".tmp")
    try:
        src = load_workbook(a.input, read_only=True, data_only=True)
        out = Workbook()
        out.remove(out.active)
        stats: dict = {}
        dropped: dict = {}
        reconciled: dict = {}
        try:
            prepare(src, a.since, a.until, out, stats, dropped, reconciled)
        finally:
            src.close()
        buf = io.BytesIO()
        out.save(buf)
        content = buf.getvalue()
        tmp.write_bytes(content)
        i_h, i_l = issue.parse_workbook(content)
        r_h, r_l = receive.parse_workbook(content)
        os.replace(tmp, a.output)  # only after validation succeeded
    except Exception as exc:  # message only; must not echo cell data
        tmp.unlink(missing_ok=True)
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for name, (kept, n_dropped, unparse) in stats.items():
        print(f"sheet[{name}] kept={kept} dropped={n_dropped} unparseable_date={unparse}")
    for name, n in reconciled.items():
        print(f"sheet[{name}] doc_reconciled={n}")
    for name, (names, unnamed) in dropped.items():
        print(f"sheet[{name}] dropped_columns={len(names) + unnamed} names={names} unnamed={unnamed}")
    print(
        f"validated issue_headers={len(i_h)} issue_lines={len(i_l)} "
        f"receive_headers={len(r_h)} receive_lines={len(r_l)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
