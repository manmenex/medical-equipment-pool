"""PR24D-L2 (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §32):
static structural assertions on the local Staging/UAT PowerShell installer
scripts and their interaction with compose.yml.

Scope note (Fix Round 1): these are *structural* checks only. The
orchestration behavior they used to approximate -- build-before-migrate,
fail-closed bootstrap, stop-verification, lock coverage, state
classification -- is now covered by executed behavior tests in
deployment/local-staging/tests/Invoke-InstallerTests.ps1, which mock the
single native-command seam and call the real functions. What remains here
are the invariants best expressed as "this text must/must not appear
anywhere in the shipped scripts", which a behavior test cannot prove
(e.g. "no script anywhere uses Invoke-Expression").

True PowerShell syntax validation and the behavior tests both run in CI's
"PowerShell script validation" job (pwsh is preinstalled on GitHub-hosted
ubuntu-latest runners).
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ROOT = REPO_ROOT / "deployment" / "local-staging"
LIB_ROOT = DEPLOYMENT_ROOT / "lib"
TESTS_ROOT = DEPLOYMENT_ROOT / "tests"
COMPOSE_PATH = DEPLOYMENT_ROOT / "compose.yml"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

ENTRY_SCRIPTS = ["install.ps1", "start.ps1", "stop.ps1", "status.ps1", "update.ps1", "uninstall.ps1"]
LIB_MODULES = ["Common.ps1", "Operations.ps1"]
# Every script that changes deployment state must hold the shared mutation
# lock. status.ps1 is read-only and deliberately does not.
MUTATING_SCRIPTS = ["install.ps1", "start.ps1", "stop.ps1", "update.ps1", "uninstall.ps1"]


def _read(name: str) -> str:
    return (DEPLOYMENT_ROOT / name).read_text()


def _lib(name: str) -> str:
    return (LIB_ROOT / name).read_text()


def _all_ps1_paths() -> dict[str, Path]:
    paths = {name: DEPLOYMENT_ROOT / name for name in ENTRY_SCRIPTS}
    for name in LIB_MODULES:
        paths[f"lib/{name}"] = LIB_ROOT / name
    return paths


def _all_ps1_texts() -> dict[str, str]:
    return {name: path.read_text() for name, path in _all_ps1_paths().items()}


def _strip_comments_and_docstrings(text: str) -> str:
    """Removes `<# ... #>` block comments and `#`-prefixed line comments,
    so structural checks below inspect only executable PowerShell code --
    a prose mention inside a docstring/comment (e.g. "never pulls a
    `:latest` image tag") must never trip a check meant to catch actual
    usage."""
    without_blocks = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    lines = []
    for line in without_blocks.splitlines():
        if line.strip().startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _ps_function_body(code: str, function_name: str) -> str:
    """Returns the source of a single top-level PowerShell function, ending
    at the next top-level `function` declaration (or end of file). Slicing a
    fixed number of characters instead would bleed into the following
    function and make a per-function assertion silently wrong."""
    start = code.find(f"function {function_name} ")
    assert start != -1, f"function {function_name} not found"
    next_fn = code.find("\nfunction ", start + 1)
    return code[start:] if next_fn == -1 else code[start:next_fn]


# ---------------------------------------------------------------------------
# File layout
# ---------------------------------------------------------------------------


def test_all_expected_l2_files_exist():
    for name, path in _all_ps1_paths().items():
        assert path.is_file(), f"missing required installer file: {name}"
    assert (TESTS_ROOT / "Invoke-InstallerTests.ps1").is_file(), (
        "the PowerShell orchestration behavior tests must ship with the scripts they cover"
    )


def test_entry_scripts_dot_source_both_shared_modules():
    for name in ENTRY_SCRIPTS:
        text = _read(name)
        assert ". (Join-Path $PSScriptRoot 'lib/Common.ps1')" in text, (
            f"{name} must dot-source lib/Common.ps1 via a $PSScriptRoot-relative path"
        )
        if name != "status.ps1":
            # status.ps1 is read-only and needs only the primitives.
            assert ". (Join-Path $PSScriptRoot 'lib/Operations.ps1')" in text, (
                f"{name} must dot-source lib/Operations.ps1"
            )


# ---------------------------------------------------------------------------
# Command execution discipline (Fix Round 1, review §21/§33)
# ---------------------------------------------------------------------------


def test_no_invoke_expression_anywhere():
    for name, text in _all_ps1_texts().items():
        code = _strip_comments_and_docstrings(text)
        assert "Invoke-Expression" not in code, f"{name} must not use Invoke-Expression"


def test_native_command_execution_is_centralized():
    """Only Invoke-MepCommand may invoke a native binary directly, so exit
    codes are checked in exactly one place instead of being re-implemented
    (or forgotten) per call site."""
    common_code = _strip_comments_and_docstrings(_lib("Common.ps1"))
    assert "function Invoke-MepCommand" in common_code

    for name, text in _all_ps1_texts().items():
        if name == "lib/Common.ps1":
            continue
        code = _strip_comments_and_docstrings(text)
        assert "& docker" not in code, f"{name} must call docker through Invoke-MepCommand, not directly"
        assert "& git" not in code, f"{name} must call git through Invoke-MepCommand, not directly"
        assert "$LASTEXITCODE" not in code, (
            f"{name} must not handle $LASTEXITCODE itself -- Invoke-MepCommand owns exit-code checking"
        )


def test_no_native_command_output_silently_discarded():
    """`| Out-Null` after a native command hides both output and failure.
    Every Compose call must flow through Invoke-DockerCompose, whose
    result the caller inspects."""
    for name, text in _all_ps1_texts().items():
        code = _strip_comments_and_docstrings(text)
        assert not re.search(r"Invoke-DockerCompose[^\n]*\|\s*Out-Null", code), (
            f"{name} must not pipe a Compose result to Out-Null without checking its exit code"
        )


def test_docker_info_and_version_probes_allow_nonzero():
    """The Docker availability probes legitimately expect a non-zero exit
    when Docker is down; they must say so explicitly rather than throwing."""
    common_code = _strip_comments_and_docstrings(_lib("Common.ps1"))
    for probe in ("docker-info", "compose-version"):
        idx = common_code.find(f"-Phase '{probe}'")
        assert idx != -1, f"expected a {probe} probe"
        window = common_code[max(0, idx - 300):idx]
        assert "-AllowNonZeroExit" in window, f"the {probe} probe must pass -AllowNonZeroExit"


# ---------------------------------------------------------------------------
# Mutation lock (Fix Round 1, P1-D / review §11-§15)
# ---------------------------------------------------------------------------


def test_mutation_lock_is_atomic_named_mutex_not_test_path():
    common_code = _strip_comments_and_docstrings(_lib("Common.ps1"))
    assert "System.Threading.Mutex" in common_code, (
        "the mutation lock must be an atomic named mutex, not a check-then-create file"
    )
    assert "function Enter-MepMutationLock" in common_code
    assert "function Exit-MepMutationLock" in common_code
    # The previous TOCTOU pattern (Test-Path on a lock file, then writing
    # it) must be gone entirely.
    assert "LockFilePath" not in common_code, "the non-atomic lock-file implementation must not remain"


def test_every_mutating_script_takes_the_lock_and_releases_it_in_finally():
    for name in MUTATING_SCRIPTS:
        code = _strip_comments_and_docstrings(_read(name))
        assert "Enter-MepMutationLock" in code, f"{name} mutates deployment state and must take the mutation lock"
        assert "Exit-MepMutationLock" in code, f"{name} must release the mutation lock"
        finally_index = code.find("finally {")
        exit_index = code.find("Exit-MepMutationLock", finally_index if finally_index != -1 else 0)
        assert finally_index != -1 and exit_index > finally_index, (
            f"{name} must release the mutation lock from a finally block so no failure path leaks it"
        )


def test_status_script_is_read_only_and_does_not_hold_the_lock():
    code = _strip_comments_and_docstrings(_read("status.ps1"))
    # It may *probe* the lock to report BUSY, but must release immediately
    # and must not wrap its reporting in a held lock.
    assert "Invoke-MepStop" not in code and "Invoke-MepInstall" not in code, (
        "status.ps1 must not perform any mutating operation"
    )
    probe_index = code.find("Enter-MepMutationLock")
    if probe_index != -1:
        release_index = code.find("Exit-MepMutationLock", probe_index)
        assert release_index != -1 and release_index - probe_index < 200, (
            "status.ps1 may only probe the lock and must release it immediately"
        )


def test_all_scripts_share_one_lock_namespace():
    common_code = _strip_comments_and_docstrings(_lib("Common.ps1"))
    assert "$Script:MutationLockName" in common_code
    # No script may define its own competing lock name.
    for name, text in _all_ps1_texts().items():
        if name == "lib/Common.ps1":
            continue
        assert "MutationLockName =" not in text, f"{name} must not define a second lock namespace"


# ---------------------------------------------------------------------------
# State inspection (Fix Round 1, P2 / review §16-§19)
# ---------------------------------------------------------------------------


def test_every_compose_ps_invocation_passes_all():
    """Plain `docker compose ps` hides stopped/exited containers, which is
    what made a fully stopped installation classifiable as healthy."""
    for name, text in _all_ps1_texts().items():
        code = _strip_comments_and_docstrings(text)
        for match in re.finditer(r"@\(\s*'ps'[^)]*\)", code):
            assert "'--all'" in match.group(0), (
                f"{name} must pass --all to docker compose ps (saw: {match.group(0)!r})"
            )


def test_state_classification_validates_the_expected_service_set():
    common_code = _strip_comments_and_docstrings(_lib("Common.ps1"))
    assert "$Script:ExpectedServices" in common_code
    for service in ("postgres", "redis", "backend", "frontend"):
        assert f"'{service}'" in common_code, f"the expected-service set must include {service}"
    assert "function Get-InstallationState" in common_code
    for state in ("FRESH", "EXISTING_HEALTHY", "EXISTING_STOPPED", "PARTIAL", "AMBIGUOUS"):
        assert state in common_code, f"state classification must be able to return {state}"


def test_completed_install_metadata_is_a_distinct_signal():
    """Metadata alone must not imply a healthy install, and it must record
    completion explicitly so a failed bootstrap leaves no success marker."""
    common_code = _strip_comments_and_docstrings(_lib("Common.ps1"))
    assert "InstallCompleted" in common_code
    assert "function Test-MepInstallCompleted" in common_code


# ---------------------------------------------------------------------------
# Image freshness and migration ordering (Fix Round 1, P1-A)
# ---------------------------------------------------------------------------


def test_operations_module_builds_images_explicitly():
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    assert "function Invoke-MepBuildImages" in ops_code
    assert "'build', 'backend', 'frontend'" in ops_code, "the build step must build both application images explicitly"


def test_migration_runs_with_no_build_and_a_distinct_container_name():
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    migrate_index = ops_code.find("deploy_migrate.py")
    assert migrate_index != -1
    window = ops_code[max(0, migrate_index - 500):migrate_index]
    assert "'--no-build'" in window, (
        "the migration one-off container must pass --no-build so it uses the image just built, never an ambiguous rebuild"
    )
    assert "mep-local-staging-migrate" in window, (
        "the migration container must not reuse the backend service's fixed container_name"
    )


def test_install_and_update_build_before_migrating():
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    for func in ("Invoke-MepInstall", "Invoke-MepUpdate"):
        body = _ps_function_body(ops_code, func)
        build_index = body.find("Invoke-MepBuildImages")
        migrate_index = body.find("Invoke-MepMigration")
        assert build_index != -1, f"{func} must build images"
        assert migrate_index != -1, f"{func} must run the explicit migration"
        assert build_index < migrate_index, f"{func} must build before migrating"


def test_start_script_never_migrates_or_builds():
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    body = _ps_function_body(ops_code, "Invoke-MepStart")
    assert "Invoke-MepMigration" not in body, "start must never run a migration"
    assert "Invoke-MepBuildImages" not in body, "start must never rebuild images"


# ---------------------------------------------------------------------------
# Update safety (Fix Round 1, P1-C)
# ---------------------------------------------------------------------------


def test_update_requires_acknowledgement_before_any_mutation():
    code = _strip_comments_and_docstrings(_read("update.ps1"))
    ack_index = code.find("if (-not $AcknowledgeUpdateRisk)")
    invoke_index = code.find("Invoke-MepUpdate")
    assert ack_index != -1 and invoke_index != -1 and ack_index < invoke_index, (
        "update.ps1 must refuse before invoking any update work when the risk acknowledgement is absent"
    )


def test_stop_verification_checks_both_exit_code_and_running_state():
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    body = _ps_function_body(ops_code, "Stop-MepApplication")
    assert "$result.ExitCode -ne 0" in body, "the stop step must inspect its exit code"
    assert "Test-MepServiceRunning" in body, (
        "the stop step must verify the backend is actually stopped, not trust the exit code alone"
    )


def test_update_script_never_uses_latest_tag_or_git_mutation():
    code = _strip_comments_and_docstrings(_read("update.ps1"))
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    for body in (code, ops_code):
        assert ":latest" not in body
        assert "git pull" not in body
        assert "git checkout" not in body
    common_code = _strip_comments_and_docstrings(_lib("Common.ps1"))
    assert "git checkout" not in common_code
    assert "git pull" not in common_code
    assert "'rev-parse', 'HEAD'" in common_code, "only a read-only git rev-parse is permitted"


# ---------------------------------------------------------------------------
# Uninstall safety
# ---------------------------------------------------------------------------


def test_uninstall_default_path_preserves_data():
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    body = _ps_function_body(ops_code, "Invoke-MepUninstall")
    remove_data_index = body.find("RemoveData")
    volumes_index = body.find("'--volumes'")
    assert volumes_index != -1, "destructive removal must go through an explicit --volumes call"
    assert remove_data_index != -1 and remove_data_index < volumes_index, (
        "the --volumes removal must be gated behind -RemoveData"
    )


def test_destructive_uninstall_verifies_configuration_was_actually_deleted():
    """Same class as P1-C: a swallowed removal failure would report
    "data removed" while .env -- and the generated secrets in it -- is
    still on disk."""
    body = _ps_function_body(
        _strip_comments_and_docstrings(_lib("Operations.ps1")), "Invoke-MepUninstall"
    )
    assert "Test-Path -LiteralPath $leftover" in body, (
        "destructive uninstall must verify removal rather than trust -ErrorAction SilentlyContinue"
    )
    verify_index = body.find("Test-Path -LiteralPath $leftover")
    completed_index = body.find("uninstall.ps1 completed (data removed")
    assert completed_index != -1 and verify_index < completed_index, (
        "the removal must be verified before uninstall reports success"
    )


def test_uninstall_requires_typed_confirmation_phrase():
    code = _strip_comments_and_docstrings(_read("uninstall.ps1"))
    assert "confirmationPhrase" in code
    assert "DELETE LOCAL STAGING DATA" in code
    confirm_index = code.find("confirmationPhrase")
    invoke_index = code.find("Invoke-MepUninstall")
    assert confirm_index < invoke_index, "the typed confirmation must be obtained before any removal runs"


# ---------------------------------------------------------------------------
# Secrets and credentials
# ---------------------------------------------------------------------------


def test_secret_generation_uses_cryptographic_randomness():
    text = _lib("Common.ps1")
    assert "RandomNumberGenerator" in text, "New-UrlSafeSecret must use a cryptographic RNG, not Get-Random"
    assert "Get-Random" not in text, "installer scripts must never use Get-Random for secret material"


def test_secret_generation_produces_url_safe_output():
    text = _lib("Common.ps1")
    assert "TrimEnd('=')" in text
    assert "Replace('+', '-')" in text
    assert "Replace('/', '_')" in text


def test_fresh_env_generation_refuses_to_overwrite_existing_env():
    text = _lib("Common.ps1")
    assert "New-LocalStagingEnvFile must not be called when .env already exists" in text


def test_env_generation_is_guarded_by_the_absence_of_an_env_file():
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    guard_index = ops_code.find("if (-not (Test-EnvFileExists))")
    gen_index = ops_code.find("New-LocalStagingEnvFile")
    assert guard_index != -1 and gen_index != -1 and guard_index < gen_index, (
        "config generation must sit inside a Test-EnvFileExists guard so reinstall never regenerates secrets"
    )


def test_no_default_administrator_credentials_in_installer():
    # "ADMIN001" alone is not a credential (it appears only as a
    # placeholder example employee code in an operator prompt, matching
    # app.scripts.bootstrap_admin's own docstring example) -- the actual
    # risk this guards against is a hardcoded default *password*.
    for name, text in _all_ps1_texts().items():
        lowered = text.lower()
        for forbidden in ("admin@12345", "changeme", "password123"):
            assert forbidden not in lowered, f"{name} must not contain a default administrator credential: {forbidden!r}"
        assert "--password" not in text, f"{name} must never pass a password argument"


def test_bootstrap_output_is_never_written_to_the_installer_log():
    """The bootstrap CLI prints a one-time password to stdout. Its output
    may be shown on the console and inspected to classify a failure, but
    must never reach Write-InstallLog."""
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    body = _ps_function_body(ops_code, "Invoke-MepAdminBootstrap")
    assert "Write-Host $line" in body, "bootstrap output is shown on the console"
    assert not re.search(r"Write-InstallLog[^\n]*\$result\.Output", body), (
        "bootstrap output must never be passed to Write-InstallLog"
    )
    assert not re.search(r"Write-InstallLog[^\n]*\$joined", body), (
        "bootstrap output must never be passed to Write-InstallLog"
    )


def test_admin_bootstrap_rejects_blank_required_fields():
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    body = _ps_function_body(ops_code, "Invoke-MepAdminBootstrap")
    assert "IsNullOrWhiteSpace" in body, "blank administrator fields must be rejected explicitly"


# ---------------------------------------------------------------------------
# PR24D-L1 invariants preserved
# ---------------------------------------------------------------------------


def test_compose_still_has_no_postgres_or_redis_lan_exposure():
    services = yaml.safe_load(COMPOSE_PATH.read_text())["services"]
    assert "ports" not in services["postgres"]
    assert "ports" not in services["redis"]
    assert "ports" not in services["backend"]


def test_compose_backend_fixed_container_name_preserved():
    compose = yaml.safe_load(COMPOSE_PATH.read_text())
    assert compose["services"]["backend"].get("container_name") == "mep-local-staging-backend"


def test_compose_no_deploy_replicas_and_no_scale_in_scripts():
    compose = yaml.safe_load(COMPOSE_PATH.read_text())
    assert "deploy" not in compose["services"].get("backend", {})
    for name, text in _all_ps1_texts().items():
        code = _strip_comments_and_docstrings(text)
        assert "--scale" not in code, f"{name} must never invoke `docker compose ... --scale`"


def test_redis_is_never_part_of_a_wait_call():
    """The application's readiness contract treats Redis as non-blocking;
    the installer must not reintroduce it as a startup gate."""
    ops_code = _strip_comments_and_docstrings(_lib("Operations.ps1"))
    for match in re.finditer(r"@\([^)]*'--wait'[^)]*\)", ops_code):
        assert "redis" not in match.group(0).lower(), (
            f"redis must never appear in a --wait call (saw: {match.group(0)!r})"
        )
    body = _ps_function_body(ops_code, "Start-MepRedis")
    assert "'up', '-d', 'redis'" in body and "--wait" not in body, (
        "Redis must be started fire-and-forget, never health-gated"
    )


def test_compose_backend_worker_count_still_one():
    dockerfile_text = (REPO_ROOT / "backend" / "Dockerfile").read_text()
    match = re.search(r'"--workers",\s*"(\d+)"', dockerfile_text)
    assert match and match.group(1) == "1"


def test_production_cookie_secure_default_unchanged():
    config_text = (REPO_ROOT / "backend" / "app" / "core" / "config.py").read_text()
    assert "COOKIE_SECURE: bool | None = None" in config_text
    assert 'return self.ENVIRONMENT == "production"' in config_text


def test_local_staging_runtime_state_is_gitignored():
    gitignore_text = GITIGNORE_PATH.read_text()
    for pattern in (
        "deployment/local-staging/logs/",
        "deployment/local-staging/.install-metadata.json",
    ):
        assert pattern in gitignore_text, f".gitignore must cover {pattern}"
