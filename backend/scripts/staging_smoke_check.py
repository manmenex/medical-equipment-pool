#!/usr/bin/env python3
"""PR24D: minimal post-deploy smoke verification against a deployed
Staging (or any) environment.

docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §18/§25: after an
artifact is deployed and migrated, verify the instance is actually
reachable and ready *before* declaring the deployment successful --
never a destructive business-workflow transaction (login/PDF-export-style
checks already exist as CI's own Docker-smoke-test job; this script is
deliberately narrower and safe to run repeatedly against a live,
shared Staging environment).

Checks performed, in order (stdlib `urllib.request` only -- no extra
runtime dependency required to run this against a real deployed
environment):

    1. HTTPS/HTTP reachable: the base URL responds to a GET request.
    2. GET {base_url}/api/v1/health -- liveness, HTTP 200 expected
       (docs/design/... §15A: always 200, this is the process-alive
       check, not the readiness gate).
    3. GET {base_url}/api/v1/ready -- fail-closed readiness, HTTP 200
       required (§15A: a non-2xx here means a required dependency,
       i.e. PostgreSQL, is unreachable -- this is the actual go/no-go
       signal, not step 2).
    4. Frontend serves (only if --frontend-url is given, since backend
       and frontend may be deployed/verified as separate artifacts):
       GET {frontend_url}/ returns HTTP 200 with a non-trivial body.
    5. Current Alembic revision matches --expected-alembic-revision
       (only if both that flag and a reachable DATABASE_URL are
       given -- this is an optional defense-in-depth check, reusing
       backend/scripts/pg_backup_verify.get_alembic_revision, never
       required to run this script).

Usage:
    python scripts/staging_smoke_check.py \\
        --base-url https://staging.example.com \\
        [--frontend-url https://staging.example.com] \\
        [--expected-alembic-revision <revision>] \\
        [--timeout-seconds 10]

Never performs a login, a write, a PDF export, or any other
business-workflow transaction against the target environment -- read-only
HTTP GETs to fixed, unauthenticated diagnostic endpoints only. Never logs
DATABASE_URL or credentials; only a redacted host/port/database identity
is printed if the optional Alembic check runs.
"""

import argparse
import asyncio
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.pg_backup_lib import parse_database_url  # noqa: E402
from scripts.pg_backup_verify import get_alembic_revision  # noqa: E402

DEFAULT_TIMEOUT_SECONDS = 10


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="The deployed backend's base URL (e.g. https://staging.example.com).")
    parser.add_argument(
        "--frontend-url",
        default=None,
        help="Optional: the deployed frontend's base URL, if served separately from --base-url. Skipped if omitted.",
    )
    parser.add_argument(
        "--expected-alembic-revision",
        default=None,
        help="Optional: the Alembic revision this deployment is expected to be at. Checked only if DATABASE_URL "
        "is also set in the environment; skipped otherwise.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args()


def _get(url: str, timeout_seconds: float) -> tuple[int, bytes] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() if exc.fp else b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def main() -> int:
    args = _parse_args()
    failures: list[str] = []

    base_url = args.base_url.rstrip("/")

    print(f"[smoke] checking reachability of {base_url}")
    reachable = _get(base_url, args.timeout_seconds)
    if reachable is None:
        failures.append(f"base URL {base_url} was not reachable at all")
    else:
        print(f"[smoke] base URL reachable, HTTP {reachable[0]}")

    print(f"[smoke] GET {base_url}/api/v1/health (liveness)")
    health = _get(f"{base_url}/api/v1/health", args.timeout_seconds)
    if health is None or health[0] != 200:
        failures.append(f"/api/v1/health did not return HTTP 200 (got {health[0] if health else 'no response'})")
    else:
        print("[smoke] /api/v1/health: HTTP 200 OK")

    print(f"[smoke] GET {base_url}/api/v1/ready (fail-closed readiness)")
    ready = _get(f"{base_url}/api/v1/ready", args.timeout_seconds)
    if ready is None or ready[0] != 200:
        failures.append(f"/api/v1/ready did not return HTTP 200 (got {ready[0] if ready else 'no response'}) -- a required dependency is unreachable")
    else:
        print("[smoke] /api/v1/ready: HTTP 200 OK")

    if args.frontend_url:
        frontend_url = args.frontend_url.rstrip("/")
        print(f"[smoke] GET {frontend_url}/ (frontend serves)")
        frontend = _get(f"{frontend_url}/", args.timeout_seconds)
        if frontend is None or frontend[0] != 200 or len(frontend[1]) < 100:
            failures.append("frontend did not serve a non-trivial HTTP 200 response")
        else:
            print(f"[smoke] frontend served HTTP 200, {len(frontend[1])} bytes")
    else:
        print("[smoke] --frontend-url not given, skipping frontend serve check")

    database_url = os.environ.get("DATABASE_URL")
    if args.expected_alembic_revision and database_url:
        try:
            params = parse_database_url(database_url)
            print(f"[smoke] checking Alembic revision against {params.redacted()}")
            actual_revision = asyncio.run(get_alembic_revision(params))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"could not read the deployed Alembic revision: {exc}")
        else:
            if actual_revision != args.expected_alembic_revision:
                failures.append(
                    f"deployed Alembic revision {actual_revision!r} does not match expected "
                    f"{args.expected_alembic_revision!r}"
                )
            else:
                print(f"[smoke] Alembic revision verified: {actual_revision}")
    else:
        print("[smoke] --expected-alembic-revision and/or DATABASE_URL not given, skipping Alembic check")

    if failures:
        print("[smoke] FAIL:", file=sys.stderr)
        for failure in failures:
            print(f"[smoke]   - {failure}", file=sys.stderr)
        return 1

    print("[smoke] result=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
