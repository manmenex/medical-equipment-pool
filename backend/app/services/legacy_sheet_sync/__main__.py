"""CLI / runner for the legacy pool sheet shadow sync.

    python -m app.services.legacy_sheet_sync --once --dry-run   print the plan
    python -m app.services.legacy_sheet_sync --once             one real pass
    python -m app.services.legacy_sheet_sync --loop             every N seconds

Exit codes: 0 ok, 1 error, 2 refused because LEGACY_SHEET_SYNC_ENABLED is not
true (a dry run is allowed without it: it writes nothing).
"""
import argparse
import asyncio
import logging
import sys

from app.services.legacy_sheet_sync.config import SyncConfig, SyncConfigError, load_config
from app.services.legacy_sheet_sync.runner import RunReport, run_once
from app.services.legacy_sheet_sync.sheet_parser import HeaderError
from app.services.legacy_sheet_sync.sheets_client import GoogleSheetsReader, SheetsError

logger = logging.getLogger("legacy_sheet_sync")


def print_report(report: RunReport) -> None:
    print(report.summary())
    for line in report.planned:
        print("  would:", line)
    for s in report.skipped:
        print(f"  skipped {s['tab']} row {s['row_id']}: {s['reason']}")
    for r in report.review:
        print(f"  needs review {r['tab']} row {r['row_id']}: {r['result']} {r['code']}")


async def _pass(cfg: SyncConfig, *, dry_run: bool, session_factory=None, reader=None) -> RunReport:
    cfg.require_source()
    if session_factory is None:
        from app.db.session import AsyncSessionLocal as session_factory
    reader = reader or GoogleSheetsReader(cfg.key_file, cfg.spreadsheet_id)
    return await run_once(session_factory, reader, cfg, dry_run=dry_run)


async def _loop(cfg: SyncConfig) -> int:
    logger.info("legacy_sheet_sync loop started interval=%ss", cfg.interval_seconds)
    while True:
        try:
            await _pass(cfg, dry_run=False)
        except (SyncConfigError, SheetsError, HeaderError) as exc:
            logger.error("legacy_sheet_sync pass failed: %s", exc)
        except Exception as exc:  # never crash the runner
            logger.error("legacy_sheet_sync pass failed unexpectedly (%s)", type(exc).__name__)
        await asyncio.sleep(cfg.interval_seconds)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="with --once: read and plan, write nothing")
    args = p.parse_args(argv)
    if args.dry_run and not args.once:
        p.error("--dry-run requires --once")
    try:
        cfg = load_config()
        if not cfg.enabled and not args.dry_run:
            print("Legacy sheet sync is disabled (LEGACY_SHEET_SYNC_ENABLED is not true). Nothing done.")
            return 0 if args.loop else 2
        if args.loop:
            return asyncio.run(_loop(cfg))
        print_report(asyncio.run(_pass(cfg, dry_run=args.dry_run)))
        return 0
    except (SyncConfigError, SheetsError, HeaderError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
