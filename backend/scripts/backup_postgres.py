#!/usr/bin/env python3
"""PR24C: back up the application PostgreSQL database.

docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §11 / OD-PR24-3:
PostgreSQL is the system of record for all persisted application state
(including import_source_blobs's BYTEA content -- there is no separate
object-storage backup stream, per §12's own finding). This script takes
a single, transactionally-consistent logical backup via `pg_dump
--format=custom`.

Usage:
    python scripts/backup_postgres.py \\
        --database-url postgresql+asyncpg://user:pass@host:5432/dbname \\
        --environment production \\
        [--output-dir backups/postgres] \\
        [--baseline-sha <git-sha>]

Reads DATABASE_URL / ENVIRONMENT / BACKUP_OUTPUT_DIR / MEP_BASELINE_SHA
from the environment if the matching flag is omitted.

Produces (both under --output-dir):
    mep-postgres-<environment>-<UTCTIMESTAMP>.dump
    mep-postgres-<environment>-<UTCTIMESTAMP>.dump.manifest.json

On any failure: exits non-zero, writes no manifest, and removes any
partial dump file -- never leaves a false-PASS artifact, and (since
every filename is uniquely timestamped) never touches a previously
successful backup.

Never logs, prints, or passes DATABASE_URL / the database password on
any command line -- see pg_backup_lib.ConnectionParams.as_libpq_env().
"""

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.pg_backup_lib import (  # noqa: E402
    BackupManifest,
    backup_filename,
    default_backup_dir,
    manifest_filename_for,
    parse_database_url,
    sha256_checksum,
    utc_now,
)
from scripts.pg_backup_verify import AlembicRevisionUnavailableError, get_alembic_revision  # noqa: E402


def _pg_dump_version() -> str:
    result = subprocess.run(["pg_dump", "--version"], capture_output=True, text=True, timeout=10)
    return result.stdout.strip() or result.stderr.strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"), help="Defaults to $DATABASE_URL")
    parser.add_argument(
        "--environment",
        default=os.environ.get("ENVIRONMENT", "unknown"),
        help="Defaults to $ENVIRONMENT (e.g. production, staging)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("BACKUP_OUTPUT_DIR"),
        help="Defaults to $BACKUP_OUTPUT_DIR, falling back to <repo-root>/backups/postgres",
    )
    parser.add_argument(
        "--baseline-sha",
        default=os.environ.get("MEP_BASELINE_SHA"),
        help="Optional application baseline commit SHA, recorded in the manifest only",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.database_url:
        print("[backup] FAIL: --database-url not given and $DATABASE_URL is not set", file=sys.stderr)
        return 1

    try:
        conn = parse_database_url(args.database_url)
    except ValueError as exc:
        print(f"[backup] FAIL: invalid --database-url: {exc}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir) if args.output_dir else default_backup_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    created_at = utc_now()
    filename = backup_filename(args.environment, created_at)
    final_path = output_dir / filename
    partial_path = output_dir / f"{filename}.partial"
    manifest_path = output_dir / manifest_filename_for(filename)

    print(f"[backup] starting: target={conn.redacted()} environment={args.environment!r}")

    try:
        alembic_revision = asyncio.run(get_alembic_revision(conn))
    except AlembicRevisionUnavailableError as exc:
        print(f"[backup] FAIL: could not read Alembic revision before backup: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - connection failures vary by driver
        print(f"[backup] FAIL: could not connect to {conn.redacted()} to read Alembic revision: {exc}", file=sys.stderr)
        return 1

    result = subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(partial_path)],
        env={**os.environ, **conn.as_libpq_env()},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[backup] FAIL: pg_dump exited {result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        partial_path.unlink(missing_ok=True)
        return 1

    partial_path.rename(final_path)

    manifest = BackupManifest(
        backup_filename=filename,
        created_at=created_at.isoformat(),
        environment=args.environment,
        baseline_sha=args.baseline_sha,
        alembic_revision=alembic_revision,
        database_name=conn.dbname,
        host=conn.host,
        port=conn.port,
        file_size_bytes=final_path.stat().st_size,
        checksum_sha256=sha256_checksum(final_path),
        tool="pg_dump",
        tool_version=_pg_dump_version(),
    )
    manifest_path.write_text(manifest.to_json())

    print(f"[backup] OK: {final_path}")
    print(f"[backup]     size_bytes={manifest.file_size_bytes} checksum_sha256={manifest.checksum_sha256}")
    print(f"[backup]     alembic_revision={alembic_revision} manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
