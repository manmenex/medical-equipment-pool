"""System-generated transaction notes are internal bookkeeping, never an
operator remark. The legacy sheet sync stores a trace line ("legacy sheet
dispatch row ...") in ``notes``; printed forms and Excel reports must show
only what a person typed, so they filter through ``operator_note``."""

SYSTEM_NOTE_PREFIX = "legacy sheet "


def is_system_note(note: str | None) -> bool:
    return bool(note) and note.lstrip().lower().startswith(SYSTEM_NOTE_PREFIX)


def operator_note(note: str | None) -> str | None:
    """The operator-entered remark, or None when the note is system text."""
    return None if is_system_note(note) else note
