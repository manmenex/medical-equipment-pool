#!/usr/bin/env python3
"""PR24D: explicit, fail-closed migration deployment step.

docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §15/§20: Alembic
migrations are never run automatically on application boot -- they are an
explicit, separate deployment step, sequenced strictly before the new
application version receives traffic. This script is that step, wrapping
`alembic upgrade head` (already the exact command CI's own `migrations` job
and the Docker smoke-test job use) with before/after Alembic-revision
evidence and a fail-closed exit code.

Usage:
    DATABASE_URL=postgresql+asyncpg://... \\
    python scripts/deploy_migrate.py --target-environment staging --artifact-sha <commit-sha>

`DATABASE_URL` is read from the process environment only -- never accepted
as a CLI argument (would be `ps`/`/proc`-visible) and never echoed or
logged; matches backend/scripts/pg_backup_lib.py's own non-leak
convention. Only a redacted host/port/database identity is ever printed.

Evidence printed (never DATABASE_URL or credentials):
    target environment, artifact SHA, Alembic revision before, migration
    result, Alembic revision after.

Failure handling: any failure (unreachable database, `alembic upgrade`
non-zero exit, resulting revision not verifiable) exits non-zero and
prints which step failed. This script never proceeds to report success
if the post-migration revision cannot be positively confirmed via
`alembic_version` -- ambiguity is treated as failure, not silently
assumed to be fine.
"""

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.pg_backup_lib import parse_database_url  # noqa: E402
from scripts.pg_backup_verify import get_alembic_revision  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--target-environment",
        required=True,
        help="Human-readable label for the deployment target (e.g. staging). Recorded in evidence output only "
        "-- this script does not itself refuse a 'production' label (unlike restore_postgres.py's restore-"
        "target guard, migration deployment is a normal, intended production operation).",
    )
    parser.add_argument(
        "--artifact-sha",
        required=True,
        help="The exact Git commit SHA of the application artifact being deployed. Recorded in evidence "
        "output for traceability -- never invented if not supplied by the caller.",
    )
    return parser.parse_args()


def _current_revision_or_none(database_url: str) -> str | None:
    """Best-effort read of the current Alembic revision. Returns None if
    the table doesn't exist yet (a fresh, never-migrated database) or the
    row count is anything other than exactly one -- both legitimate
    'before' states this script must tolerate without treating them as a
    hard failure (only the *post*-migration read is fail-closed)."""
    try:
        params = parse_database_url(database_url)
    except ValueError:
        return None
    try:
        return asyncio.run(get_alembic_revision(params))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    args = _parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("[deploy-migrate] FAIL: DATABASE_URL is not set in the environment.", file=sys.stderr)
        return 1

    try:
        redacted_target = parse_database_url(database_url).redacted()
    except ValueError as exc:
        print(f"[deploy-migrate] FAIL: invalid DATABASE_URL: {exc}", file=sys.stderr)
        return 1

    print(f"[deploy-migrate] target_environment={args.target_environment}")
    print(f"[deploy-migrate] artifact_sha={args.artifact_sha}")
    print(f"[deploy-migrate] database={redacted_target}")

    revision_before = _current_revision_or_none(database_url)
    print(f"[deploy-migrate] alembic_revision_before={revision_before or '(none / not yet migrated)'}")

    print("[deploy-migrate] running: alembic upgrade head")
    result = subprocess.run(
        ["python", "-m", "alembic", "upgrade", "head"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env={**os.environ},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[deploy-migrate] FAIL: alembic upgrade head exited {result.returncode}", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        print("[deploy-migrate] result=FAIL -- deployment fails closed; application rollout must not proceed.")
        return 1
    print("[deploy-migrate] alembic upgrade head: OK")

    try:
        params = parse_database_url(database_url)
        revision_after = asyncio.run(get_alembic_revision(params))
    except Exception as exc:  # noqa: BLE001
        print(
            f"[deploy-migrate] FAIL: could not positively confirm the post-migration Alembic revision: {exc}. "
            "Migration command reported success but its result cannot be verified -- treating as failure.",
            file=sys.stderr,
        )
        print("[deploy-migrate] result=FAIL -- deployment fails closed; application rollout must not proceed.")
        return 1

    print(f"[deploy-migrate] alembic_revision_after={revision_after}")
    print("[deploy-migrate] result=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
