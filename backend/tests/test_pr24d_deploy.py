"""PR24D: unit tests for backend/scripts/cd_lib.py,
backend/scripts/deploy_migrate.py, and backend/scripts/staging_smoke_check.py.

Pure-logic / mocked-I/O tests only -- none require a real PostgreSQL
connection, a real container, or real network access. The CD workflow's
own live behavior (`.github/workflows/cd-staging.yml`) is a separate,
manually-triggered proof of the mechanism -- see
docs/runbooks/PR24_STAGING_DEPLOYMENT_RUNBOOK.md's explicit distinction
between this suite (proves the tooling) and a real deployment (proves
operational readiness), matching PR24C's own established discipline.
"""

import sys

import pytest

from scripts import cd_lib, deploy_migrate, staging_smoke_check

# ---------------------------------------------------------------------------
# cd_lib.is_valid_commit_sha / image_tag
# ---------------------------------------------------------------------------

VALID_SHA = "0754c8f3193de5db33645ff6af939d888f748901"


def test_is_valid_commit_sha_accepts_full_lowercase_sha():
    assert cd_lib.is_valid_commit_sha(VALID_SHA) is True


@pytest.mark.parametrize(
    "value",
    [
        VALID_SHA.upper(),  # must be lowercase, matching git's own output
        VALID_SHA[:7],  # short SHA
        "latest",
        "main",
        "claude/medical-equipment-pool-0c7fz0",
        "",
        VALID_SHA + "x",  # 41 chars
        "g" * 40,  # non-hex character
    ],
)
def test_is_valid_commit_sha_rejects_non_full_sha_values(value):
    assert cd_lib.is_valid_commit_sha(value) is False


def test_image_tag_builds_expected_format():
    tag = cd_lib.image_tag("ghcr.io", "manmenex/medical-equipment-pool", "backend", VALID_SHA)
    assert tag == f"ghcr.io/manmenex/medical-equipment-pool-backend:{VALID_SHA}"


def test_image_tag_never_produces_a_mutable_tag():
    tag = cd_lib.image_tag("ghcr.io", "owner/repo", "frontend", VALID_SHA)
    assert "latest" not in tag
    assert tag.endswith(f":{VALID_SHA}")


def test_image_tag_rejects_non_commit_sha():
    with pytest.raises(ValueError):
        cd_lib.image_tag("ghcr.io", "owner/repo", "backend", "latest")


def test_image_tag_rejects_empty_component():
    with pytest.raises(ValueError):
        cd_lib.image_tag("ghcr.io", "owner/repo", "", VALID_SHA)


# ---------------------------------------------------------------------------
# deploy_migrate.py
# ---------------------------------------------------------------------------


def test_deploy_migrate_fails_closed_without_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deploy_migrate.py", "--target-environment", "staging", "--artifact-sha", VALID_SHA],
    )
    assert deploy_migrate.main() == 1
    assert "DATABASE_URL is not set" in capsys.readouterr().err


def test_deploy_migrate_fails_closed_on_invalid_database_url(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "not-a-valid-url")
    monkeypatch.setattr(
        sys,
        "argv",
        ["deploy_migrate.py", "--target-environment", "staging", "--artifact-sha", VALID_SHA],
    )
    assert deploy_migrate.main() == 1
    assert "invalid DATABASE_URL" in capsys.readouterr().err


def test_deploy_migrate_never_echoes_database_url_or_credentials(monkeypatch, capsys):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://mep_user:s3cr3t-password@dbhost:5432/mep_db",
    )
    monkeypatch.setattr(
        deploy_migrate.subprocess,
        "run",
        lambda *a, **k: pytest.fail("subprocess.run must not be reached when DATABASE_URL is unreachable in this unit test"),
    )
    # Force the pre-migration revision lookup to fail fast (no real DB
    # available in this unit test) and short-circuit before subprocess.run
    # by making alembic itself unreachable -- simplest way to assert on
    # stdout without a live database is to check the printed evidence
    # never contains the password, regardless of how far execution gets.
    monkeypatch.setattr(deploy_migrate, "_current_revision_or_none", lambda _url: None)

    def _fake_run(*args, **kwargs):
        class _Result:
            returncode = 1
            stdout = ""
            stderr = "connection refused"

        return _Result()

    monkeypatch.setattr(deploy_migrate.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deploy_migrate.py", "--target-environment", "staging", "--artifact-sha", VALID_SHA],
    )
    deploy_migrate.main()
    output = capsys.readouterr()
    assert "s3cr3t-password" not in output.out
    assert "s3cr3t-password" not in output.err


def test_deploy_migrate_records_target_environment_and_artifact_sha(monkeypatch, capsys):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://mep_user:pw@dbhost:5432/mep_db",
    )
    monkeypatch.setattr(deploy_migrate, "_current_revision_or_none", lambda _url: None)

    def _fake_run(*args, **kwargs):
        class _Result:
            returncode = 1
            stdout = ""
            stderr = "connection refused"

        return _Result()

    monkeypatch.setattr(deploy_migrate.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deploy_migrate.py", "--target-environment", "staging-ci-proof", "--artifact-sha", VALID_SHA],
    )
    deploy_migrate.main()
    out = capsys.readouterr().out
    assert "target_environment=staging-ci-proof" in out
    assert f"artifact_sha={VALID_SHA}" in out


def test_deploy_migrate_fails_closed_when_alembic_command_fails(monkeypatch, capsys):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://mep_user:pw@dbhost:5432/mep_db",
    )
    monkeypatch.setattr(deploy_migrate, "_current_revision_or_none", lambda _url: None)

    def _fake_run(*args, **kwargs):
        class _Result:
            returncode = 1
            stdout = "some alembic output"
            stderr = "boom"

        return _Result()

    monkeypatch.setattr(deploy_migrate.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deploy_migrate.py", "--target-environment", "staging", "--artifact-sha", VALID_SHA],
    )
    assert deploy_migrate.main() == 1
    assert "result=FAIL" in capsys.readouterr().out


def test_deploy_migrate_fails_closed_when_post_migration_revision_unverifiable(monkeypatch, capsys):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://mep_user:pw@dbhost:5432/mep_db",
    )
    monkeypatch.setattr(deploy_migrate, "_current_revision_or_none", lambda _url: None)

    def _fake_run(*args, **kwargs):
        class _Result:
            returncode = 0
            stdout = "alembic upgrade succeeded"
            stderr = ""

        return _Result()

    monkeypatch.setattr(deploy_migrate.subprocess, "run", _fake_run)

    def _raise(*args, **kwargs):
        raise RuntimeError("cannot connect to verify")

    monkeypatch.setattr(deploy_migrate, "get_alembic_revision", lambda _params: _raise())
    monkeypatch.setattr(
        sys,
        "argv",
        ["deploy_migrate.py", "--target-environment", "staging", "--artifact-sha", VALID_SHA],
    )
    assert deploy_migrate.main() == 1
    out = capsys.readouterr()
    assert "result=FAIL" in out.out
    assert "cannot be verified" in out.err


# ---------------------------------------------------------------------------
# staging_smoke_check.py
# ---------------------------------------------------------------------------


def _make_fake_get(responses: dict[str, tuple[int, bytes] | None]):
    def _fake_get(url: str, timeout_seconds: float):
        for key, value in responses.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected URL requested in smoke check: {url}")

    return _fake_get


def test_smoke_check_passes_when_health_and_ready_are_200(monkeypatch):
    monkeypatch.setattr(
        staging_smoke_check,
        "_get",
        _make_fake_get(
            {
                "/api/v1/health": (200, b"ok"),
                "/api/v1/ready": (200, b"ready"),
                "": (200, b"ok"),
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["staging_smoke_check.py", "--base-url", "http://localhost:8000"],
    )
    assert staging_smoke_check.main() == 0


def test_smoke_check_fails_closed_when_ready_is_not_200(monkeypatch, capsys):
    monkeypatch.setattr(
        staging_smoke_check,
        "_get",
        _make_fake_get(
            {
                "/api/v1/health": (200, b"ok"),
                "/api/v1/ready": (503, b"not_ready"),
                "": (200, b"ok"),
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["staging_smoke_check.py", "--base-url", "http://localhost:8000"],
    )
    assert staging_smoke_check.main() == 1
    assert "/api/v1/ready" in capsys.readouterr().err


def test_smoke_check_fails_closed_when_base_url_unreachable(monkeypatch):
    monkeypatch.setattr(staging_smoke_check, "_get", lambda url, timeout_seconds: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["staging_smoke_check.py", "--base-url", "http://localhost:8000"],
    )
    assert staging_smoke_check.main() == 1


def test_smoke_check_verifies_frontend_when_given(monkeypatch):
    monkeypatch.setattr(
        staging_smoke_check,
        "_get",
        _make_fake_get(
            {
                "/api/v1/health": (200, b"ok"),
                "/api/v1/ready": (200, b"ready"),
                "frontend.example": (200, b"x" * 500),
                "": (200, b"ok"),
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "staging_smoke_check.py",
            "--base-url",
            "http://backend.example",
            "--frontend-url",
            "http://frontend.example",
        ],
    )
    assert staging_smoke_check.main() == 0


def test_smoke_check_fails_when_frontend_serves_trivial_body(monkeypatch):
    monkeypatch.setattr(
        staging_smoke_check,
        "_get",
        _make_fake_get(
            {
                "/api/v1/health": (200, b"ok"),
                "/api/v1/ready": (200, b"ready"),
                "frontend.example": (200, b"x"),  # too small
                "": (200, b"ok"),
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "staging_smoke_check.py",
            "--base-url",
            "http://backend.example",
            "--frontend-url",
            "http://frontend.example",
        ],
    )
    assert staging_smoke_check.main() == 1


def test_smoke_check_never_requests_a_write_or_login_endpoint(monkeypatch):
    requested_urls: list[str] = []

    def _fake_get(url: str, timeout_seconds: float):
        requested_urls.append(url)
        return 200, b"ok" * 100

    monkeypatch.setattr(staging_smoke_check, "_get", _fake_get)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "staging_smoke_check.py",
            "--base-url",
            "http://backend.example",
            "--frontend-url",
            "http://frontend.example",
        ],
    )
    staging_smoke_check.main()
    for url in requested_urls:
        assert "login" not in url
        assert "auth" not in url


def test_smoke_check_skips_alembic_check_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        staging_smoke_check,
        "_get",
        _make_fake_get(
            {
                "/api/v1/health": (200, b"ok"),
                "/api/v1/ready": (200, b"ready"),
                "": (200, b"ok"),
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "staging_smoke_check.py",
            "--base-url",
            "http://localhost:8000",
            "--expected-alembic-revision",
            "abc123",
        ],
    )
    assert staging_smoke_check.main() == 0


def test_smoke_check_fails_closed_on_alembic_revision_mismatch(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://mep_user:pw@dbhost:5432/mep_db")
    monkeypatch.setattr(
        staging_smoke_check,
        "_get",
        _make_fake_get(
            {
                "/api/v1/health": (200, b"ok"),
                "/api/v1/ready": (200, b"ready"),
                "": (200, b"ok"),
            }
        ),
    )
    async def _fake_get_alembic_revision(_params):
        return "different_revision"

    monkeypatch.setattr(staging_smoke_check, "get_alembic_revision", _fake_get_alembic_revision)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "staging_smoke_check.py",
            "--base-url",
            "http://localhost:8000",
            "--expected-alembic-revision",
            "expected_revision",
        ],
    )
    assert staging_smoke_check.main() == 1
    assert "does not match expected" in capsys.readouterr().err
