"""PR24D-L2 (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §32):
static structural assertions on the local Staging/UAT PowerShell installer
scripts and their interaction with compose.yml.

These are pure text/structure checks (no PowerShell runtime required) --
true PowerShell syntax validation happens in CI's own "PowerShell script
validation" job (pwsh is preinstalled on GitHub-hosted ubuntu-latest
runners). Tests here inspect the real script files directly, not
duplicated fixtures, per this repository's own established convention for
deployment/local-staging (see test_pr24d_local_staging_compose.py).
"""

import re
from pathlib import Path

import yaml

DEPLOYMENT_ROOT = Path(__file__).resolve().parents[2] / "deployment" / "local-staging"
LIB_ROOT = DEPLOYMENT_ROOT / "lib"
COMPOSE_PATH = DEPLOYMENT_ROOT / "compose.yml"
GITIGNORE_PATH = Path(__file__).resolve().parents[2] / ".gitignore"

EXPECTED_SCRIPTS = ["install.ps1", "start.ps1", "stop.ps1", "status.ps1", "update.ps1", "uninstall.ps1"]


def _read(name: str) -> str:
    return (DEPLOYMENT_ROOT / name).read_text()


def _common_text() -> str:
    return (LIB_ROOT / "Common.ps1").read_text()


def _all_ps1_texts() -> dict[str, str]:
    texts = {name: _read(name) for name in EXPECTED_SCRIPTS}
    texts["lib/Common.ps1"] = _common_text()
    return texts


def _strip_comments_and_docstrings(text: str) -> str:
    """Removes `<# ... #>` block comments and `#`-prefixed line comments,
    so structural checks below inspect only executable PowerShell code --
    a prose mention inside a docstring/comment (e.g. "never pulls a
    `:latest` image tag") must never trip a check meant to catch actual
    usage."""
    without_blocks = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    lines = []
    for line in without_blocks.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def test_all_expected_l2_scripts_exist():
    for name in EXPECTED_SCRIPTS:
        assert (DEPLOYMENT_ROOT / name).is_file(), f"missing required installer script: {name}"
    assert (LIB_ROOT / "Common.ps1").is_file(), "missing shared helper module lib/Common.ps1"


def test_all_scripts_dot_source_shared_helper():
    for name in EXPECTED_SCRIPTS:
        text = _read(name)
        assert ". (Join-Path $PSScriptRoot 'lib/Common.ps1')" in text, (
            f"{name} must dot-source lib/Common.ps1 via a $PSScriptRoot-relative path"
        )


def test_no_invoke_expression_anywhere():
    for name, text in _all_ps1_texts().items():
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "Invoke-Expression" not in line, f"{name} must not use Invoke-Expression: {line!r}"


def test_stop_script_never_uses_down():
    text = _read("stop.ps1")
    assert "'down'" not in text and '"down"' not in text, "stop.ps1 must use `docker compose stop`, never `down`"
    assert "'stop'" in text, "stop.ps1 must invoke `docker compose stop`"


def test_uninstall_default_path_has_no_down_dash_v():
    text = _read("uninstall.ps1")
    # The only occurrence of a volume-removing flag must be inside the
    # -RemoveData branch, gated by the typed confirmation phrase -- assert
    # both that the guard text appears BEFORE the --volumes call in the
    # file, and that a bare `down -v`-style default-path call is absent.
    assert "down', '--volumes'" in text or 'down", "--volumes"' in text, (
        "uninstall.ps1 must remove volumes only via an explicit --volumes call"
    )
    guard_index = text.find("RemoveData")
    volumes_index = text.find("--volumes")
    assert guard_index != -1 and volumes_index != -1 and guard_index < volumes_index, (
        "the --volumes removal call must be gated behind the -RemoveData parameter"
    )
    assert "confirmationPhrase" in text, "destructive uninstall must require a typed confirmation phrase"


def test_local_staging_runtime_state_is_gitignored():
    gitignore_text = GITIGNORE_PATH.read_text()
    for pattern in (
        "deployment/local-staging/logs/",
        "deployment/local-staging/.install.lock",
        "deployment/local-staging/.install-metadata.json",
    ):
        assert pattern in gitignore_text, f".gitignore must cover {pattern}"


def test_secret_generation_uses_cryptographic_randomness():
    text = _common_text()
    assert "RandomNumberGenerator" in text, "New-UrlSafeSecret must use a cryptographic RNG, not Get-Random"
    assert "Get-Random" not in text, "installer scripts must never use Get-Random for secret material"


def test_secret_generation_produces_url_safe_output():
    text = _common_text()
    # Base64url alphabet substitution (+ -> -, / -> _) and padding removal
    # -- ensures generated POSTGRES_PASSWORD is always safe to interpolate
    # directly into compose.yml's DATABASE_URL connection string.
    assert "TrimEnd('=')" in text
    assert "Replace('+', '-')" in text
    assert "Replace('/', '_')" in text


def test_fresh_env_generation_refuses_to_overwrite_existing_env():
    text = _common_text()
    assert "New-LocalStagingEnvFile must not be called when .env already exists" in text, (
        "the .env generator must refuse to run against an existing installation"
    )


def test_install_only_calls_new_env_file_on_fresh_state():
    text = _read("install.ps1")
    # The env-generation branch must be reached only via a Test-EnvFileExists
    # guard, never unconditionally -- and the top-level else branch (an
    # existing .env) must never call the generator. Searches for the
    # specific "existing .env found" else-branch marker rather than a bare
    # "else {" so nested ternary if/else assignments inside the true
    # branch (e.g. `$suggested = if (...) {...} else {...}`) do not create
    # false positives.
    assert "if (-not (Test-EnvFileExists)) {" in text
    generation_block_start = text.find("if (-not (Test-EnvFileExists)) {")
    new_env_call_index = text.find("New-LocalStagingEnvFile", generation_block_start)
    existing_env_branch_index = text.find("Existing .env found; preserving", generation_block_start)
    assert new_env_call_index != -1, "install.ps1 must call New-LocalStagingEnvFile in the fresh-install branch"
    assert existing_env_branch_index != -1, "install.ps1 must have an existing-.env branch that logs preservation"
    assert new_env_call_index < existing_env_branch_index, (
        "New-LocalStagingEnvFile must be called before the existing-.env branch, i.e. only in the fresh-install branch"
    )
    assert "New-LocalStagingEnvFile" not in text[existing_env_branch_index:], (
        "the existing-.env branch must never call New-LocalStagingEnvFile"
    )


def test_start_script_never_runs_migration():
    text = _read("start.ps1")
    assert "deploy_migrate.py" not in text, "start.ps1 must never run a migration -- that belongs to install.ps1/update.ps1"


def test_install_script_runs_explicit_migration():
    text = _read("install.ps1")
    assert "deploy_migrate.py" in text, "install.ps1 must run the explicit migration step"
    # Must be a one-off `run`, never baked into the long-running backend
    # service's own startup command.
    assert "'run', '--rm'" in text


def test_update_script_runs_explicit_migration_and_requires_acknowledgement():
    text = _read("update.ps1")
    assert "deploy_migrate.py" in text
    assert "AcknowledgeUpdateRisk" in text
    # The acknowledgement check must occur before any docker compose
    # mutation (build/stop/migrate) is invoked.
    ack_index = text.find("if (-not $AcknowledgeUpdateRisk)")
    build_index = text.find("Invoke-DockerCompose -Arguments @('build'")
    assert ack_index != -1 and build_index != -1 and ack_index < build_index


def test_update_script_never_uses_latest_tag():
    code = _strip_comments_and_docstrings(_read("update.ps1"))
    assert ":latest" not in code
    assert re.search(r"pull.{0,20}latest", code, re.IGNORECASE) is None


def test_update_script_never_pulls_or_checks_out_git_refs():
    code = _strip_comments_and_docstrings(_read("update.ps1"))
    assert "git pull" not in code
    assert "git checkout" not in code
    assert "& git" not in code
    # No literal git subprocess invocation of any kind in this script --
    # source acquisition is explicitly out of scope for L2 (module
    # docstring); only Get-CurrentSourceSha (in Common.ps1) shells out to
    # git, and only to read the current HEAD, never to mutate the checkout.
    common_code = _strip_comments_and_docstrings(_common_text())
    assert "git checkout" not in common_code
    assert "git pull" not in common_code
    assert "git rev-parse HEAD" in common_code


def test_uninstall_default_preserves_data():
    text = _read("uninstall.ps1")
    assert "RemoveData" in text
    preserved_index = text.find("Containers removed. PostgreSQL data")
    assert preserved_index != -1, "uninstall.ps1 must report that data was preserved on the default path"


def test_compose_still_has_no_postgres_or_redis_lan_exposure():
    compose = yaml.safe_load(COMPOSE_PATH.read_text())
    services = compose["services"]
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


def test_compose_redis_never_a_wait_gated_dependency_in_scripts():
    # install.ps1/start.ps1/update.ps1 must only ever request health-waits
    # for postgres alone or for backend+frontend -- never a combination
    # that includes redis, which would let a broken Redis container block
    # the installer (the application's own /api/v1/ready contract already
    # treats Redis as non-blocking; the installer must not regress that).
    pattern = re.compile(r"Wait-ComposeServicesHealthy -Services @\(([^)]*)\)")
    for name in ("install.ps1", "start.ps1", "update.ps1"):
        text = _read(name)
        for match in pattern.finditer(text):
            services_literal = match.group(1)
            assert "redis" not in services_literal.lower(), (
                f"{name} must not wait on redis health: {match.group(0)!r}"
            )


def test_compose_backend_worker_count_still_one():
    dockerfile_text = (Path(__file__).resolve().parents[2] / "backend" / "Dockerfile").read_text()
    match = re.search(r'"--workers",\s*"(\d+)"', dockerfile_text)
    assert match and match.group(1) == "1"


def test_production_cookie_secure_default_unchanged():
    config_text = (Path(__file__).resolve().parents[2] / "backend" / "app" / "core" / "config.py").read_text()
    assert "COOKIE_SECURE: bool | None = None" in config_text
    assert 'return self.ENVIRONMENT == "production"' in config_text


def test_no_default_administrator_credentials_in_installer():
    # "ADMIN001" alone is not a credential (it appears only as a
    # placeholder example employee code in an operator prompt, matching
    # app.scripts.bootstrap_admin's own docstring example) -- the actual
    # risk this guards against is a hardcoded default *password*.
    for name, text in _all_ps1_texts().items():
        lowered = text.lower()
        for forbidden in ("admin@12345", "changeme", "password123"):
            assert forbidden not in lowered, f"{name} must not contain a default administrator credential: {forbidden!r}"
        # bootstrap_admin.py is only ever invoked with operator-supplied
        # --employee-code/--email/--full-name; it must never receive a
        # --password argument from these scripts (the CLI accepts none).
        assert "--password" not in text


def test_install_never_passes_password_as_bootstrap_argument():
    text = _read("install.ps1")
    assert "bootstrap_admin" in text
    assert "--password" not in text
    # The bootstrap call's output must not be captured into a variable
    # this script could later log -- it streams straight to the console.
    bootstrap_call = re.search(r"& docker @composeArgs\s*\n\s*\$bootstrapExit = \$LASTEXITCODE", text)
    assert bootstrap_call is not None, "bootstrap_admin invocation must not capture stdout into a loggable variable"
