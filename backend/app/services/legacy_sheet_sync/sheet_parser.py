"""Parse the legacy pool sheet tabs into typed rows (pure, no I/O).

Columns are located by HEADER TEXT (prefix match after normalisation), never
by letter, because the Owner's screenshots show truncated headers. A missing
required header fails the whole read clearly (``HeaderError``).

Privacy rules (Governance 2026-10-21):
* A row containing something that looks like a patient hospital number (HN)
  is skipped, and the report never echoes the offending cell.
* Free-text notes are NOT read into the result. Only the accessory check-mark
  columns are summarised (which ones show a failure mark).
* The ward-side person column ("ชื่อ (User)") is read ONLY into the D7 ward
  contact name (optional column; Owner Governance 2026-11-25 D7 / PR27 maps
  it, amending the 2026-10-21 "never stored" rule). It is still HN-screened
  like every other cell, and it is never a user/account.
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
    "bme": ("ชื่อbme", "ชื่อ(bme)", "ผู้รับเครื่อง(bme)", "ผู้ส่งเครื่อง(bme)", "ผู้ส่งเครื่องยืม(bme)"),
}
# Optional ward-side person column; the receipt tab may label it by role.
_USER_HEADERS = ("ชื่อ(user)", "ผู้รับเครื่อง(user)", "ผู้ส่งเครื่อง(user)", "ผู้ส่งเครื่องยืม(user)", "ผู้คืนเครื่อง(user)")
_DOC_PREFIX = {KIND_DISPATCH: "เลขที่ใบส่ง", KIND_RECEIPT: "เลขที่ใบรับ"}
_STOP_ACCESSORY = ("จำนวน", "หมายเหตุ", "เวลา", "ชื่อ", "ผู้")

_HN_PATTERNS = (
    re.compile(r"(?<![a-z])hn\s*[:.\-#]?\s*\d{3,}", re.IGNORECASE),
    re.compile(r"^\s*\d{6,}\s*$"),
)
_FAIL_MARKS = {"✗", "✘", "✕", "✖", "❌", "×", "x", "false", "no", "ไม่"}
_OK_MARKS = {"✓", "✔", "☑", "√", "true", "yes", "ok", "/"}
# Header prefixes (normalised) of the three D4 standard-checklist columns.
_CHECK_HEADERS = {"screen": ("หน้าจอ",), "charger": ("สายชาร์จ",), "clamp": ("clamp", "ขาจับเสา")}
_ROW_ID_RE = re.compile(r"^[0-9a-fA-F]{8}$")


@dataclass(frozen=True)
class Columns:
    kind: str
    index: dict[str, int]
    accessories: list[tuple[int, str]]  # (column index, header label)
    ignored_for_hn: frozenset[int]
    check_columns: dict[str, int] = field(default_factory=dict)  # screen/charger/clamp; {} unless all 3 map cleanly


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
    user_name: str = ""  # ward-side person ("ชื่อ (User)") -> D7 contact name
    failed_accessories: tuple[str, ...] = ()
    # D4 standard checklist from the sheet: screen/charger/clamp -> True (✓),
    # False (✗) or None (blank/unknown). {} when the columns do not map cleanly.
    check_marks: dict[str, bool | None] = field(default_factory=dict)


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

    def find(prefix) -> int | None:
        prefixes = [prefix] if isinstance(prefix, str) else list(prefix)
        for p in prefixes:
            p = _norm(p)  # NFKC rewrites Thai sara-am, so both sides must be normalised
            for i, h in enumerate(norm):
                if h.startswith(p):
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
    user_col = find(_USER_HEADERS)
    if user_col is not None:
        index["user"] = user_col  # optional: older sheets may lack it
    scan = find("scancode")
    ignored = {index[k] for k in ("row_id", "date", "time", "doc_no")}
    if scan is not None:
        ignored.add(scan)
    # Device-description block between the ME.Code and ward columns (equipment
    # name, brand, model, serial number, photo link): a long numeric serial
    # (e.g. a 10-digit pneumatic-pump SN) is not an HN. Free-text columns such
    # as the note stay scanned.
    ignored.update(range(index["bcm"] + 1, index["ward"]))
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
    return Columns(kind, index, accessories, frozenset(ignored), _map_check_columns(accessories))


def _map_check_columns(accessories: list[tuple[int, str]]) -> dict[str, int]:
    """Map the accessory columns to screen/charger/clamp by header text. Any
    deviation (not exactly three, a duplicate or an unrecognised header)
    yields {} -- never guess a mapping."""
    if len(accessories) != 3:
        return {}
    found: dict[str, int] = {}
    for col, label in accessories:
        key = next((k for k, pres in _CHECK_HEADERS.items() if any(_norm(p) in _norm(label) for p in pres)), None)
        if key is None or key in found:
            return {}
        found[key] = col
    return found


def _mark_text(text: str) -> str:
    return (text or "").replace("\ufe0f", "").strip().casefold()


def _mark(text: str) -> bool | None:
    t = _mark_text(text)
    if t in _OK_MARKS:
        return True
    if t in _FAIL_MARKS:
        return False
    return None


_MONTHS: dict[str, int] = {}
for _i, _names in enumerate(
    [
        ("jan", "january", "ม.ค."),
        ("feb", "february", "ก.พ."),
        ("mar", "march", "มี.ค."),
        ("apr", "april", "เม.ย."),
        ("may", "พ.ค."),
        ("jun", "june", "มิ.ย."),
        ("jul", "july", "ก.ค."),
        ("aug", "august", "ส.ค."),
        ("sep", "sept", "september", "ก.ย."),
        ("oct", "october", "ต.ค."),
        ("nov", "november", "พ.ย."),
        ("dec", "december", "ธ.ค."),
    ],
    start=1,
):
    for _n in _names:
        _MONTHS[_n] = _i


def _month_from_name(token: str) -> int | None:
    # Case-insensitive; Thai abbreviations may contain spaces ("ม. ค.").
    return _MONTHS.get(re.sub(r"\s+", "", token).lower())


def _clean_person(text: str) -> str:
    """Display-only person name: no control characters, at most 100 chars."""
    return "".join(ch for ch in (text or "") if ord(ch) >= 32 and ord(ch) != 127).strip()[:100]


def _parse_date(text: str) -> date:
    m = re.fullmatch(r"\s*(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})\s*", text)
    if m:
        a, b, c = (int(x) for x in m.groups())
        y, mo, d = (a, b, c) if a > 31 else (c, b, a)  # yyyy-mm-dd or dd/mm/yyyy
    else:
        # d/Mon/yyyy or d-Mon-yyyy (English or Thai month name).
        m = re.fullmatch(r"\s*(\d{1,2})\s*[/\-]?\s*([^\d/\-]+?)\s*[/\-]?\s*(\d{4})\s*", text)
        if not m:
            raise ValueError("date")
        mo_name = _month_from_name(m.group(2))
        if mo_name is None:
            raise ValueError("date")
        d, mo, y = int(m.group(1)), mo_name, int(m.group(3))
    if y > 2400:  # Buddhist Era
        y -= 543
    return date(y, mo, d)


def _parse_time(text: str) -> time:
    m = re.fullmatch(
        r"\s*(\d{1,2})[:.](\d{2})(?::(\d{2}))?\s*(?:(am|pm)|น\.?)?\s*", text, re.IGNORECASE
    )
    if not m:
        raise ValueError("time")
    hour = int(m.group(1))
    if m.group(4):
        if not 1 <= hour <= 12:
            raise ValueError("time")
        hour = hour % 12 + (12 if m.group(4).lower() == "pm" else 0)
    return time(hour, int(m.group(2)), int(m.group(3) or 0))


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
            label for (i, label) in cols.accessories if _mark_text(cells[i]) in _FAIL_MARKS
        )
        marks = {k: _mark(cells[i]) for k, i in cols.check_columns.items()}
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
                user_name=_clean_person(cell("user") if "user" in cols.index else ""),
                failed_accessories=failed,
                check_marks=marks,
            )
        )
    return out
