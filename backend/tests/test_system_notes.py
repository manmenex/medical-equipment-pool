"""System-note text must never be shown as a name."""
from app.services.system_notes import clean_label, has_system_text


def test_clean_label_keeps_plain_name():
    assert clean_label("พิพัฒน์") == "พิพัฒน์"
    assert clean_label("  ") is None and clean_label(None) is None


def test_clean_label_drops_system_note():
    assert clean_label("legacy sheet receipt row 1; BME X") is None


def test_clean_label_strips_appended_return_trace():
    assert clean_label("พิพัฒน์\n[Return] legacy sheet receipt row 3d87cd27") == "พิพัฒน์"
    assert clean_label("พิพัฒน์ [Return] legacy sheet receipt row 3d87cd27") == "พิพัฒน์"


def test_has_system_text():
    assert has_system_text("A\n[Return] legacy sheet receipt row x")
    assert not has_system_text("พิพัฒน์")
