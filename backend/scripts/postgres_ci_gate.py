"""Fail-closed CI gate for tests/test_postgres_integration.py.

That suite's fixtures call pytest.skip() whenever PostgreSQL is
unreachable/unusable (pg_engine) or a scratch database cannot be created
(_recreate_scratch_database, used by every migration round-trip test) --
by design, so the suite stays "always safe to run" locally, per its own
module docstring. The same behavior means `pytest -m postgres` can exit 0
in CI while PostgreSQL is actually broken (wrong credentials, wrong
database, missing CREATEDB privilege): every affected test just reports
skipped instead of failed.

This module provides two independent commands that close that gap:

  preflight        Proves, before pytest ever runs, that
                    POSTGRES_TEST_DATABASE_URL can connect, authenticate,
                    query the configured database, and hold scratch-
                    database create/drop privilege. Does not use
                    pg_isready: pg_isready only proves the server process
                    accepts TCP connections, not that these credentials
                    can authenticate, reach the configured database, or
                    create/drop a database.

  assert-no-skips  Parses a `pytest --junitxml` report from the
                    postgres-marked run and fails if any test was skipped
                    or errored -- every pytest.skip() in that suite
                    signals unusable infrastructure, never an intentional
                    exclusion, so a skip here must fail CI.

Usage:
    python scripts/postgres_ci_gate.py preflight
    python -m pytest -q -m postgres --junitxml=postgres-results.xml
    python scripts/postgres_ci_gate.py assert-no-skips postgres-results.xml
"""

import argparse
import asyncio
import os
import sys
import uuid
import xml.etree.ElementTree as ET

import asyncpg

DEFAULT_POSTGRES_TEST_DATABASE_URL = "postgresql+asyncpg://mep_test:mep_test_password@localhost:5432/mep_test_db"


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _admin_dsn(url: str) -> str:
    # Mirrors tests/test_postgres_integration.py's own _admin_dsn(): swap to
    # the server's "postgres" maintenance database so CREATE DATABASE / DROP
    # DATABASE privilege can be checked independently of whatever database
    # POSTGRES_TEST_DATABASE_URL itself points at.
    return _plain_dsn(url).rsplit("/", 1)[0] + "/postgres"


async def _check_connect_and_query(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        result = await conn.fetchval("SELECT 1")
        if result != 1:
            raise RuntimeError(f"unexpected result from SELECT 1: {result!r}")
    finally:
        await conn.close()


async def _check_scratch_database_privilege(admin_dsn: str) -> None:
    # Exercises the exact CREATE DATABASE / DROP DATABASE privilege that
    # tests/test_postgres_integration.py's _recreate_scratch_database() /
    # _drop_scratch_database() helpers depend on for every migration
    # round-trip test in that suite.
    probe_name = f"mep_ci_privilege_probe_{uuid.uuid4().hex[:12]}"
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{probe_name}"')
        await conn.execute(f'CREATE DATABASE "{probe_name}"')
        await conn.execute(f'DROP DATABASE IF EXISTS "{probe_name}"')
    finally:
        await conn.close()


async def _preflight(dsn_url: str) -> int:
    dsn = _plain_dsn(dsn_url)
    admin_dsn = _admin_dsn(dsn_url)

    try:
        await _check_connect_and_query(dsn)
    except Exception as exc:
        print(f"[postgres-ci-gate] FAIL: cannot connect/authenticate/query at {dsn}: {exc}", file=sys.stderr)
        return 1
    print(f"[postgres-ci-gate] OK: connected, authenticated, and queried {dsn}")

    try:
        await _check_scratch_database_privilege(admin_dsn)
    except Exception as exc:
        print(
            f"[postgres-ci-gate] FAIL: cannot create/drop a scratch database via {admin_dsn} "
            f"(required by tests/test_postgres_integration.py's migration round-trip tests): {exc}",
            file=sys.stderr,
        )
        return 1
    print(f"[postgres-ci-gate] OK: scratch-database create/drop privilege confirmed via {admin_dsn}")
    return 0


def _assert_no_skips(junit_xml_path: str) -> int:
    tree = ET.parse(junit_xml_path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        print(f"[postgres-ci-gate] FAIL: no <testsuite> found in {junit_xml_path}", file=sys.stderr)
        return 1

    total_tests = sum(int(s.attrib.get("tests", 0)) for s in suites)
    total_skipped = sum(int(s.attrib.get("skipped", 0)) for s in suites)
    total_errors = sum(int(s.attrib.get("errors", 0)) for s in suites)

    if total_tests == 0:
        print(f"[postgres-ci-gate] FAIL: zero postgres-marked tests were collected/run in {junit_xml_path}", file=sys.stderr)
        return 1

    if total_skipped:
        skipped_names = [
            f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
            for s in suites
            for case in s.iter("testcase")
            if case.find("skipped") is not None
        ]
        print(
            f"[postgres-ci-gate] FAIL: {total_skipped} of {total_tests} postgres-marked tests were skipped: "
            f"{skipped_names}. Every pytest.skip() in tests/test_postgres_integration.py signals unusable "
            f"PostgreSQL infrastructure, not an intentional exclusion -- this must fail CI, not pass it.",
            file=sys.stderr,
        )
        return 1

    if total_errors:
        print(f"[postgres-ci-gate] FAIL: {total_errors} collection/setup errors in {junit_xml_path}", file=sys.stderr)
        return 1

    print(f"[postgres-ci-gate] OK: all {total_tests} postgres-marked tests ran, zero skips, zero errors")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser(
        "preflight",
        help="Prove POSTGRES_TEST_DATABASE_URL can connect, authenticate, query, and hold scratch-database privilege",
    )
    preflight.add_argument(
        "--database-url",
        default=None,
        help="Defaults to $POSTGRES_TEST_DATABASE_URL, falling back to the same default the test suite uses",
    )

    assert_no_skips = sub.add_parser(
        "assert-no-skips",
        help="Fail if the given pytest JUnit XML report contains any skipped or errored postgres-marked test",
    )
    assert_no_skips.add_argument("junit_xml_path")

    args = parser.parse_args()

    if args.command == "preflight":
        dsn_url = args.database_url or os.environ.get(
            "POSTGRES_TEST_DATABASE_URL", DEFAULT_POSTGRES_TEST_DATABASE_URL
        )
        return asyncio.run(_preflight(dsn_url))

    return _assert_no_skips(args.junit_xml_path)


if __name__ == "__main__":
    sys.exit(main())
