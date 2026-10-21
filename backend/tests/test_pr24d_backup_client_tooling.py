"""PR24D fix: the backend image must actually be able to run PR24C's
backup/restore engine.

deployment/local-staging/lib/Backup.ps1 executes
`compose run --rm --no-deps backend python scripts/backup_postgres.py`, and
that script shells out to the `pg_dump` binary (restore_postgres.py shells
out to `pg_restore`). docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md section 2
already states both as a prerequisite -- "on PATH, matching (or compatible
with) the target PostgreSQL server's major version" -- but nothing verified
that the prerequisite held in the container PR24D-L3 chose to run them in.
It did not: the first real local-staging backup failed instantly with
`FileNotFoundError: [Errno 2] No such file or directory: 'pg_dump'`, which
also made `.\\update.ps1` unusable, because its mandatory pre-update backup
gate cannot be satisfied without a working backup.

backend-postgres-tests already runs a real pg_dump/pg_restore round-trip
(tests/test_pr24c_postgres.py) and even forbids it from skipping -- but on
the RUNNER's PATH, never inside the image. These assertions are static; the
executed proof is the `backend-backup-tooling-smoke-test` CI job, which
builds the image, runs the binaries inside it, and takes a real backup
against a real PostgreSQL 16 server.
"""

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DOCKERFILE = _REPO_ROOT / "backend" / "Dockerfile"
LOCAL_STAGING_COMPOSE = _REPO_ROOT / "deployment" / "local-staging" / "compose.yml"
ROOT_COMPOSE = _REPO_ROOT / "docker-compose.yml"
CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
BACKUP_PS1 = _REPO_ROOT / "deployment" / "local-staging" / "lib" / "Backup.ps1"

_CLIENT_PACKAGE_RE = re.compile(r"\bpostgresql-client-(\d+)\b")
_SERVER_IMAGE_RE = re.compile(r"postgres:(\d+)-")


def _dockerfile_text() -> str:
    return BACKEND_DOCKERFILE.read_text()


def _dockerfile_instructions() -> list[str]:
    """Dockerfile lines with comments and blank lines removed, so an
    assertion can never be satisfied by prose in a comment."""
    return [
        line
        for line in _dockerfile_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _installed_client_major() -> int:
    majors = {int(m) for m in _CLIENT_PACKAGE_RE.findall("\n".join(_dockerfile_instructions()))}
    assert len(majors) == 1, (
        "backend/Dockerfile must install exactly one postgresql-client-<major> "
        f"package; found {sorted(majors)}"
    )
    return majors.pop()


def test_backend_image_installs_a_postgresql_client():
    """The defect itself: libpq-dev is the client library's headers, for
    building psycopg. It ships no pg_dump."""
    instructions = "\n".join(_dockerfile_instructions())
    assert "libpq-dev" in instructions, "psycopg still needs the libpq headers"
    assert _CLIENT_PACKAGE_RE.search(instructions), (
        "backend/Dockerfile installs no postgresql-client-<major> package, so the "
        "image has no pg_dump/pg_restore binary -- PR24C's backup and restore "
        "engine cannot run inside it, and .\\update.ps1's mandatory pre-update "
        "backup gate can never be satisfied."
    )


def test_client_package_is_version_pinned_not_the_debian_metapackage():
    """`postgresql-client` unversioned resolves to 15 on Debian bookworm,
    and pg_dump 15 refuses a version 16 server outright. A client that is
    present but too old fails in the same place a missing one does."""
    instructions = "\n".join(_dockerfile_instructions())
    assert not re.search(r"\bpostgresql-client\b(?!-\d)", instructions), (
        "backend/Dockerfile must install a MAJOR-VERSIONED postgresql-client-<n>, "
        "not the unversioned Debian metapackage"
    )


def test_client_major_matches_every_pinned_postgres_server():
    """Bumping the server image without bumping the client must fail here,
    not at the operator's next backup."""
    client_major = _installed_client_major()
    for compose_path in (LOCAL_STAGING_COMPOSE, ROOT_COMPOSE):
        compose = yaml.safe_load(compose_path.read_text())
        image = compose["services"]["postgres"]["image"]
        match = _SERVER_IMAGE_RE.match(image)
        assert match, f"{compose_path.name} pins an unrecognised postgres image: {image}"
        server_major = int(match.group(1))
        assert client_major == server_major, (
            f"backend/Dockerfile installs postgresql-client-{client_major} but "
            f"{compose_path.name} pins postgres {server_major}. pg_dump refuses a "
            "server newer than itself."
        )


def test_client_is_installed_before_the_image_drops_to_a_non_root_user():
    """apt-get cannot install anything after USER appuser."""
    instructions = _dockerfile_instructions()
    client_line = next(i for i, line in enumerate(instructions) if _CLIENT_PACKAGE_RE.search(line))
    user_line = next(i for i, line in enumerate(instructions) if line.strip().startswith("USER "))
    assert client_line < user_line, (
        "the PostgreSQL client must be installed while the build is still root"
    )


def test_backup_still_runs_inside_the_backend_service():
    """The reason the backend image needs the client at all. If the engine
    is ever moved to a purpose-built image, this assertion should fail so the
    Dockerfile's rationale is revisited rather than left stale."""
    text = BACKUP_PS1.read_text()
    assert "'backend'," in text and "scripts/backup_postgres.py" in text, (
        "Backup.ps1 no longer invokes PR24C's engine inside the `backend` service; "
        "revisit why backend/Dockerfile carries the PostgreSQL client"
    )


_SMOKE_JOB = "backend-docker-smoke-test"


def _smoke_job() -> dict:
    """The executed proof lives in the job that already builds and runs the
    production backend image against a real PostgreSQL 16, rather than in a
    second job that would rebuild the same image and add a ninth required
    check for no extra coverage."""
    jobs = yaml.safe_load(CI_WORKFLOW.read_text())["jobs"]
    assert _SMOKE_JOB in jobs, f"CI no longer defines {_SMOKE_JOB}"
    return jobs[_SMOKE_JOB]


def _smoke_job_steps() -> str:
    return "\n".join(str(step.get("run", "")) for step in _smoke_job()["steps"])


def test_ci_runs_the_client_binaries_inside_the_built_image():
    """A static assertion cannot prove a binary exists in a built image."""
    steps = _smoke_job_steps()
    assert "docker build -t mep-backend:ci" in steps, "the job must build the image it tests"
    assert "command -v pg_dump" in steps and "command -v pg_restore" in steps, (
        "CI must prove both binaries are on PATH INSIDE the image -- "
        "backend-postgres-tests only ever proved it on the runner's own PATH"
    )
    assert '"$tool" --version' in steps, (
        "CI must assert the client's major version, not merely its presence: "
        "pg_dump refuses a server newer than itself"
    )
    # As it appears in the workflow's own grep pattern, parentheses escaped.
    assert rf"PostgreSQL\) {_installed_client_major()}" in steps, (
        "the major version CI asserts must be the one backend/Dockerfile installs"
    )


def test_ci_takes_a_real_backup_with_the_engine_inside_the_image():
    steps = _smoke_job_steps()
    assert "scripts/backup_postgres.py" in steps, (
        "presence of a binary is not proof the backup path works; CI must run "
        "PR24C's engine inside the image"
    )
    assert _smoke_job()["services"]["postgres"]["image"].startswith("postgres:16-"), (
        "the real backup must run against the same server major version the "
        "deployment pins"
    )


def test_ci_backup_step_runs_after_migration_and_seed():
    """Dumping an empty database would prove far less, and
    backup_postgres.py fails closed unless alembic_version holds exactly one
    row -- so the ordering is load-bearing, not cosmetic."""
    names = [str(step.get("name", "")) for step in _smoke_job()["steps"]]
    migrate = next(i for i, n in enumerate(names) if "Apply migrations" in n)
    seed = next(i for i, n in enumerate(names) if "Seed minimal data" in n)
    backup = next(i for i, n in enumerate(names) if "Take a real backup" in n)
    assert migrate < backup and seed < backup


def test_ci_asserts_the_reported_artifact_line_and_manifest():
    """`Resolve-MepProducedBackup` binds the produced artifact's identity by
    parsing PR24C's `[backup] OK: <path>` line and fails closed if it cannot.
    CI should catch a change to that contract before the operator does."""
    steps = _smoke_job_steps()
    assert "[backup] OK:" in steps
    assert ".manifest.json" in steps
    assert "checksum_sha256" in steps
    assert ".partial" in steps, "a leftover partial dump must fail the job"
