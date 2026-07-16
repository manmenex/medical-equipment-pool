"""
SQLite connection management.

Design notes
------------
* A single `Database` wrapper owns the connection and exposes only
  parametrized helpers (`execute`, `executemany`, `query_all`, `query_one`).
  No calling code ever builds SQL by string-concatenating user input, which
  is what actually prevents SQL injection (not the ORM/lack thereof).
* `sqlite3.Row` is used as the row factory so results behave like
  dictionaries (`row["column"]`) without pulling in a full ORM.
* WAL journal mode is enabled for better concurrent read/write behavior
  between the GUI thread and background scheduler jobs.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from app.database.migrations import CURRENT_SCHEMA_VERSION, apply_migrations
from app.utils.exceptions import DatabaseError
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

_SCHEMA_FILE = Path(__file__).with_name("schema.sql")


class Database:
    """Thread-safe-ish wrapper around a single SQLite database file.

    SQLite connections are not shared across threads by default; this
    class opens one connection per instance and serializes access with a
    lock, which is sufficient for a desktop app with a GUI thread plus an
    occasional background scheduler thread.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._initialize_schema()

    # -- lifecycle ---------------------------------------------------------
    def _initialize_schema(self) -> None:
        with self._lock:
            try:
                script = _SCHEMA_FILE.read_text(encoding="utf-8")
                self._conn.executescript(script)
                self._conn.commit()
                apply_migrations(self._conn)
            except sqlite3.Error as exc:  # pragma: no cover - defensive
                raise DatabaseError(f"Failed to initialize schema: {exc}") from exc
        logger.info("Database ready at %s (schema v%s)", self.db_path, CURRENT_SCHEMA_VERSION)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- generic parametrized helpers ---------------------------------------
    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        """Run a single parametrized statement and commit."""
        with self._lock:
            try:
                cur = self._conn.execute(sql, params)
                self._conn.commit()
                return cur
            except sqlite3.Error as exc:
                self._conn.rollback()
                logger.error("SQL execute failed: %s | params=%r | %s", sql, params, exc)
                raise DatabaseError(str(exc)) from exc

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        with self._lock:
            try:
                cur = self._conn.executemany(sql, list(seq_of_params))
                self._conn.commit()
                return cur
            except sqlite3.Error as exc:
                self._conn.rollback()
                logger.error("SQL executemany failed: %s | %s", sql, exc)
                raise DatabaseError(str(exc)) from exc

    def query_all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                return list(self._conn.execute(sql, params).fetchall())
            except sqlite3.Error as exc:
                logger.error("SQL query failed: %s | params=%r | %s", sql, params, exc)
                raise DatabaseError(str(exc)) from exc

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            try:
                return self._conn.execute(sql, params).fetchone()
            except sqlite3.Error as exc:
                logger.error("SQL query failed: %s | params=%r | %s", sql, params, exc)
                raise DatabaseError(str(exc)) from exc

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Explicit transaction context manager for multi-statement writes."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    @property
    def raw_connection(self) -> sqlite3.Connection:
        """Escape hatch for report generation (pandas.read_sql_query needs a connection)."""
        return self._conn


_INSTANCE: Database | None = None
_INSTANCE_LOCK = threading.Lock()


def get_database(db_path: Path | None = None) -> Database:
    """Return the process-wide `Database` singleton, creating it on first use."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            if db_path is None:
                from app.config import get_settings

                db_path = get_settings().database_path
            _INSTANCE = Database(db_path)
        return _INSTANCE


def reset_database_singleton() -> None:
    """Close and clear the singleton - primarily for tests."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is not None:
            _INSTANCE.close()
            _INSTANCE = None
