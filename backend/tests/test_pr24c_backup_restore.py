"""PR24C: unit tests for backend/scripts/pg_backup_lib.py.

These are pure-logic tests (filename generation/parsing, checksums,
retention cutoff, DSN parsing, and the production-restore guard) --
none require a real PostgreSQL connection. The real pg_dump/pg_restore
round trip lives in test_pr24c_postgres.py (pytest.mark.postgres).
"""

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import restore_postgres
from scripts.pg_backup_lib import (
    BackupManifest,
    ConnectionParams,
    DatabaseIdentity,
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


def _source_identity(host="source-db", port=5432, database_name="mep_db"):
    return DatabaseIdentity(host=host, port=port, database_name=database_name)


def test_guard_restore_target_refuses_production_label():
    with pytest.raises(ProductionRestoreRefused):
        guard_restore_target(target=_target(), target_environment="production", source_identity=_source_identity())


@pytest.mark.parametrize("label", ["Production", "PRODUCTION", "  production  "])
def test_guard_restore_target_refuses_production_label_case_and_whitespace_insensitive(label):
    with pytest.raises(ProductionRestoreRefused):
        guard_restore_target(target=_target(), target_environment=label, source_identity=_source_identity())


def test_guard_restore_target_allows_non_production_label():
    guard_restore_target(
        target=_target(), target_environment="staging", source_identity=_source_identity()
    )  # must not raise


def test_guard_restore_target_refuses_same_database_as_source():
    source_identity = _source_identity(host="prod-host", database_name="mep_db")
    identical_target = ConnectionParams(host="prod-host", port=5432, user="other_user", password="pw2", dbname="mep_db")
    with pytest.raises(ProductionRestoreRefused):
        guard_restore_target(target=identical_target, target_environment="staging", source_identity=source_identity)


def test_guard_restore_target_allows_distinct_target_from_source():
    source_identity = _source_identity(host="prod-host", database_name="mep_db")
    guard_restore_target(target=_target(), target_environment="staging", source_identity=source_identity)  # must not raise


# --- Fix Round 1 (PR #132 independent review, [P1]) -------------------------
#
# Same-source restore protection must be derived from the backup manifest
# and enforced UNCONDITIONALLY -- it must not depend on the operator
# optionally supplying --source-database-url. These tests exercise
# guard_restore_target() directly with a manifest-derived DatabaseIdentity
# and no ConnectionParams "source" object at all, proving the guard has no
# code path that skips this check.


def test_guard_restore_target_refuses_same_database_without_any_source_url_supplied():
    # No --source-database-url anywhere in this call -- source_identity
    # (as restore_postgres.py always derives it from the manifest) is the
    # only thing driving the refusal.
    source_identity = _source_identity(host="source-db", port=5432, database_name="mep_db")
    target = ConnectionParams(host="source-db", port=5432, user="mep_user", password="pw", dbname="mep_db")
    with pytest.raises(ProductionRestoreRefused):
        guard_restore_target(target=target, target_environment="staging", source_identity=source_identity)


def test_guard_restore_target_refuses_same_database_different_credentials():
    # Different username/password than the manifest's source -- identity
    # comparison must ignore credentials entirely.
    source_identity = _source_identity(host="source-db", port=5432, database_name="mep_db")
    target = ConnectionParams(host="source-db", port=5432, user="different_user", password="different_password", dbname="mep_db")
    with pytest.raises(ProductionRestoreRefused):
        guard_restore_target(target=target, target_environment="staging", source_identity=source_identity)


def test_guard_restore_target_refuses_same_database_omitted_target_port():
    # Manifest records the resolved default port (5432); target URL omits
    # the port explicitly -- parse_database_url() already materializes it
    # to 5432, so the omitted port must not bypass the guard.
    source_identity = _source_identity(host="source-db", port=5432, database_name="mep_db")
    target = parse_database_url("postgresql+asyncpg://user:pass@source-db/mep_db")
    assert target.port == 5432
    with pytest.raises(ProductionRestoreRefused):
        guard_restore_target(target=target, target_environment="staging", source_identity=source_identity)


def test_guard_restore_target_allows_same_host_different_database():
    source_identity = _source_identity(host="source-db", port=5432, database_name="mep_db")
    target = ConnectionParams(host="source-db", port=5432, user="mep_user", password="pw", dbname="mep_restore")
    guard_restore_target(target=target, target_environment="staging", source_identity=source_identity)  # must not raise


def test_guard_restore_target_allows_different_host_same_database():
    source_identity = _source_identity(host="source-db", port=5432, database_name="mep_db")
    target = ConnectionParams(host="restore-db", port=5432, user="mep_user", password="pw", dbname="mep_db")
    guard_restore_target(target=target, target_environment="staging", source_identity=source_identity)  # must not raise


def test_guard_restore_target_force_non_empty_flag_is_not_part_of_this_guard():
    # guard_restore_target() has no --force-non-empty-target concept at all
    # -- that guard lives entirely in restore_postgres.py's separate
    # target-emptiness check, downstream of this one. Proves the two
    # guards are structurally independent: nothing this function accepts
    # can bypass the same-source/production checks.
    import inspect

    assert "force" not in inspect.signature(guard_restore_target).parameters


# --- DatabaseIdentity ---------------------------------------------------


def test_database_identity_from_manifest_uses_manifest_fields():
    manifest = BackupManifest(
        backup_filename="mep-postgres-staging-20260828T120000Z.dump",
        created_at="2026-08-28T12:00:00+00:00",
        environment="staging",
        baseline_sha="abc123",
        alembic_revision="0024_something",
        database_name="mep_db",
        host="source-db",
        port=5432,
        file_size_bytes=1234,
        checksum_sha256="deadbeef",
        tool="pg_dump",
        tool_version="pg_dump (PostgreSQL) 16.4",
    )
    identity = DatabaseIdentity.from_manifest(manifest)
    assert identity == DatabaseIdentity(host="source-db", port=5432, database_name="mep_db")


def test_database_identity_from_connection_params_ignores_credentials():
    params = ConnectionParams(host="dbhost", port=5432, user="mep_user", password="s3cr3t", dbname="mep_db")
    identity = DatabaseIdentity.from_connection_params(params)
    assert identity == DatabaseIdentity(host="dbhost", port=5432, database_name="mep_db")


def test_database_identity_matches_is_case_insensitive_on_host():
    a = DatabaseIdentity(host="DBHOST", port=5432, database_name="mep_db")
    b = DatabaseIdentity(host="dbhost", port=5432, database_name="mep_db")
    assert a.matches(b) is True


def test_database_identity_redacted_contains_no_credentials():
    # DatabaseIdentity never carries a username/password at all -- this
    # just documents that its str form is safe to print/log.
    identity = DatabaseIdentity(host="dbhost", port=5432, database_name="mep_db")
    assert identity.redacted() == "dbhost:5432/mep_db"


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


# ---------------------------------------------------------------------------
# restore_postgres.py CLI-level regressions (Fix Round 1, PR #132)
#
# These invoke the real script's main() in-process (no subprocess), with
# target_database_is_empty/subprocess.run monkeypatched to raise if ever
# reached -- proving the same-source guard fires strictly before any
# database connection or destructive action, exactly as it must whether
# or not --source-database-url is supplied.
# ---------------------------------------------------------------------------


def _write_backup_and_manifest(tmp_path, *, host="source-db", port=5432, database_name="mep_db", environment="staging"):
    backup_path = tmp_path / "mep-postgres-staging-20260828T120000Z.dump"
    backup_path.write_bytes(b"fake dump bytes for restore-guard regression tests")
    manifest = BackupManifest(
        backup_filename=backup_path.name,
        created_at="2026-08-28T12:00:00+00:00",
        environment=environment,
        baseline_sha="d4a40349f62d76d129dcc6f1feea3e7e8fc8f28d",
        alembic_revision="0024_something",
        database_name=database_name,
        host=host,
        port=port,
        file_size_bytes=backup_path.stat().st_size,
        checksum_sha256=sha256_checksum(backup_path),
        tool="pg_dump",
        tool_version="pg_dump (PostgreSQL) 16.4",
    )
    manifest_path = backup_path.with_name(manifest_filename_for(backup_path.name))
    manifest_path.write_text(manifest.to_json())
    return backup_path


def _fail_if_reached(*args, **kwargs):
    raise AssertionError("must not be reached: the same-source guard must refuse before any DB/subprocess call")


def test_restore_refuses_same_database_as_manifest_source_without_source_url_flag(tmp_path, monkeypatch, capsys):
    # Reproduces the exact defect from independent review: no
    # --source-database-url is passed at all, yet the target resolves to
    # the same host/port/database the manifest says the backup came
    # from (with different credentials). Must fail closed on this head,
    # and specifically via the same-source guard -- not some other
    # exception path that also happens to exit non-zero (the pre-fix
    # code path with no --source-database-url would have skipped this
    # guard entirely and proceeded to target_database_is_empty(), whose
    # failure alone must not be mistaken for the guard firing).
    backup_path = _write_backup_and_manifest(tmp_path, host="source-db", port=5432, database_name="mep_db")
    monkeypatch.setattr(restore_postgres, "target_database_is_empty", _fail_if_reached)
    monkeypatch.setattr(restore_postgres.subprocess, "run", _fail_if_reached)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restore_postgres.py",
            "--backup-file",
            str(backup_path),
            "--target-database-url",
            "postgresql+asyncpg://other_user:other_password@source-db:5432/mep_db",
            "--target-environment",
            "staging",
        ],
    )
    assert restore_postgres.main() == 1
    stderr = capsys.readouterr().err
    assert "matches the source database recorded in the backup manifest" in stderr
    assert "must not be reached" not in stderr


def test_restore_allows_distinct_target_without_source_url_flag(tmp_path, monkeypatch, capsys):
    # Control case: a target that is genuinely distinct from the
    # manifest's recorded source must not be refused by the same-source
    # guard -- execution must reach the target-emptiness check (which
    # this test makes fail with a distinctive marker, since a real
    # PostgreSQL connection isn't available here). Proves the guard is
    # not overbroad: it doesn't refuse every restore, only same-source
    # ones.
    backup_path = _write_backup_and_manifest(tmp_path, host="source-db", port=5432, database_name="mep_db")

    async def _raise_marker_error(_conn_params):
        raise RuntimeError("MARKER: reached target emptiness check")

    monkeypatch.setattr(restore_postgres, "target_database_is_empty", _raise_marker_error)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restore_postgres.py",
            "--backup-file",
            str(backup_path),
            "--target-database-url",
            "postgresql+asyncpg://mep_user:pw@restore-host:5432/mep_restore_rehearsal",
            "--target-environment",
            "staging",
        ],
    )
    assert restore_postgres.main() == 1
    # The guard did not refuse the distinct target -- execution reached
    # (and failed inside) target_database_is_empty(), not the guard.
    assert "MARKER: reached target emptiness check" in capsys.readouterr().err


def test_restore_fails_closed_when_source_url_disagrees_with_manifest(tmp_path, monkeypatch, capsys):
    # --source-database-url is supplied, but points at a different
    # database than the manifest's recorded provenance -- must refuse
    # before any live source connection is attempted (never silently
    # compare row counts against the wrong database).
    backup_path = _write_backup_and_manifest(tmp_path, host="source-db", port=5432, database_name="mep_db")
    monkeypatch.setattr(restore_postgres, "target_database_is_empty", _fail_if_reached)
    monkeypatch.setattr(restore_postgres.subprocess, "run", _fail_if_reached)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restore_postgres.py",
            "--backup-file",
            str(backup_path),
            "--target-database-url",
            "postgresql+asyncpg://mep_user:pw@restore-host:5432/mep_restore_rehearsal",
            "--target-environment",
            "staging",
            "--source-database-url",
            "postgresql+asyncpg://mep_user:pw@other-db:5432/mep_db",
        ],
    )
    assert restore_postgres.main() == 1
    stderr = capsys.readouterr().err
    assert "does not match the source database recorded in the backup manifest" in stderr
    assert "must not be reached" not in stderr


def test_restore_force_non_empty_target_does_not_bypass_same_source_guard(tmp_path, monkeypatch, capsys):
    # --force-non-empty-target must only ever bypass the target-emptiness
    # check, never the Production/same-source guards.
    backup_path = _write_backup_and_manifest(tmp_path, host="source-db", port=5432, database_name="mep_db")
    monkeypatch.setattr(restore_postgres, "target_database_is_empty", _fail_if_reached)
    monkeypatch.setattr(restore_postgres.subprocess, "run", _fail_if_reached)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restore_postgres.py",
            "--backup-file",
            str(backup_path),
            "--target-database-url",
            "postgresql+asyncpg://other_user:other_password@source-db:5432/mep_db",
            "--target-environment",
            "staging",
            "--force-non-empty-target",
        ],
    )
    assert restore_postgres.main() == 1
    stderr = capsys.readouterr().err
    assert "matches the source database recorded in the backup manifest" in stderr
    assert "must not be reached" not in stderr


def test_restore_force_non_empty_target_does_not_bypass_production_guard(tmp_path, monkeypatch, capsys):
    backup_path = _write_backup_and_manifest(tmp_path, host="source-db", port=5432, database_name="mep_db")
    monkeypatch.setattr(restore_postgres, "target_database_is_empty", _fail_if_reached)
    monkeypatch.setattr(restore_postgres.subprocess, "run", _fail_if_reached)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restore_postgres.py",
            "--backup-file",
            str(backup_path),
            "--target-database-url",
            "postgresql+asyncpg://mep_user:pw@restore-host:5432/mep_restore_rehearsal",
            "--target-environment",
            "production",
            "--force-non-empty-target",
        ],
    )
    assert restore_postgres.main() == 1
    stderr = capsys.readouterr().err
    assert "explicitly labeled --target-environment production" in stderr
    assert "must not be reached" not in stderr
