#!/usr/bin/env python3
"""PR24C: delete backup artifacts older than the retention window.

docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §11 / OD-PR24-3:
backup retention is 30 days (DEFAULT_RETENTION_DAYS in pg_backup_lib.py).

Usage:
    python scripts/prune_backups.py [--backup-dir backups/postgres] [--retention-days 30] [--dry-run]

Safety (see pg_backup_lib.select_prune_candidates for the tested logic):
    - only ever considers files directly inside --backup-dir matching
      the mep-postgres-<environment>-<timestamp>.dump naming pattern
      (never a generic rm -rf, never touches unrelated files)
    - the single newest backup is never deleted, even if its own
      timestamp is technically past the cutoff
    - --dry-run prints what would be deleted without deleting anything
    - each backup's .manifest.json sidecar is deleted alongside it
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.pg_backup_lib import (  # noqa: E402
    DEFAULT_RETENTION_DAYS,
    default_backup_dir,
    manifest_filename_for,
    parse_backup_filename,
    select_prune_candidates,
    utc_now,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backup-dir", default=os.environ.get("BACKUP_OUTPUT_DIR"))
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    backup_dir = Path(args.backup_dir) if args.backup_dir else default_backup_dir()
    if not backup_dir.is_dir():
        print(f"[prune] nothing to do: {backup_dir} does not exist")
        return 0

    resolved_backup_dir = backup_dir.resolve()
    backups: list[tuple[Path, "object"]] = []
    for entry in backup_dir.iterdir():
        # Only files directly inside --backup-dir (not a symlink escape,
        # not a subdirectory) matching the exact naming pattern are ever
        # considered -- see pg_backup_lib.BACKUP_FILENAME_RE.
        if not entry.is_file():
            continue
        if entry.resolve().parent != resolved_backup_dir:
            continue
        parsed = parse_backup_filename(entry.name)
        if parsed is None:
            continue
        _environment, created_at = parsed
        backups.append((entry, created_at))

    now = utc_now()
    candidates = select_prune_candidates(backups, now=now, retention_days=args.retention_days)

    if not candidates:
        print(f"[prune] nothing eligible for deletion (retention_days={args.retention_days}, {len(backups)} backups on disk)")
        return 0

    for dump_path in candidates:
        manifest_path = dump_path.with_name(manifest_filename_for(dump_path.name))
        if args.dry_run:
            print(f"[prune] would delete: {dump_path.name} (and {manifest_path.name} if present)")
            continue
        dump_path.unlink()
        manifest_path.unlink(missing_ok=True)
        print(f"[prune] deleted: {dump_path.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
