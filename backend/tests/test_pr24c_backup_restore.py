"""PR24C: unit tests for backend/scripts/pg_backup_lib.py.

These are pure-logic tests (filename generation/parsing, checksums,
retention cutoff, DSN parsing, and the production-restore guard) --
none require a real PostgreSQL connection. The real pg_dump/pg_restore
round trip lives in test_pr24c_postgres.py (pytest.mark.postgres).
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.pg_backup_lib import (
    BackupManifest,
    ConnectionParams,
    ProductionRestoreRefused,
    backup_filename,
    guard_restore_target,
    is_eligible_for_pruning,
    manifest_filename_for,
    parse_backup_filename,
    parse_database_url,
    same_database_target,
    select_prune_candidates,
    sha256_checksum,
)


def _dt(year=2026, month=8, day=28, hour=12, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Filename generation / parsing
# ---------------------------------------------------------------------------


def test_backup_filename_deterministic_pattern():
    name = backup_filename("production", _dt())
    assert name == "mep-postgres-production-20260828T120000Z.dump"


def test_backup_filename_sanitizes_environment():
    name = backup_filename("Staging/UAT!", _dt())
    assert name == "mep-postgres-staginguat-20260828T120000Z.dump"


def test_backup_filename_never_contains_secrets():
    # Filename must be reconstructable purely from environment + timestamp
    # -- no way to accidentally interpolate a password/username into it.
    name = backup_filename("production", _dt())
    assert "mep_user" not in name
    assert "password" not in name.lower()


def test_manifest_filename_for_appends_suffix():
    assert manifest_filename_for("mep-postgres-production-20260828T120000Z.dump") == (
        "mep-postgres-production-20260828T120000Z.dump.manifest.json"
    )


def test_parse_backup_filename_round_trips():
    name = backup_filename("staging", _dt(2026, 1, 2, 3, 4, 5))
    parsed = parse_backup_filename(name)
    assert parsed == ("staging", _dt(2026, 1, 2, 3, 4, 5))


@pytest.mark.parametrize(
    "name",
    [
        "not-a-backup.dump",
        "mep-postgres-production-20260828T120000Z.dump.manifest.json",
        "mep-postgres-production-bad-timestamp.dump",
        "",
    ],
)
def test_parse_backup_filename_rejects_non_matching_names(name):
    assert parse_backup_filename(name) is None


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------


def test_sha256_checksum_matches_hashlib(tmp_path):
    content = b"some backup bytes" * 1000
    path = tmp_path / "sample.dump"
    path.write_bytes(content)
    assert sha256_checksum(path) == hashlib.sha256(content).hexdigest()


def test_sha256_checksum_changes_with_content(tmp_path):
    path_a = tmp_path / "a.dump"
    path_b = tmp_path / "b.dump"
    path_a.write_bytes(b"content a")
    path_b.write_bytes(b"content b")
    assert sha256_checksum(path_a) != sha256_checksum(path_b)


# ---------------------------------------------------------------------------
# Retention / pruning
# ---------------------------------------------------------------------------


def test_is_eligible_for_pruning_boundary():
    now = _dt()
    exactly_30_days_old = now - timedelta(days=30)
    just_over_30_days_old = now - timedelta(days=30, seconds=1)
    assert is_eligible_for_pruning(created_at=exactly_30_days_old, now=now, retention_days=30) is False
    assert is_eligible_for_pruning(created_at=just_over_30_days_old, now=now, retention_days=30) is True


def test_is_eligible_for_pruning_rejects_non_positive_retention():
    with pytest.raises(ValueError):
        is_eligible_for_pruning(created_at=_dt(), now=_dt(), retention_days=0)


def test_select_prune_candidates_deletes_only_old_backups():
    now = _dt()
    old = Path("mep-postgres-production-20260101T000000Z.dump")
    recent = Path("mep-postgres-production-20260827T000000Z.dump")
    backups = [(old, now - timedelta(days=60)), (recent, now - timedelta(days=1))]
    assert select_prune_candidates(backups, now=now, retention_days=30) == [old]


def test_select_prune_candidates_never_deletes_the_newest_backup():
    # Every backup is older than retention (e.g. the schedule was paused
    # for months) -- the newest one must still survive so the directory
    # is never left with zero backups.
    now = _dt()
    older = Path("mep-postgres-production-20250101T000000Z.dump")
    newest = Path("mep-postgres-production-20250601T000000Z.dump")
    backups = [(older, now - timedelta(days=400)), (newest, now - timedelta(days=200))]
    candidates = select_prune_candidates(backups, now=now, retention_days=30)
    assert candidates == [older]
    assert newest not in candidates


def test_select_prune_candidates_empty_input():
    assert select_prune_candidates([], now=_dt(), retention_days=30) == []


def test_select_prune_candidates_single_backup_never_deleted_even_if_old():
    now = _dt()
    only = Path("mep-postgres-production-20240101T000000Z.dump")
    assert select_prune_candidates([(only, now - timedelta(days=900))], now=now, retention_days=30) == []


# ---------------------------------------------------------------------------
# DATABASE_URL parsing / redaction
# ---------------------------------------------------------------------------


def test_parse_database_url_extracts_components():
    conn = parse_database_url("postgresql+asyncpg://mep_user:s3cr3t@dbhost:5433/mep_db")
    assert conn == ConnectionParams(host="dbhost", port=5433, user="mep_user", password="s3cr3t", dbname="mep_db")


def test_parse_database_url_defaults_port():
    conn = parse_database_url("postgresql+asyncpg://mep_user:s3cr3t@dbhost/mep_db")
    assert conn.port == 5432


@pytest.mark.parametrize(
    "url",
    [
        "mysql://user:pass@host/db",
        "postgresql+asyncpg://host/db",  # no credentials
        "postgresql+asyncpg://user:pass@host/",  # no database name
    ],
)
def test_parse_database_url_rejects_malformed_urls(url):
    with pytest.raises(ValueError):
        parse_database_url(url)


def test_connection_params_redacted_never_includes_password():
    conn = ConnectionParams(host="dbhost", port=5432, user="mep_user", password="s3cr3t-password", dbname="mep_db")
    redacted = conn.redacted()
    assert "s3cr3t-password" not in redacted
    assert "dbhost" in redacted
    assert "mep_user" in redacted


def test_connection_params_as_libpq_env_carries_password_only_via_env_dict():
    conn = ConnectionParams(host="dbhost", port=5432, user="mep_user", password="s3cr3t-password", dbname="mep_db")
    env = conn.as_libpq_env()
    assert env == {
        "PGHOST": "dbhost",
        "PGPORT": "5432",
        "PGUSER": "mep_user",
        "PGPASSWORD": "s3cr3t-password",
        "PGDATABASE": "mep_db",
    }


def test_same_database_target_ignores_credentials():
    a = ConnectionParams(host="dbhost", port=5432, user="alice", password="pw1", dbname="mep_db")
    b = ConnectionParams(host="DBHOST", port=5432, user="bob", password="pw2", dbname="mep_db")
    assert same_database_target(a, b) is True


def test_same_database_target_false_for_different_database():
    a = ConnectionParams(host="dbhost", port=5432, user="alice", password="pw1", dbname="mep_db")
    b = ConnectionParams(host="dbhost", port=5432, user="alice", password="pw1", dbname="mep_restore_rehearsal")
    assert same_database_target(a, b) is False


# ---------------------------------------------------------------------------
# Production-restore guard
# ---------------------------------------------------------------------------


def _target(dbname="mep_restore_rehearsal", host="restore-host"):
    return ConnectionParams(host=host, port=5432, user="mep_user", password="pw", dbname=dbname)


def test_guard_restore_target_refuses_production_label():
    with pytest.raises(ProductionRestoreRefused):
        guard_restore_target(target=_target(), target_environment="production")


@pytest.mark.parametrize("label", ["Production", "PRODUCTION", "  production  "])
def test_guard_restore_target_refuses_production_label_case_and_whitespace_insensitive(label):
    with pytest.raises(ProductionRestoreRefused):
        guard_restore_target(target=_target(), target_environment=label)


def test_guard_restore_target_allows_non_production_label():
    guard_restore_target(target=_target(), target_environment="staging")  # must not raise


def test_guard_restore_target_refuses_same_database_as_source():
    source = ConnectionParams(host="prod-host", port=5432, user="mep_user", password="pw", dbname="mep_db")
    identical_target = ConnectionParams(host="prod-host", port=5432, user="other_user", password="pw2", dbname="mep_db")
    with pytest.raises(ProductionRestoreRefused):
        guard_restore_target(target=identical_target, target_environment="staging", source=source)


def test_guard_restore_target_allows_distinct_target_from_source():
    source = ConnectionParams(host="prod-host", port=5432, user="mep_user", password="pw", dbname="mep_db")
    guard_restore_target(target=_target(), target_environment="staging", source=source)  # must not raise


def test_guard_restore_target_without_source_only_checks_environment_label():
    # No --source-database-url given: only the environment-label guard applies.
    guard_restore_target(target=_target(dbname="mep_db", host="prod-host"), target_environment="staging")


# ---------------------------------------------------------------------------
# Manifest serialization
# ---------------------------------------------------------------------------


def test_backup_manifest_round_trips_through_json():
    manifest = BackupManifest(
        backup_filename="mep-postgres-production-20260828T120000Z.dump",
        created_at="2026-08-28T12:00:00+00:00",
        environment="production",
        baseline_sha="abc123",
        alembic_revision="0024_something",
        database_name="mep_db",
        host="dbhost",
        port=5432,
        file_size_bytes=1234,
        checksum_sha256="deadbeef",
        tool="pg_dump",
        tool_version="pg_dump (PostgreSQL) 16.4",
    )
    round_tripped = BackupManifest.from_json(manifest.to_json())
    assert round_tripped == manifest


def test_backup_manifest_json_never_contains_a_password_field():
    manifest = BackupManifest(
        backup_filename="mep-postgres-production-20260828T120000Z.dump",
        created_at="2026-08-28T12:00:00+00:00",
        environment="production",
        baseline_sha=None,
        alembic_revision="0024_something",
        database_name="mep_db",
        host="dbhost",
        port=5432,
        file_size_bytes=1234,
        checksum_sha256="deadbeef",
        tool="pg_dump",
        tool_version="pg_dump (PostgreSQL) 16.4",
    )
    data = json.loads(manifest.to_json())
    assert "password" not in {key.lower() for key in data}
    assert "user" not in {key.lower() for key in data}
