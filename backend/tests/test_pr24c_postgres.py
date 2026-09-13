"""PR24C: real pg_dump/pg_restore round-trip against PostgreSQL.

Proves the backup_postgres.py / restore_postgres.py tooling actually
works end to end: seed a real database, back it up, restore the backup
into a second, disposable scratch database, and verify the restored
data matches. This is CI tooling proof, not a real Staging rehearsal --
see docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md's own explicit
distinction between the two.

Run only this suite:
    POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
        .venv/bin/python -m pytest -q -m postgres

Skips automatically (like tests/test_postgres_integration.py) if
PostgreSQL is unreachable, or if pg_dump/pg_restore are not on PATH.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db.base import Base
from app.models.master_data import Ward
from app.models.user import ROLE_ADMINISTRATOR, Role, User

pytestmark = pytest.mark.postgres

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SCRATCH_DB_NAME = "mep_test_pr24c_restore_target"

POSTGRES_TEST_DATABASE_URL = os.environ.get(
    "POSTGRES_TEST_DATABASE_URL",
    "postgresql+asyncpg://mep_test:mep_test_password@localhost:5432/mep_test_db",
)


def _admin_dsn() -> str:
    plain = POSTGRES_TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    return plain.rsplit("/", 1)[0] + "/postgres"


def _restore_target_url() -> str:
    base = POSTGRES_TEST_DATABASE_URL.rsplit("/", 1)[0]
    return f"{base}/{_SCRATCH_DB_NAME}"


async def _recreate_restore_target_database() -> None:
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB_NAME}"')
        await conn.execute(f'CREATE DATABASE "{_SCRATCH_DB_NAME}"')
    finally:
        await conn.close()


async def _drop_restore_target_database() -> None:
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB_NAME}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def pg_engine():
    engine = create_async_engine(POSTGRES_TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL not reachable/usable at {POSTGRES_TEST_DATABASE_URL}: {exc}")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine):
    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session


def _require_pg_dump_and_pg_restore() -> None:
    if shutil.which("pg_dump") is None or shutil.which("pg_restore") is None:
        pytest.skip("pg_dump/pg_restore not found on PATH")


def _run_script(script_name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_BACKEND_DIR / "scripts" / script_name), *args],
        cwd=str(_BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=120,
    )


async def _seed_representative_data(pg_session: AsyncSession) -> dict[str, int]:
    role = Role(name=ROLE_ADMINISTRATOR, permissions={})
    pg_session.add(role)
    await pg_session.flush()

    user = User(
        employee_code="ADMINISTRATOR001",
        full_name="PR24C Backup Test Admin",
        email="pr24c-backup-test@mep-hospital-test.dev",
        password_hash=hash_password("Password@123"),
        role_id=role.id,
    )
    pg_session.add(user)

    ward = Ward(code="PR24C-W1", name="PR24C Test Ward")
    pg_session.add(ward)

    await pg_session.commit()
    return {"equipment": 0, "wards": 1, "users": 1, "borrow_transactions": 0, "audit_logs": 0}


async def _representative_counts(database_url: str) -> dict[str, int]:
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        return {
            table: await conn.fetchval(f'SELECT COUNT(*) FROM "{table}"')
            for table in ("equipment", "wards", "users", "borrow_transactions", "audit_logs")
        }
    finally:
        await conn.close()


async def test_backup_and_restore_round_trip_matches_source(pg_session, pg_engine, tmp_path):
    _require_pg_dump_and_pg_restore()

    expected_counts = await _seed_representative_data(pg_session)
    source_counts = await _representative_counts(POSTGRES_TEST_DATABASE_URL)
    assert source_counts == expected_counts

    backup_result = _run_script(
        "backup_postgres.py",
        "--database-url",
        POSTGRES_TEST_DATABASE_URL,
        "--environment",
        "citest",
        "--output-dir",
        str(tmp_path),
    )
    assert backup_result.returncode == 0, f"backup_postgres.py failed:\nstdout={backup_result.stdout}\nstderr={backup_result.stderr}"

    dump_files = list(tmp_path.glob("mep-postgres-citest-*.dump"))
    assert len(dump_files) == 1, f"expected exactly one dump file, found {dump_files}"
    manifest_files = list(tmp_path.glob("mep-postgres-citest-*.dump.manifest.json"))
    assert len(manifest_files) == 1

    try:
        await _recreate_restore_target_database()
    except Exception as exc:
        pytest.skip(f"Cannot create restore-target scratch database: {exc}")

    try:
        restore_result = _run_script(
            "restore_postgres.py",
            "--backup-file",
            str(dump_files[0]),
            "--target-database-url",
            _restore_target_url(),
            "--target-environment",
            "citest",
            "--source-database-url",
            POSTGRES_TEST_DATABASE_URL,
        )
        assert restore_result.returncode == 0, (
            f"restore_postgres.py failed:\nstdout={restore_result.stdout}\nstderr={restore_result.stderr}"
        )
        assert "OK" in restore_result.stdout

        restored_counts = await _representative_counts(_restore_target_url())
        assert restored_counts == source_counts
    finally:
        await _drop_restore_target_database()


async def test_restore_refuses_production_target_without_touching_backup(pg_session, pg_engine, tmp_path):
    _require_pg_dump_and_pg_restore()

    await _seed_representative_data(pg_session)

    backup_result = _run_script(
        "backup_postgres.py",
        "--database-url",
        POSTGRES_TEST_DATABASE_URL,
        "--environment",
        "citest",
        "--output-dir",
        str(tmp_path),
    )
    assert backup_result.returncode == 0

    dump_files = list(tmp_path.glob("mep-postgres-citest-*.dump"))
    assert len(dump_files) == 1

    restore_result = _run_script(
        "restore_postgres.py",
        "--backup-file",
        str(dump_files[0]),
        "--target-database-url",
        POSTGRES_TEST_DATABASE_URL,  # deliberately the live source DB
        "--target-environment",
        "production",
    )
    assert restore_result.returncode != 0
    assert "Refusing to restore" in restore_result.stderr

    # The source database must be completely untouched by the refused attempt.
    counts_after = await _representative_counts(POSTGRES_TEST_DATABASE_URL)
    assert counts_after["wards"] == 1
    assert counts_after["users"] == 1
