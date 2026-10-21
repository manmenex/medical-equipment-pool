"""Async verification queries against a live PostgreSQL database, shared
by backup_postgres.py (capture) and restore_postgres.py (compare).

Uses asyncpg directly (in-process connections, not a subprocess) rather
than shelling out to `psql` -- matches backend/scripts/postgres_ci_gate.py's
own convention, and keeps the connection string out of any process argv.
"""

from __future__ import annotations

import asyncpg

from scripts.pg_backup_lib import ConnectionParams

# PR24C §18: a small, fixed, deterministic set of representative
# application tables -- covers the core domain (equipment, wards, users,
# transactions) plus the audit trail. Row counts only, never full row
# dumps, to avoid exposing operational/hospital data in rehearsal
# evidence output (PR24C §18's own instruction).
REPRESENTATIVE_TABLES = ("equipment", "wards", "users", "borrow_transactions", "audit_logs")


class AlembicRevisionUnavailableError(RuntimeError):
    """Raised when a database's current Alembic revision cannot be
    established as a single authoritative value."""


async def get_alembic_revision(conn_params: ConnectionParams) -> str:
    """Mirrors app.crud.cutover_readiness.get_current_database_migration_head's
    own fail-closed contract (exactly one row in alembic_version) without
    importing the FastAPI application -- this is a standalone ops script,
    not a request-handling code path."""
    conn = await asyncpg.connect(conn_params.asyncpg_dsn())
    try:
        rows = await conn.fetch("SELECT version_num FROM alembic_version")
    finally:
        await conn.close()
    if len(rows) != 1:
        raise AlembicRevisionUnavailableError(
            f"Expected exactly one row in alembic_version at {conn_params.redacted()}, found {len(rows)}."
        )
    return rows[0]["version_num"]


async def get_representative_row_counts(conn_params: ConnectionParams) -> dict[str, int]:
    conn = await asyncpg.connect(conn_params.asyncpg_dsn())
    try:
        counts: dict[str, int] = {}
        for table in REPRESENTATIVE_TABLES:
            # REPRESENTATIVE_TABLES is a fixed constant defined in this
            # module, never operator/CLI input -- safe to interpolate
            # into SQL (asyncpg has no DDL/identifier bind-parameter
            # support, and this list is not user-controlled).
            counts[table] = await conn.fetchval(f'SELECT COUNT(*) FROM "{table}"')
        return counts
    finally:
        await conn.close()


async def target_database_is_empty(conn_params: ConnectionParams) -> bool:
    """True if the target database has no user tables in the `public`
    schema -- used by restore_postgres.py as an extra safety check
    before restoring, beyond the source/Production guards in
    pg_backup_lib.guard_restore_target()."""
    conn = await asyncpg.connect(conn_params.asyncpg_dsn())
    try:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        return count == 0
    finally:
        await conn.close()
