"""System-generated transaction notes are internal bookkeeping, never an
operator remark. The legacy sheet sync stores a trace line ("legacy sheet
dispatch row ...") in ``notes``; printed forms and Excel reports must show
only what a person typed, so they filter through ``operator_note``."""

import re

SYSTEM_NOTE_PREFIX = "legacy sheet "


def is_system_note(note: str | None) -> bool:
    return bool(note) and note.lstrip().lower().startswith(SYSTEM_NOTE_PREFIX)


def operator_note(note: str | None) -> str | None:
    """The operator-entered remark, or None when the note is system text."""
    return None if is_system_note(note) else note


def has_system_text(label: str | None) -> bool:
    """True when a label carries system-note text anywhere (e.g. a name followed
    by an appended "[Return] legacy sheet receipt row ..." line) or spans lines."""
    return bool(label) and ("\n" in label or SYSTEM_NOTE_PREFIX in label.lower())


def clean_label(label: str | None) -> str | None:
    """A display label, or None when empty or system-note text (never printed).

    Only the first line is a name; anything appended after it (sync trace
    lines such as "[Return] legacy sheet receipt row ...") is dropped."""
    if not label or not label.strip():
        return None
    first = label.strip().splitlines()[0].strip()
    if not first or is_system_note(first):
        return None
    cut = first.lower().find(SYSTEM_NOTE_PREFIX)
    if cut != -1:
        first = re.sub(r"\s*\[return\]\s*$", "", first[:cut], flags=re.IGNORECASE).strip()
    return first or None
