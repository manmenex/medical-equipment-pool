import re
from datetime import date, datetime, timezone

from app.schemas.report_export import ReportIdentity

# Roadmap PR18B (docs/design/PR18_PRINTING_EXPORT_PLAN.md §15 "Filename
# Convention"): "{report-id}_{date-or-range}_{shift-or-all}_{generated-utc}"
# -- deterministic, safe, and free of patient/unnecessary personal data. This
# builds the filename *stem* only (no extension); the extension is supplied
# by whichever future renderer (PR18D PDF, PR18E Excel) actually produces a
# file -- this foundation slice never hardcodes one (design §15's own rule).

_UNSAFE_CHARS = re.compile(r"[^a-z0-9._-]")

# Bounded so a pathological filter combination can never produce an
# unreasonably long filename/header value (design §15 "bounded length").
_MAX_STEM_LENGTH = 200


def _sanitize_segment(value: str) -> str:
    """Lowercases and strips every character outside the design's declared
    safe set (`[a-z0-9._-]`) -- never a raw, unvalidated filter value."""
    return _UNSAFE_CHARS.sub("", value.lower())


def date_range_segment(date_from: date | None, date_to: date | None) -> str:
    """"date-or-range" segment (design §15 examples): a single ISO date, an
    inclusive ISO range joined by "-to-", or "all" when neither bound is
    supplied."""
    if date_from is None and date_to is None:
        return "all"
    if date_from is not None and date_to is not None and date_from == date_to:
        return date_from.isoformat()
    from_part = date_from.isoformat() if date_from is not None else "all"
    to_part = date_to.isoformat() if date_to is not None else "all"
    return f"{from_part}-to-{to_part}"


def shift_segment(shift_value: str | None) -> str:
    """"shift-or-all" segment: the raw ASCII shift value (`day`/`night`,
    never a Thai label -- filenames stay ASCII per design §15) or "all"."""
    return shift_value if shift_value is not None else "all"


def build_filename_stem(
    report_identity: ReportIdentity,
    *,
    date_segment: str,
    shift_segment_value: str,
    generated_at: datetime,
) -> str:
    """Assembles the deterministic filename stem (design §15). `generated_at`
    is converted to UTC regardless of its own timezone (matching this
    repository's `UTCDateTime`/`datetime.now(timezone.utc)` convention) --
    the generation timestamp is always rendered in UTC for uniqueness,
    independent of the report's own Asia/Bangkok display timezone."""
    generated_at_utc = generated_at.astimezone(timezone.utc)
    timestamp = generated_at_utc.strftime("%Y%m%dT%H%M%SZ")
    stem = "_".join(
        (
            _sanitize_segment(report_identity.value),
            _sanitize_segment(date_segment),
            _sanitize_segment(shift_segment_value),
            timestamp,
        )
    )
    return stem[:_MAX_STEM_LENGTH]
