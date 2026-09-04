# PR24D-L2 (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §32):
# the install/update/start/stop/uninstall orchestration sequences.
#
# These live in functions rather than in the entry scripts' top-level
# bodies for one specific reason: tests/Invoke-InstallerTests.ps1 replaces
# the single command seam (Invoke-MepCommand, defined in Common.ps1) with a
# recording mock and then calls these exact functions -- so the ordering
# and fail-closed rules below are covered by real behavior tests, not by a
# structural grep over a script that could drift from them.
#
# Requires lib/Common.ps1 to be dot-sourced first.

Set-StrictMode -Version Latest

class MepOperationFailure : System.Exception {
    MepOperationFailure([string]$message) : base($message) {}
}

function New-MepFailure {
    param([Parameter(Mandatory)] [string]$Message)
    return [MepOperationFailure]::new($Message)
}

# ---------------------------------------------------------------------------
# Building (Fix Round 1, P1-A/P1-B: image freshness is a hard precondition)
# ---------------------------------------------------------------------------

function Invoke-MepBuildImages {
    <#
    .SYNOPSIS
    Explicitly builds the backend and frontend images from the currently
    checked-out source, before any migration or application start.

    .DESCRIPTION
    Without this, `docker compose run backend ...` can silently reuse a
    stale cached image -- running a migration from older code, starting an
    older application, and reporting success against the wrong revision.
    That is especially reachable after an uninstall, which removes
    containers but leaves images behind.

    Fails closed: a non-zero build exit stops the whole operation before
    migration runs, so a failed build can never be followed by a migration
    or by success metadata.
    #>
    Write-Host 'Building application images from the current source...'
    $result = Invoke-DockerCompose -Arguments @('build', 'backend', 'frontend') -AllowNonZeroExit -Phase 'build'
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure 'Image build failed. Migration was NOT run and the application was NOT started. Fix the build error above and rerun.')
    }
    Write-InstallLog -Phase 'build' -Message 'backend and frontend images built from current source.'
}

# ---------------------------------------------------------------------------
# Migration (reuses backend/scripts/deploy_migrate.py unchanged)
# ---------------------------------------------------------------------------

function Invoke-MepMigration {
    <#
    .SYNOPSIS
    Runs the explicit Alembic migration step against the just-built
    backend image.

    .DESCRIPTION
    The installer explicitly builds backend/frontend before migration
    (Invoke-MepBuildImages). `docker compose run` does not request a build,
    so it uses the service image already produced by that explicit build
    step. This is local-source mode: it is NOT immutable artifact identity,
    and is not described as such.

    Fix Round 2 (P1-A): an earlier revision passed `--no-build` here. That
    flag does not exist on `docker compose run` -- the real CLI rejects it
    with "unknown flag: --no-build", so the migration could never have run.
    `--build` is deliberately NOT used either: it would add a second,
    implicit build during migration and weaken the explicit build-once
    sequence.

    `--name` avoids colliding with the `backend` service's fixed
    `container_name`, which PR24D-L1 relies on for its single-backend
    structural guard.
    #>
    param(
        [Parameter(Mandatory)] [string]$SourceSha,
        [string]$TargetEnvironmentLabel = 'local-staging'
    )
    Write-Host 'Applying database migration...'
    $result = Invoke-DockerCompose -Arguments @(
        'run', '--rm', '--no-deps', '--name', 'mep-local-staging-migrate', 'backend',
        'python', 'scripts/deploy_migrate.py',
        '--target-environment', $TargetEnvironmentLabel,
        '--artifact-sha', $SourceSha
    ) -AllowNonZeroExit -Phase 'migrate'
    foreach ($line in @($result.Output)) { Write-Host $line }
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure 'Database migration failed. The application was NOT started. PostgreSQL data was not deleted; resolve the migration error above and rerun.')
    }
    Write-InstallLog -Phase 'migrate' -Message "Migration completed successfully (artifact_sha=$SourceSha)."
}

# ---------------------------------------------------------------------------
# Application start / readiness
# ---------------------------------------------------------------------------

function Start-MepPostgres {
    $result = Invoke-DockerCompose -Arguments @('up', '-d', '--wait', '--wait-timeout', '120', 'postgres') -AllowNonZeroExit -Phase 'start-postgres'
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure 'PostgreSQL did not become healthy in time. Run .\status.ps1 for diagnostics.')
    }
}

function Start-MepRedis {
    # Deliberately fire-and-forget and never part of a --wait call: Redis
    # is non-blocking by the application's own readiness contract, so a
    # slow or broken Redis container must never block installation.
    $result = Invoke-DockerCompose -Arguments @('up', '-d', 'redis') -AllowNonZeroExit -Phase 'start-redis'
    if ($result.ExitCode -ne 0) {
        Write-InstallLog -Phase 'start-redis' -Level 'WARN' -Message 'Redis did not start; continuing because Redis is non-blocking by contract (cache/refresh-token paths fail open).'
    }
}

function Start-MepApplication {
    # Only backend and frontend are named, so their dependency graph
    # (backend -> postgres; frontend -> backend) is what gates readiness.
    # Redis is never named here and therefore can never block.
    $result = Invoke-DockerCompose -Arguments @('up', '-d', '--wait', '--wait-timeout', '180', 'backend', 'frontend') -AllowNonZeroExit -Phase 'start-app'
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure 'The application did not become ready in time (GET /api/v1/ready). Run .\status.ps1 or `docker compose -p mep-local-staging logs backend` for diagnostics.')
    }
}

function Stop-MepApplication {
    <#
    .SYNOPSIS
    Stops backend and frontend and verifies they are actually stopped
    (Fix Round 1, P1-C).

    .DESCRIPTION
    Both halves matter: the previous code discarded the stop command's
    exit code entirely, and an exit code alone would still not prove the
    containers are down. Migrating while the old backend is still running
    risks concurrent writes and a duplicated embedded scheduler, so this
    fails closed on either signal.
    #>
    $result = Invoke-DockerCompose -Arguments @('stop', 'backend', 'frontend') -AllowNonZeroExit -Phase 'stop-app'
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure 'Failed to stop the running application. Migration was NOT run and no replacement version was started -- migrating while the old backend is still running risks concurrent writes and a duplicated scheduler.')
    }

    $states = Get-MepServiceStates
    if ($null -eq $states) {
        throw (New-MepFailure 'Could not verify that the application stopped (docker compose ps failed). Refusing to migrate against an unverified state.')
    }
    if (Test-MepServiceRunning -ServiceStates $states -Service 'backend') {
        throw (New-MepFailure 'The backend container is still running after `docker compose stop`. Refusing to migrate: a running backend during migration risks concurrent writes and a duplicated scheduler.')
    }
    Write-InstallLog -Phase 'stop-app' -Message 'Application stopped and verified not running.'
}

# ---------------------------------------------------------------------------
# Administrator bootstrap (Fix Round 1, P1-B: mandatory on first install)
# ---------------------------------------------------------------------------

function Invoke-MepAdminBootstrap {
    <#
    .SYNOPSIS
    Creates the first Administrator via the existing PR24B
    `app.scripts.bootstrap_admin` CLI, unchanged.

    .DESCRIPTION
    That CLI accepts no password argument -- it generates a one-time
    password itself and prints it once to stdout -- so this function never
    accepts, transports, or stores a password. Its output is written to
    the console only and never to the installer log, which is why it is
    captured here but deliberately never passed to Write-InstallLog: the
    capture exists solely so a *failure* can be classified (backend
    "already exists" refusal vs. a real error) without hiding the
    backend's own validation message from the operator.

    Returns 'Created' or 'AlreadyExists'; throws on anything else, which
    on a first install is a hard installation failure.
    #>
    param(
        [Parameter(Mandatory)] [string]$EmployeeCode,
        [Parameter(Mandatory)] [string]$Email,
        [Parameter(Mandatory)] [string]$FullName
    )

    if ([string]::IsNullOrWhiteSpace($EmployeeCode) -or [string]::IsNullOrWhiteSpace($Email) -or [string]::IsNullOrWhiteSpace($FullName)) {
        throw (New-MepFailure 'Administrator employee code, email, and full name are all required. Installation is NOT complete without an administrator account -- rerun .\install.ps1 and provide all three.')
    }

    $result = Invoke-DockerCompose -Arguments @(
        'exec', '-T', 'backend',
        'python', '-m', 'app.scripts.bootstrap_admin',
        '--employee-code', $EmployeeCode, '--email', $Email, '--full-name', $FullName
    ) -AllowNonZeroExit -Phase 'bootstrap'

    # Console only. Never Write-InstallLog: on success this carries the
    # one-time password.
    foreach ($line in @($result.Output)) { Write-Host $line }

    if ($result.ExitCode -eq 0) {
        Write-InstallLog -Phase 'bootstrap' -Message "Administrator created for employee_code=$EmployeeCode (one-time password shown on console only, never logged)."
        return 'Created'
    }

    $joined = (@($result.Output) -join "`n")
    if ($joined -match 'administrator already exists') {
        # The backend is the source of truth, and it says one exists --
        # a legitimate, satisfied state when converging a previously
        # partial installation.
        Write-InstallLog -Phase 'bootstrap' -Message 'Backend reports an administrator already exists; no second administrator created.'
        return 'AlreadyExists'
    }

    throw (New-MepFailure "Administrator bootstrap failed (exit code $($result.ExitCode)). Installation is NOT complete. See the backend's message above, correct the input, and rerun .\install.ps1.")
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

function Invoke-MepInstall {
    <#
    .SYNOPSIS
    The full install/converge sequence. Caller is responsible for holding
    the mutation lock.

    .PARAMETER AdminCredentialCallback
    Scriptblock returning a hashtable with EmployeeCode/Email/FullName,
    invoked only when an Administrator is actually required. Injected so
    the entry script can prompt interactively while tests can supply
    fixed (including deliberately blank) values.
    #>
    param(
        [Parameter(Mandatory)] [scriptblock]$AdminCredentialCallback,
        [scriptblock]$ConfigCallback,
        [switch]$SkipPrerequisites
    )

    $state = Get-InstallationState
    Write-InstallLog -Phase 'install' -Message "Detected installation state: $state"

    if ($state -eq 'AMBIGUOUS') {
        throw (New-MepFailure 'Installation state could not be determined safely. Run .\status.ps1 for diagnostics, resolve the underlying Docker/configuration conflict, then retry.')
    }

    if (-not $SkipPrerequisites) {
        $failures = Invoke-PrerequisiteChecks -FrontendPort (Get-ConfiguredHttpPort)
        if ($failures.Count -gt 0) {
            foreach ($f in $failures) {
                Write-Host "ERROR [$($f.Check)]: $($f.Error)" -ForegroundColor Red
                Write-Host "ACTION: $($f.Action)" -ForegroundColor Yellow
            }
            throw (New-MepFailure 'One or more prerequisites are not satisfied. Resolve the items above and rerun .\install.ps1.')
        }
    }

    # Config: generate on a genuinely fresh install, preserve otherwise.
    if (-not (Test-EnvFileExists)) {
        $config = & $ConfigCallback
        New-LocalStagingEnvFile -AllowedOrigins $config.AllowedOrigins -HttpPort $config.HttpPort
    }
    else {
        Write-InstallLog -Phase 'install' -Message 'Existing .env found; preserving all secrets and configuration unchanged.'
    }

    if ((Invoke-DockerComposeConfigOnly) -ne 0) {
        throw (New-MepFailure 'docker compose config failed -- .env is likely missing a required value. See deployment/local-staging/.env.example.')
    }

    # Build BEFORE migration so the migration and the running application
    # are both the current source, never a stale cached image.
    Invoke-MepBuildImages

    Start-MepPostgres
    Start-MepRedis

    $sourceSha = Get-CurrentSourceSha
    Invoke-MepMigration -SourceSha $sourceSha

    Start-MepApplication

    # Administrator bootstrap is mandatory whenever this installation has
    # never completed successfully -- including a previously-partial
    # install whose metadata was (correctly) never written.
    if (-not (Test-MepInstallCompleted)) {
        $creds = & $AdminCredentialCallback
        $bootstrapOutcome = Invoke-MepAdminBootstrap `
            -EmployeeCode $creds.EmployeeCode -Email $creds.Email -FullName $creds.FullName
        Write-InstallLog -Phase 'install' -Message "Administrator bootstrap outcome: $bootstrapOutcome"
    }
    else {
        Write-InstallLog -Phase 'install' -Message 'Installation already completed previously; skipping Administrator bootstrap (backend already has one).'
    }

    # Only now -- after build, migration, readiness, and a satisfied
    # Administrator requirement -- is the installation actually complete.
    Set-InstallMetadata -SourceSha $sourceSha
    Write-InstallLog -Phase 'install' -Message 'install.ps1 completed successfully.'
    return $sourceSha
}

# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

function Invoke-MepUpdate {
    <#
    .SYNOPSIS
    Conservative update sequence. Caller holds the mutation lock and is
    responsible for having already enforced the -AcknowledgeUpdateRisk
    gate (no automated backup safety net exists until PR24D-L3).
    #>
    if (-not (Test-EnvFileExists)) {
        throw (New-MepFailure 'No existing installation found. Run .\install.ps1 first; update.ps1 only operates on an existing installation.')
    }

    # Fix Round 2 (P1-C/§11/§12): update is an UPDATE mechanism, not an
    # installation-recovery mechanism. The completion precondition is
    # captured BEFORE any mutation, so update can never be the operation
    # that transitions InstallCompleted from absent/false to true and can
    # never launder a PARTIAL installation -- one whose Administrator
    # bootstrap never succeeded -- into a completed one.
    if (-not (Test-MepInstallCompleted)) {
        throw (New-MepFailure @'
Installation has never completed successfully, so it cannot be updated.
This usually means a previous install failed before the Administrator was
created.
ACTION: Run .\install.ps1 again. It preserves your .env, secrets, and
PostgreSQL data, converges the deployment, and completes the Administrator
bootstrap. update.ps1 is not an installation-recovery mechanism.
'@)
    }

    # Fix Round 4 (§14): the initial state is captured ONCE, before any
    # mutation, and every branching decision below uses that snapshot.
    # Re-reading it after the build/stop would risk branching on a state
    # this function itself had just changed.
    $initialState = Get-InstallationState
    Write-InstallLog -Phase 'update' -Message "Detected installation state: $initialState"
    # Only states that represent a genuinely completed installation may be
    # updated. PARTIAL / AMBIGUOUS / FRESH all fail closed.
    if ($initialState -notin @('EXISTING_HEALTHY', 'EXISTING_STOPPED')) {
        throw (New-MepFailure "Installation state is '$initialState'; update requires a previously completed installation (EXISTING_HEALTHY or EXISTING_STOPPED).`nACTION: Run .\status.ps1 to inspect, then .\install.ps1 to converge the installation before updating.")
    }

    # Build first: a failed build must never leave the old application
    # stopped, so nothing is stopped until the new images exist.
    Invoke-MepBuildImages

    # PR24D-L3 (§19/§21/§41): a schema-changing update may not proceed
    # without a verified backup. This replaces the L2
    # -AcknowledgeUpdateRisk switch, which existed only because no backup
    # safety net had shipped yet -- an operator's acknowledgement is not a
    # substitute for a restorable backup. The contract is now simply:
    # no backup, no update.
    #
    # The backup runs BEFORE the application is stopped, so a backup
    # failure leaves a healthy deployment untouched and still serving.
    # PR24C's logical backup is transactionally consistent
    # (pg_dump --format=custom), so an active application does not
    # compromise the snapshot and the writers do not need to be quiesced
    # first. Invoke-MepBackup converges PostgreSQL to healthy itself, so
    # this works from EXISTING_STOPPED too -- and it starts ONLY
    # PostgreSQL, never the backend, to take the backup.
    #
    # This calls the SAME shared Invoke-MepBackup that backup.ps1 calls --
    # there is no "quick backup" variant here. It deliberately does NOT
    # shell out to backup.ps1: that script acquires the mutation lock this
    # update already holds, and re-acquiring the same named mutex is not a
    # re-entrancy we have proven. The lock stays at the entry-script
    # boundary; the shared function is what both paths reuse (§22).
    Invoke-MepBackup -Reason 'pre-update' | Out-Null

    if ($initialState -eq 'EXISTING_HEALTHY') {
        # Stop the application writers (and the scheduler with them) and
        # verify they are really down before any schema change. Only
        # backend/frontend are stopped -- PostgreSQL is deliberately left
        # running, since the migration needs it.
        Stop-MepApplication
    }
    else {
        # EXISTING_STOPPED: the application is already down. Issuing a stop
        # here would be ritual, and a "failed to stop" error against an
        # intentionally stopped deployment would be actively misleading.
        Write-InstallLog -Phase 'update' -Message 'Application was already stopped; skipping the application stop step.'
        Write-Host 'Application is already stopped; skipping the stop step.'
    }

    # Fix Round 4 (P1): database availability is a HARD precondition of the
    # migration, not an assumption. The migration container runs with
    # --no-deps (deliberately -- it must run before the application), so
    # Compose will NOT start PostgreSQL for it.
    #
    # Re-asserted here after the stop: Stop-MepApplication targets only
    # backend/frontend, so PostgreSQL should still be up, but the
    # migration's precondition is verified rather than assumed. The step
    # is idempotent and health-gated, so this is cheap on both paths.
    Start-MepPostgres

    $sourceSha = Get-CurrentSourceSha
    Invoke-MepMigration -SourceSha $sourceSha -TargetEnvironmentLabel 'local-staging-update'

    # Documented post-update contract: a successful update always ends with
    # the application RUNNING and READY, whichever state it started from.
    # Entering from EXISTING_STOPPED therefore leaves the application
    # started -- this is deliberate and documented in update.ps1, not a
    # silent side effect. Preserving an original stopped state is NOT
    # implemented here; that would be a separate Owner-requested feature.
    Start-MepApplication

    Set-InstallMetadata -SourceSha $sourceSha -RequireExistingCompletion
    Write-InstallLog -Phase 'update' -Message "update.ps1 completed successfully (source_sha=$sourceSha)."
    return $sourceSha
}

# ---------------------------------------------------------------------------
# Start / stop / uninstall
# ---------------------------------------------------------------------------

function Invoke-MepStart {
    if (-not (Test-EnvFileExists)) {
        throw (New-MepFailure 'No existing installation found (deployment/local-staging/.env is missing). Run .\install.ps1 first.')
    }
    if ((Invoke-DockerComposeConfigOnly) -ne 0) {
        throw (New-MepFailure 'docker compose config failed against the existing .env. See deployment/local-staging/.env.example.')
    }
    Start-MepPostgres
    Start-MepRedis
    # Never runs a migration: schema changes belong to install.ps1/update.ps1.
    Start-MepApplication
    Write-InstallLog -Phase 'start' -Message 'start.ps1 completed successfully.'
}

function Invoke-MepStop {
    if (-not (Test-EnvFileExists)) {
        Write-Host 'No existing installation found -- nothing to stop.' -ForegroundColor Yellow
        return
    }
    # `stop` (never `down`): containers are stopped but not removed, and
    # the named volumes are never touched by this command.
    $result = Invoke-DockerCompose -Arguments @('stop') -AllowNonZeroExit -Phase 'stop'
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure 'docker compose stop reported a failure. PostgreSQL data, configuration, and any backups were not modified.')
    }
    Write-InstallLog -Phase 'stop' -Message 'stop.ps1 completed successfully.'
}

function Invoke-MepUninstall {
    <#
    .SYNOPSIS
    Removes application containers. Data removal requires -RemoveData,
    and the caller is responsible for having already obtained the typed
    confirmation.
    #>
    param([switch]$RemoveData)

    if (-not (Test-EnvFileExists)) {
        Write-Host 'No existing installation found -- nothing to uninstall.' -ForegroundColor Yellow
        return
    }

    $result = Invoke-DockerCompose -Arguments @('down') -AllowNonZeroExit -Phase 'uninstall'
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure 'docker compose down reported a failure. Nothing was deleted.')
    }

    if (-not $RemoveData) {
        Write-InstallLog -Phase 'uninstall' -Message 'uninstall.ps1 completed (containers removed; data, configuration, and secrets preserved).'
        return
    }

    # Only reachable behind -RemoveData plus the entry script's typed
    # confirmation -- never the default path.
    $volResult = Invoke-DockerCompose -Arguments @('down', '--volumes') -AllowNonZeroExit -Phase 'uninstall-data'
    if ($volResult.ExitCode -ne 0) {
        throw (New-MepFailure 'Failed to remove the data volumes.')
    }
    # SilentlyContinue covers only the already-absent case; the removal is
    # then VERIFIED. Reporting "data removed" while .env survives would
    # leave the operator believing the generated secrets are gone when
    # they are still on disk.
    Remove-Item -LiteralPath $Script:EnvFilePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Script:MetadataFilePath -Force -ErrorAction SilentlyContinue
    foreach ($leftover in @($Script:EnvFilePath, $Script:MetadataFilePath)) {
        if (Test-Path -LiteralPath $leftover) {
            throw (New-MepFailure "Data volumes were removed, but '$leftover' could not be deleted and still contains this installation's configuration.`nACTION: Close any program holding the file open and delete it manually.")
        }
    }
    Write-InstallLog -Phase 'uninstall' -Message 'uninstall.ps1 completed (data removed per -RemoveData confirmation).'
}
