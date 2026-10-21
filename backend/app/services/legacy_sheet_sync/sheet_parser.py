"""Parse the legacy pool sheet tabs into typed rows (pure, no I/O).

Columns are located by HEADER TEXT (prefix match after normalisation), never
by letter, because the Owner's screenshots show truncated headers. A missing
required header fails the whole read clearly (``HeaderError``).

Privacy rules (Governance 2026-10-21):
* A row containing something that looks like a patient hospital number (HN)
  is skipped, and the report never echoes the offending cell.
* Free-text notes are NOT read into the result. Only the accessory check-mark
  columns are summarised (which ones show a failure mark).
* The ward-side person column ("ชื่อ (User)") is never read.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone

from app.services.legacy_sheet_sync.config import BANGKOK, TAB_DISPATCH, TAB_RECEIPT

KIND_DISPATCH = "dispatch"
KIND_RECEIPT = "receipt"


class HeaderError(ValueError):
    """A required header is missing from a tab."""


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[\s.​]+", "", text)


# field -> normalised header prefix. Order matters only for readability.
_REQUIRED_COMMON = {
    "row_id": "ลำดับ",
    "date": "วันที่",
    "bcm": "mecode",
    "ward": "แผนก",
    "time": "เวลา",
    "bme": "ชื่อbme",
}
_DOC_PREFIX = {KIND_DISPATCH: "เลขที่ใบส่ง", KIND_RECEIPT: "เลขที่ใบรับ"}
_STOP_ACCESSORY = ("จำนวน", "หมายเหตุ", "เวลา", "ชื่อ")

_HN_PATTERNS = (
    re.compile(r"(?<![a-z])hn\s*[:.\-#]?\s*\d{3,}", re.IGNORECASE),
    re.compile(r"^\s*\d{6,}\s*$"),
)
_FAIL_MARKS = {"✗", "✘", "✕", "×", "x", "false", "no", "ไม่"}
_ROW_ID_RE = re.compile(r"^[0-9a-fA-F]{8}$")


@dataclass(frozen=True)
class Columns:
    kind: str
    index: dict[str, int]
    accessories: list[tuple[int, str]]  # (column index, header label)
    ignored_for_hn: frozenset[int]


@dataclass(frozen=True)
class LegacyRow:
    kind: str
    sheet_row: int  # 1-based, as shown in the sheet
    row_id: str
    doc_no: str
    occurred_at: datetime  # UTC
    bcm_raw: str
    ward_raw: str
    bme_name: str
    failed_accessories: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkippedRow:
    kind: str
    sheet_row: int
    row_id: str
    reason: str


@dataclass
class ParsedTab:
    kind: str
    rows: list[LegacyRow] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)


def tab_title(kind: str) -> str:
    return TAB_DISPATCH if kind == KIND_DISPATCH else TAB_RECEIPT


def detect_columns(kind: str, header: list[str]) -> Columns:
    norm = [_norm(h) for h in header]

    def find(prefix: str) -> int | None:
        prefix = _norm(prefix)  # NFKC rewrites Thai sara-am, so both sides must be normalised
        for i, h in enumerate(norm):
            if h.startswith(prefix):
                return i
        return None

    wanted = dict(_REQUIRED_COMMON)
    wanted["doc_no"] = _DOC_PREFIX[kind]
    index: dict[str, int] = {}
    missing: list[str] = []
    for name, prefix in wanted.items():
        i = find(prefix)
        if i is None:
            missing.append(name)
        else:
            index[name] = i
    if missing:
        raise HeaderError(
            f"Tab '{tab_title(kind)}': required header(s) not found: {', '.join(sorted(missing))}. "
            "The sheet layout may have changed."
        )
    scan = find("scancode")
    ignored = {index[k] for k in ("row_id", "date", "time", "doc_no")}
    if scan is not None:
        ignored.add(scan)
    # Accessory check-mark columns: the headers right after the ward column,
    # up to the first quantity/note/time/name header.
    accessories: list[tuple[int, str]] = []
    for i in range(index["ward"] + 1, len(header)):
        label = (header[i] or "").strip()
        if not label or any(norm[i].startswith(_norm(s)) for s in _STOP_ACCESSORY):
            break
        accessories.append((i, label[:40]))
        if len(accessories) == 3:
            break
    return Columns(kind, index, accessories, frozenset(ignored))


def _parse_date(text: str) -> date:
    m = re.fullmatch(r"\s*(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})\s*", text)
    if not m:
        raise ValueError("date")
    a, b, c = (int(x) for x in m.groups())
    y, mo, d = (a, b, c) if a > 31 else (c, b, a)  # yyyy-mm-dd or dd/mm/yyyy
    if y > 2400:  # Buddhist Era
        y -= 543
    return date(y, mo, d)


def _parse_time(text: str) -> time:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})(?::(\d{2}))?\s*(?:น\.?)?\s*", text)
    if not m:
        raise ValueError("time")
    return time(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def looks_like_patient_id(cells: list[str], ignore: frozenset[int]) -> bool:
    for i, cell in enumerate(cells):
        if i in ignore or not cell:
            continue
        if any(p.search(cell) for p in _HN_PATTERNS):
            return True
    return False


def parse_tab(kind: str, values: list[list[str]]) -> ParsedTab:
    if not values:
        raise HeaderError(f"Tab '{tab_title(kind)}' is empty (no header row).")
    cols = detect_columns(kind, values[0])
    ix = cols.index
    out = ParsedTab(kind)
    seen: set[str] = set()
    for n, raw in enumerate(values[1:], start=2):
        cells = [(c or "").strip() for c in raw]
        cells += [""] * (len(values[0]) - len(cells))
        if not any(cells):
            continue

        def cell(name: str) -> str:
            return cells[ix[name]]

        row_id = cell("row_id")

        def skip(reason: str) -> None:
            out.skipped.append(SkippedRow(kind, n, row_id[:16], reason))

        if looks_like_patient_id(cells, cols.ignored_for_hn):
            skip("possible_patient_identifier")  # never echo the cell
            continue
        if not _ROW_ID_RE.match(row_id):
            skip("bad_row_id")
            continue
        if row_id.lower() in seen:
            skip("duplicate_row_id")
            continue
        seen.add(row_id.lower())
        if not cell("bcm"):
            skip("missing_bcm")
            continue
        if not cell("ward"):
            skip("missing_ward")
            continue
        try:
            when = datetime.combine(_parse_date(cell("date")), _parse_time(cell("time")), tzinfo=BANGKOK)
        except ValueError:
            skip("bad_date_or_time")
            continue
        failed = tuple(
            label for (i, label) in cols.accessories if cells[i].strip().casefold() in _FAIL_MARKS
        )
        out.rows.append(
            LegacyRow(
                kind=kind,
                sheet_row=n,
                row_id=row_id.lower(),
                doc_no=cell("doc_no")[:40],
                occurred_at=when.astimezone(timezone.utc),
                bcm_raw=cell("bcm"),
                ward_raw=cell("ward"),
                bme_name=cell("bme")[:40],
                failed_accessories=failed,
            )
        )
    return out
