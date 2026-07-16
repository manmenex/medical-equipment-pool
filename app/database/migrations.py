"""
Lightweight forward-only schema migrations.

`schema.sql` always describes the *current* shape of a fresh database
(via `CREATE TABLE IF NOT EXISTS`). This module exists purely to evolve an
*existing* database created by an older build - e.g. adding a column that
didn't exist in v1. Add a new `_migrate_to_vN` function and register it
below whenever a released schema changes.
"""

from __future__ import annotations

import sqlite3

from app.utils.logging_config import get_logger

logger = get_logger(__name__)

CURRENT_SCHEMA_VERSION = 1


def _get_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    return int(row[0]) if row else 0


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()


# Registry of migration steps: {target_version: callable(conn)}
_MIGRATIONS: dict[int, "callable"] = {
    # 2: _migrate_to_v2,
}


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to `CURRENT_SCHEMA_VERSION`."""
    version = _get_version(conn)
    if version == 0:
        # Fresh database that just had schema.sql applied.
        _set_version(conn, CURRENT_SCHEMA_VERSION)
        return

    while version < CURRENT_SCHEMA_VERSION:
        next_version = version + 1
        migration = _MIGRATIONS.get(next_version)
        if migration is None:
            logger.warning("No migration registered for version %s; skipping", next_version)
            break
        logger.info("Applying migration to schema v%s", next_version)
        migration(conn)
        version = next_version
        _set_version(conn, version)
