"""Roadmap PR33 (D14): the "DEMO" / "ยืม" source badge as plain text, for
reports/exports where a styled badge cannot be rendered. Pool devices get no
badge."""

SOURCE_BADGES = {"demo": "DEMO", "loan": "ยืม"}


def badge_text(source: str | None) -> str | None:
    return SOURCE_BADGES.get(source or "")


def with_badge(text: str | None, source: str | None) -> str | None:
    """``[DEMO] text`` / ``[ยืม] text`` for demo/loan, unchanged for pool."""
    badge = badge_text(source)
    if badge is None or text is None:
        return text
    return f"[{badge}] {text}"
