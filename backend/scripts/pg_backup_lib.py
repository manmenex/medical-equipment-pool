"""Shared logic for PostgreSQL backup/restore/prune tooling (PR24C).

Kept deliberately small and dependency-light (stdlib + asyncpg only) so
backend/scripts/backup_postgres.py, restore_postgres.py, and
prune_backups.py can each stay a thin CLI wrapper around pure,
independently-testable functions -- see
backend/tests/test_pr24c_backup_restore.py. Mirrors two conventions
already established elsewhere in this repository rather than inventing
new ones:

  - DATABASE_URL is never logged/echoed (PR24B Fix Round 2's own
    non-leak principle for connection strings, applied here to
    subprocess invocation too -- see ConnectionParams.as_libpq_env()).
  - The dialect-conditional "postgresql+asyncpg://" -> "postgresql://"
    normalization already used by tests/test_postgres_integration.py's
    and scripts/postgres_ci_gate.py's own _admin_dsn()/_plain_dsn().
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

BACKUP_FILENAME_RE = re.compile(r"^mep-postgres-(?P<environment>[a-z0-9]+)-(?P<timestamp>\d{8}T\d{6}Z)\.dump$")

# docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §11 / §24 /
# OD-PR24-3: the repository's own approved backup retention target.
DEFAULT_RETENTION_DAYS = 30


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def backup_filename(environment: str, created_at: datetime) -> str:
    """`mep-postgres-<environment>-<YYYYMMDDTHHMMSSZ>.dump`.

    Deterministic and timestamped per PR24C §10. `environment` is
    reduced to lowercase letters/digits only -- this is the only
    identifying metadata in the filename itself; everything else
    (baseline SHA, Alembic revision, checksum, ...) lives in the
    sidecar manifest, never a database password, username, or any
    patient-adjacent identifier.
    """
    safe_env = re.sub(r"[^a-z0-9]", "", environment.lower()) or "unknown"
    return f"mep-postgres-{safe_env}-{format_timestamp(created_at)}.dump"


def manifest_filename_for(backup_filename_: str) -> str:
    return f"{backup_filename_}.manifest.json"


def parse_backup_filename(name: str) -> tuple[str, datetime] | None:
    """Inverse of backup_filename(); returns (environment, created_at) or
    None if `name` does not match the expected pattern."""
    match = BACKUP_FILENAME_RE.match(name)
    if not match:
        return None
    created_at = datetime.strptime(match.group("timestamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return match.group("environment"), created_at


def sha256_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclasses.dataclass(frozen=True)
class ConnectionParams:
    host: str
    port: int
    user: str
    password: str
    dbname: str

    def as_libpq_env(self) -> dict[str, str]:
        """PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE, meant to be merged
        into a subprocess's *environment*, never passed as a command-line
        argument -- command-line arguments are visible to other local
        users via `ps`/`/proc`, environment variables passed this way are
        not. This is how backup_postgres.py/restore_postgres.py invoke
        pg_dump/pg_restore/psql without ever putting the password (or
        the full DATABASE_URL) on a command line.
        """
        return {
            "PGHOST": self.host,
            "PGPORT": str(self.port),
            "PGUSER": self.user,
            "PGPASSWORD": self.password,
            "PGDATABASE": self.dbname,
        }

    def redacted(self) -> str:
        """Safe to print/log: no password."""
        return f"{self.user}@{self.host}:{self.port}/{self.dbname}"

    def asyncpg_dsn(self) -> str:
        """A plain `postgresql://` DSN for direct asyncpg.connect() calls
        (in-process, not a subprocess argv -- never `ps`-visible), used
        for the alembic_revision/row-count verification queries rather
        than shelling out to `psql` for them."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"


def parse_database_url(database_url: str) -> ConnectionParams:
    normalized = database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlsplit(normalized)
    if parsed.scheme != "postgresql":
        raise ValueError(f"Unsupported DATABASE_URL scheme {parsed.scheme!r}; expected postgresql(+asyncpg)://...")
    if not parsed.hostname or not parsed.username or parsed.password is None:
        raise ValueError("DATABASE_URL must include a host, username, and password")
    dbname = parsed.path.lstrip("/")
    if not dbname:
        raise ValueError("DATABASE_URL must include a database name")
    return ConnectionParams(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        dbname=dbname,
    )


@dataclasses.dataclass(frozen=True)
class DatabaseIdentity:
    """Identifies a database purely by where it is (host+port+database
    name) -- deliberately excludes credentials, since the same physical
    database can be reached with different users/passwords. Fix Round 1
    (PR #132 independent review): this is the type restore-target safety
    guards compare, and it is always derived from the backup manifest --
    never optionally supplied by the operator -- so the guard cannot be
    silently skipped by omitting a CLI flag."""

    host: str
    port: int
    database_name: str

    def matches(self, other: "DatabaseIdentity") -> bool:
        return (self.host.lower(), self.port, self.database_name) == (
            other.host.lower(),
            other.port,
            other.database_name,
        )

    def redacted(self) -> str:
        """No credentials in a DatabaseIdentity to begin with -- safe to print/log as-is."""
        return f"{self.host}:{self.port}/{self.database_name}"

    @staticmethod
    def from_connection_params(params: "ConnectionParams") -> "DatabaseIdentity":
        return DatabaseIdentity(host=params.host, port=params.port, database_name=params.dbname)

    @staticmethod
    def from_manifest(manifest: "BackupManifest") -> "DatabaseIdentity":
        return DatabaseIdentity(host=manifest.host, port=manifest.port, database_name=manifest.database_name)


def same_database_target(a: ConnectionParams, b: ConnectionParams) -> bool:
    """True if two connection targets point at the same physical
    database (host+port+database name) -- deliberately ignores
    user/password, since the same database can be reached with
    different credentials."""
    return DatabaseIdentity.from_connection_params(a).matches(DatabaseIdentity.from_connection_params(b))


class ProductionRestoreRefused(RuntimeError):
    """Raised when restore tooling refuses to target what looks like Production."""


def guard_restore_target(
    *,
    target: ConnectionParams,
    target_environment: str,
    source_identity: DatabaseIdentity,
) -> None:
    """PR24C §15/§24: restore tooling must refuse a Production target by
    default, with no override flag anywhere in this module. Two
    independent, UNCONDITIONAL checks:

      1. `target_environment` must not be "production" (case-insensitive,
         whitespace-trimmed).
      2. The target must be a physically different database
         (host+port+database name, ignoring credentials) than
         `source_identity` -- restoring "into" the exact source database
         would `--clean` it in place.

    Fix Round 1 (PR #132 independent review, [P1]): `source_identity` is
    a required argument, not an optional one gated on whether the
    operator happened to pass --source-database-url. The backup manifest
    always records the source database's host/port/database name (see
    BackupManifest), so callers must derive `source_identity` from the
    manifest via `DatabaseIdentity.from_manifest()` -- restore-target
    safety must never depend on an operator remembering an optional CLI
    flag. See backend/scripts/restore_postgres.py.

    There is deliberately no `--allow-production-restore` escape hatch
    (PR24C §24's own explicit instruction) -- if this needs to change,
    that is a new, separately-reviewed decision, not a flag to add here.
    """
    if target_environment.strip().lower() == "production":
        raise ProductionRestoreRefused(
            "Refusing to restore into a target explicitly labeled --target-environment production. "
            "Restore rehearsal must target a disposable, non-production database. There is no "
            "override flag for this check -- see backend/scripts/pg_backup_lib.py guard_restore_target()."
        )
    target_identity = DatabaseIdentity.from_connection_params(target)
    if target_identity.matches(source_identity):
        raise ProductionRestoreRefused(
            f"Refusing to restore: target ({target_identity.redacted()}) matches the source database "
            f"recorded in the backup manifest ({source_identity.redacted()}). Restore must target a "
            "separate, disposable database -- never the source database (or Production) as the 'test'."
        )


@dataclasses.dataclass(frozen=True)
class BackupManifest:
    backup_filename: str
    created_at: str  # ISO 8601 UTC, e.g. 2026-08-28T12:00:00+00:00
    environment: str
    baseline_sha: str | None
    alembic_revision: str | None
    database_name: str
    host: str
    port: int
    file_size_bytes: int
    checksum_sha256: str
    tool: str
    tool_version: str

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), indent=2, sort_keys=True) + "\n"

    @staticmethod
    def from_json(text: str) -> "BackupManifest":
        data = json.loads(text)
        return BackupManifest(**data)


def is_eligible_for_pruning(*, created_at: datetime, now: datetime, retention_days: int) -> bool:
    if retention_days <= 0:
        raise ValueError("retention_days must be a positive number of days")
    age_seconds = (now - created_at).total_seconds()
    return age_seconds > retention_days * 86400


def select_prune_candidates(
    backups: list[tuple[Path, datetime]],
    *,
    now: datetime,
    retention_days: int,
) -> list[Path]:
    """Pure retention-cutoff logic (PR24C §9/§31), independently
    testable without touching the filesystem: given (path, created_at)
    pairs, return the paths eligible for deletion.

    Safety invariant: the single newest backup is NEVER eligible, even
    if its own timestamp happens to be past the cutoff (a long gap
    since the last successful backup -- clock skew, an outage, a paused
    schedule -- must never leave zero backups on disk).
    """
    if not backups:
        return []
    newest_path, _ = max(backups, key=lambda item: item[1])
    return [
        path
        for path, created_at in backups
        if path != newest_path and is_eligible_for_pruning(created_at=created_at, now=now, retention_days=retention_days)
    ]


def repo_root() -> Path:
    # backend/scripts/pg_backup_lib.py -> backend/scripts -> backend -> repo root
    return Path(__file__).resolve().parents[2]


def default_backup_dir() -> Path:
    # .gitignore already excludes /backups/ at the repo root for exactly
    # this purpose.
    return repo_root() / "backups" / "postgres"
