from datetime import datetime

from app.database.db import Database


def test_schema_creates_all_expected_tables(tmp_path):
    db = Database(tmp_path / "test.db")
    rows = db.query_all("SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in rows}
    expected = {
        "fda_recalls",
        "ecri_alerts",
        "inventory_items",
        "match_results",
        "report_runs",
        "app_settings",
        "audit_log",
        "schema_version",
    }
    assert expected.issubset(names)
    db.close()


def test_parametrized_insert_and_query_round_trip(tmp_path):
    db = Database(tmp_path / "test2.db")
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO fda_recalls (recall_number, manufacturer, fetched_at) VALUES (?, ?, ?)",
        ("Z-100; DROP TABLE fda_recalls;--", "Acme", now),
    )
    row = db.query_one("SELECT * FROM fda_recalls WHERE recall_number = ?", ("Z-100; DROP TABLE fda_recalls;--",))
    assert row is not None
    assert row["manufacturer"] == "Acme"
    # Table must still exist - parametrized queries prevent the injected DDL from ever running.
    tables = {r["name"] for r in db.query_all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "fda_recalls" in tables
    db.close()


def test_unique_constraint_on_recall_number(tmp_path):
    db = Database(tmp_path / "test3.db")
    now = datetime.now().isoformat()
    db.execute("INSERT INTO fda_recalls (recall_number, fetched_at) VALUES (?, ?)", ("R-1", now))
    from app.utils.exceptions import DatabaseError
    import pytest

    with pytest.raises(DatabaseError):
        db.execute("INSERT INTO fda_recalls (recall_number, fetched_at) VALUES (?, ?)", ("R-1", now))
    db.close()
