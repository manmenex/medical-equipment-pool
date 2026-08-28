#!/usr/bin/env python3
"""PR24C: restore a PostgreSQL backup into a disposable, non-production
database, and verify it.

docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §11: restore
rehearsal proves the backup is actually usable, into a separate,
disposable database -- NEVER restored directly over Production "as the
test." This script has no `--allow-production-restore` flag anywhere;
see pg_backup_lib.guard_restore_target() for the two independent guards.

Fix Round 1 (PR #132 independent review, [P1]): the same-source-database
guard is now UNCONDITIONAL. The backup manifest always records the
source database's host/port/database name, and that manifest-derived
identity is always what the restore target is checked against --
whether or not --source-database-url is supplied. --source-database-url
is optional and only enables an *additional* live source connection
(for row-count comparison); it never enables or disables the guard
itself, and it must match the manifest's recorded source identity or
the restore is refused before any destructive action.

Usage:
    python scripts/restore_postgres.py \\
        --backup-file backups/postgres/mep-postgres-staging-20260828T120000Z.dump \\
        --target-database-url postgresql+asyncpg://user:pass@disposable-host:5432/mep_restore_rehearsal \\
        --target-environment staging \\
        [--source-database-url postgresql+asyncpg://user:pass@source-host:5432/mep_db] \\
        [--force-non-empty-target]

Procedure (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §11,
this task's own §16):
    1. verify backup checksum against its manifest (hard fail on mismatch)
    2. derive source identity (host/port/database name) from the manifest
    3. guard: refuse a target labeled production, or matching the
       manifest-derived source identity -- unconditional, not gated on
       --source-database-url
    4. if --source-database-url is given, verify it agrees with the
       manifest's source identity (fail closed on mismatch) before using
       it for live verification
    5. guard: refuse a non-empty target unless --force-non-empty-target
    6. pg_restore into the target
    7. verify the restored Alembic revision matches the manifest's
       (never runs `alembic upgrade` -- restore fidelity is proven
       before any migration upgrade, per this task's own §17)
    8. verify representative table row counts (and diff against the
       source database's own counts, if --source-database-url is given)
    9. print elapsed wall-clock time, for comparison against the
       Owner-approved RTO target (<= 4 hours, OD-PR24-3) -- this script
       reports the number, it does not itself claim pass/fail against a
       target that is a runbook/operator judgment (docs/runbooks/
       PR24_BACKUP_RESTORE_RUNBOOK.md)

Never logs, prints, or passes DATABASE_URL / the database password on
any command line -- see pg_backup_lib.ConnectionParams.as_libpq_env().
"""

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.pg_backup_lib import (  # noqa: E402
    BackupManifest,
    DatabaseIdentity,
    ProductionRestoreRefused,
    guard_restore_target,
    manifest_filename_for,
    parse_database_url,
    sha256_checksum,
)
from scripts.pg_backup_verify import (  # noqa: E402
    AlembicRevisionUnavailableError,
    get_alembic_revision,
    get_representative_row_counts,
    target_database_is_empty,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backup-file", required=True, help="Path to a .dump file produced by backup_postgres.py")
    parser.add_argument("--manifest", default=None, help="Defaults to <backup-file>.manifest.json")
    parser.add_argument(
        "--target-database-url",
        required=True,
        help="A disposable, non-production database to restore into. No default -- there is no normal "
        "command path that restores over Production.",
    )
    parser.add_argument(
        "--target-environment",
        required=True,
        help='Must not be "production" (case-insensitive) -- this is enforced, not advisory.',
    )
    parser.add_argument(
        "--source-database-url",
        default=None,
        help="Optional. The backup manifest always supplies source identity for restore-target safety -- "
        "this flag does not enable or disable that protection. If given, it is used only for additional "
        "live source verification (row-count comparison), and it must match the manifest's recorded "
        "source host/port/database name or the restore is refused before any destructive action.",
    )
    parser.add_argument(
        "--force-non-empty-target",
        action="store_true",
        help="Required to restore into a target database that already has tables. Absent by default so an "
        "accidental restore over an existing (even if non-production) database fails closed.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    start = time.monotonic()

    backup_path = Path(args.backup_file)
    if not backup_path.is_file():
        print(f"[restore] FAIL: backup file not found: {backup_path}", file=sys.stderr)
        return 1

    manifest_path = Path(args.manifest) if args.manifest else backup_path.with_name(manifest_filename_for(backup_path.name))
    if not manifest_path.is_file():
        print(f"[restore] FAIL: manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    manifest = BackupManifest.from_json(manifest_path.read_text())

    print(f"[restore] verifying checksum of {backup_path}")
    actual_checksum = sha256_checksum(backup_path)
    if actual_checksum != manifest.checksum_sha256:
        print(
            f"[restore] FAIL: checksum mismatch -- manifest says {manifest.checksum_sha256}, "
            f"actual file is {actual_checksum}. Refusing to restore a backup that does not match its "
            "recorded checksum.",
            file=sys.stderr,
        )
        return 1
    print("[restore] checksum OK")

    try:
        target = parse_database_url(args.target_database_url)
    except ValueError as exc:
        print(f"[restore] FAIL: invalid --target-database-url: {exc}", file=sys.stderr)
        return 1

    # Fix Round 1 (PR #132 independent review, [P1]): source identity for
    # the same-database guard is ALWAYS derived from the backup manifest,
    # never from the optional --source-database-url flag -- an operator
    # forgetting that flag must not silently disable this protection.
    source_identity = DatabaseIdentity.from_manifest(manifest)

    try:
        guard_restore_target(target=target, target_environment=args.target_environment, source_identity=source_identity)
    except ProductionRestoreRefused as exc:
        print(f"[restore] FAIL: {exc}", file=sys.stderr)
        return 1

    source = None
    if args.source_database_url:
        try:
            source = parse_database_url(args.source_database_url)
        except ValueError as exc:
            print(f"[restore] FAIL: invalid --source-database-url: {exc}", file=sys.stderr)
            return 1
        source_url_identity = DatabaseIdentity.from_connection_params(source)
        if not source_url_identity.matches(source_identity):
            print(
                f"[restore] FAIL: --source-database-url ({source_url_identity.redacted()}) does not match "
                f"the source database recorded in the backup manifest ({source_identity.redacted()}). "
                "Refusing to compare row counts against a source inconsistent with this backup's "
                "recorded provenance -- the manifest is authoritative.",
                file=sys.stderr,
            )
            return 1

    try:
        target_empty = asyncio.run(target_database_is_empty(target))
    except Exception as exc:  # noqa: BLE001
        print(f"[restore] FAIL: could not connect to target {target.redacted()}: {exc}", file=sys.stderr)
        return 1
    if not target_empty and not args.force_non_empty_target:
        print(
            f"[restore] FAIL: target {target.redacted()} already has tables. Pass --force-non-empty-target "
            "to restore into it anyway, or point at a genuinely empty disposable database.",
            file=sys.stderr,
        )
        return 1

    print(f"[restore] restoring into {target.redacted()}")
    result = subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges", "--dbname", target.dbname, str(backup_path)],
        env={**os.environ, **target.as_libpq_env()},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[restore] FAIL: pg_restore exited {result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1
    print("[restore] pg_restore OK")

    try:
        restored_revision = asyncio.run(get_alembic_revision(target))
    except AlembicRevisionUnavailableError as exc:
        print(f"[restore] FAIL: could not read restored Alembic revision: {exc}", file=sys.stderr)
        return 1
    if restored_revision != manifest.alembic_revision:
        print(
            f"[restore] FAIL: restored Alembic revision {restored_revision!r} does not match the backup's "
            f"recorded revision {manifest.alembic_revision!r}.",
            file=sys.stderr,
        )
        return 1
    print(f"[restore] Alembic revision verified: {restored_revision}")

    restored_counts = asyncio.run(get_representative_row_counts(target))
    print(f"[restore] restored row counts: {restored_counts}")

    counts_match = True
    if source is not None:
        source_counts = asyncio.run(get_representative_row_counts(source))
        print(f"[restore] source row counts:   {source_counts}")
        counts_match = source_counts == restored_counts
        if not counts_match:
            print("[restore] FAIL: row counts do not match between source and restored database", file=sys.stderr)

    elapsed_seconds = time.monotonic() - start
    print(f"[restore] elapsed_seconds={elapsed_seconds:.1f}")
    print(
        "[restore] Compare elapsed_seconds against the Owner-approved RTO target (<= 4 hours, OD-PR24-3) "
        "and record the result in docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md's evidence template."
    )

    if not counts_match:
        return 1

    print("[restore] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
