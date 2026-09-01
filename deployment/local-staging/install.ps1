<#
.SYNOPSIS
PR24D-L2 (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §32):
installs or converges the local Staging/UAT Docker deployment on a Windows
host with Docker Desktop.

THIS IS NOT A FOURTH ENVIRONMENT -- see compose.yml's own header and
OD-PR24-4. This script only orchestrates the existing Staging/UAT
execution mode; it introduces no new environment type, no new backup
engine, and no new user-creation logic (Administrator bootstrap is the
existing PR24B `app.scripts.bootstrap_admin` CLI, invoked unchanged).

.DESCRIPTION
Flow (repository §5): prerequisite checks -> installation-state detection
-> fresh-install secret generation (or existing-install secret
preservation) -> start PostgreSQL and wait healthy -> explicit Alembic
migration (backend/scripts/deploy_migrate.py, reused unchanged) -> start
the application stack and wait healthy -> Administrator bootstrap (skipped
if one already exists) -> print the LAN access URL.

Never runs `docker compose ... --scale backend=2` (the single-backend
structural guard from PR24D-L1's fixed `container_name` is preserved
unchanged); never regenerates secrets on an existing installation; never
runs `docker compose down -v`.

.EXAMPLE
.\install.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

function Write-Banner {
    param([string]$Text)
    Write-Host ''
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Exit-WithError {
    param([string]$Message)
    Write-InstallLog -Phase 'install' -Level 'ERROR' -Message $Message
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

Write-Banner 'Medical Equipment Pool -- Local Staging/UAT Install'
Write-InstallLog -Phase 'install' -Message 'install.ps1 started.'

try {
    Enter-InstallLock
}
catch {
    Exit-WithError $_.Exception.Message
}

try {
    # -------------------------------------------------------------------
    # 1. Determine installation state before anything else (repository
    #    §13): every branch below depends on this, and a second run must
    #    converge, not reset.
    # -------------------------------------------------------------------
    $state = Get-InstallationState
    Write-InstallLog -Phase 'install' -Message "Detected installation state: $state"

    if ($state -eq 'AMBIGUOUS') {
        Exit-WithError 'Installation state could not be determined safely (docker compose ps failed). Run .\status.ps1 for diagnostics, resolve the underlying Docker issue, then retry.'
    }

    if ($state -eq 'EXISTING_HEALTHY') {
        Write-Host 'An existing, healthy installation was found. Re-running install.ps1 converges it (no secrets are regenerated, no data is touched).' -ForegroundColor Yellow
    }

    # -------------------------------------------------------------------
    # 2. Prerequisite checks. Port check needs the port this installation
    #    already uses if one exists, otherwise the default.
    # -------------------------------------------------------------------
    $existingEnv = Read-EnvFile
    $httpPort = if ($existingEnv.ContainsKey('LOCAL_STAGING_HTTP_PORT') -and $existingEnv['LOCAL_STAGING_HTTP_PORT']) {
        [int]$existingEnv['LOCAL_STAGING_HTTP_PORT']
    }
    else { 80 }

    Write-Banner 'Checking prerequisites'
    $failures = Invoke-PrerequisiteChecks -FrontendPort $httpPort
    if ($failures.Count -gt 0) {
        foreach ($f in $failures) {
            Write-Host "ERROR [$($f.Check)]: $($f.Error)" -ForegroundColor Red
            Write-Host "ACTION: $($f.Action)" -ForegroundColor Yellow
            Write-InstallLog -Phase 'prerequisites' -Level 'ERROR' -Message "$($f.Check): $($f.Error)"
        }
        Exit-WithError 'One or more prerequisites are not satisfied. Resolve the items above and rerun .\install.ps1.'
    }
    Write-Host 'All prerequisite checks passed.' -ForegroundColor Green

    # -------------------------------------------------------------------
    # 3. .env: generate on fresh install, preserve on every other state
    #    (repository §8/§9/§14 -- never regenerate an existing secret).
    # -------------------------------------------------------------------
    if (-not (Test-EnvFileExists)) {
        Write-Banner 'Generating local configuration'
        $candidates = Get-LikelyLanIPv4Addresses
        $suggested = if ($candidates.Count -ge 1) { $candidates[0] } else { $null }
        if ($candidates.Count -gt 1) {
            Write-Host 'Multiple LAN addresses were detected on this machine:' -ForegroundColor Yellow
            $candidates | ForEach-Object { Write-Host "  - $_" }
            Write-Host 'Choose the one other devices on your hospital LAN will actually use to reach this PC.'
        }
        $defaultOrigin = if ($suggested) { "http://$suggested" } else { 'http://<this-computer-LAN-IP>' }
        $originInput = Read-Host "LAN URL this deployment will be reached at [$defaultOrigin]"
        $allowedOrigins = if ([string]::IsNullOrWhiteSpace($originInput)) { $defaultOrigin } else { $originInput }

        $portInput = Read-Host "Frontend port [80]"
        $newPort = if ([string]::IsNullOrWhiteSpace($portInput)) { 80 } else { [int]$portInput }

        New-LocalStagingEnvFile -AllowedOrigins $allowedOrigins -HttpPort $newPort
        $httpPort = $newPort
        Write-Host "Generated deployment/local-staging/.env (never committed; see .gitignore)." -ForegroundColor Green
    }
    else {
        Write-InstallLog -Phase 'install' -Message 'Existing .env found; preserving all secrets and configuration unchanged.'
    }

    # -------------------------------------------------------------------
    # 4. Validate the compose file + env combination before touching the
    #    daemon (repository §49: docker compose config --quiet).
    # -------------------------------------------------------------------
    Write-Banner 'Validating Compose configuration'
    $configExit = Invoke-DockerComposeConfigOnly
    if ($configExit -ne 0) {
        Exit-WithError 'docker compose config failed -- .env is likely missing a required value. See deployment/local-staging/.env.example.'
    }
    Write-Host 'Compose configuration is valid.' -ForegroundColor Green

    # -------------------------------------------------------------------
    # 5. Start PostgreSQL and wait for it to become healthy. Redis is
    #    deliberately started separately, outside any --wait call, so it
    #    can never block installation (repository §6/§17/§22 -- Redis is
    #    non-blocking by the application's own established contract).
    # -------------------------------------------------------------------
    Write-Banner 'Starting PostgreSQL'
    $pgResult = Wait-ComposeServicesHealthy -Services @('postgres') -TimeoutSeconds 120
    if ($pgResult.ExitCode -ne 0) {
        Exit-WithError 'PostgreSQL did not become healthy in time. Run .\status.ps1 or `docker compose -p mep-local-staging logs postgres` for diagnostics.'
    }
    Write-Host 'PostgreSQL is healthy.' -ForegroundColor Green

    Write-InstallLog -Phase 'install' -Message 'Starting Redis (fire-and-forget; never gates installation).'
    Invoke-DockerCompose -Arguments @('up', '-d', 'redis') | Out-Null

    # -------------------------------------------------------------------
    # 6. Explicit migration step -- reuses backend/scripts/deploy_migrate.py
    #    unchanged (repository §18/§19). Never part of application startup.
    #    Uses --name to avoid colliding with the fixed `container_name` the
    #    real `backend` service reserves (repository §15).
    # -------------------------------------------------------------------
    Write-Banner 'Running database migration'
    $sourceSha = Get-CurrentSourceSha
    $migrateResult = Invoke-DockerCompose -Arguments @(
        'run', '--rm', '--name', 'mep-local-staging-migrate', '--no-deps', 'backend',
        'python', 'scripts/deploy_migrate.py',
        '--target-environment', 'local-staging',
        '--artifact-sha', $sourceSha
    ) -PassThru
    $migrateResult.Output | ForEach-Object { Write-Host $_ }
    if ($migrateResult.ExitCode -ne 0) {
        Exit-WithError 'Database migration failed. The application stack was not started. See the migration output above; PostgreSQL data was not modified destructively.'
    }
    Write-Host 'Migration completed successfully.' -ForegroundColor Green

    # -------------------------------------------------------------------
    # 7. Start the application stack and wait for readiness. Only backend
    #    and frontend are named here -- their dependency graph
    #    (backend depends_on postgres; frontend depends_on backend) never
    #    includes redis, so this call cannot be blocked by Redis either.
    # -------------------------------------------------------------------
    Write-Banner 'Starting the application'
    $appResult = Wait-ComposeServicesHealthy -Services @('backend', 'frontend') -TimeoutSeconds 180
    if ($appResult.ExitCode -ne 0) {
        Exit-WithError 'The application did not become ready in time (GET /api/v1/ready). Run .\status.ps1 or `docker compose -p mep-local-staging logs backend` for diagnostics.'
    }
    Write-Host 'Application is ready (GET /api/v1/ready passing).' -ForegroundColor Green

    # -------------------------------------------------------------------
    # 8. Administrator bootstrap -- reuses app.scripts.bootstrap_admin
    #    unchanged (repository §20/§21). That CLI generates its own
    #    one-time password and prints it to stdout; this script never
    #    accepts, transports, or logs a password itself. Output streams
    #    directly to the console (never captured into a variable this
    #    script might log) so the printed one-time password never touches
    #    the install log.
    # -------------------------------------------------------------------
    Write-Banner 'Administrator account'
    $bootstrapArgsProvided = $false
    $adminMetadata = Get-InstallMetadata
    if (-not $adminMetadata -or $state -eq 'FRESH') {
        $employeeCode = Read-Host 'Administrator employee code (e.g. ADMIN001)'
        $email = Read-Host 'Administrator email'
        $fullNameInput = Read-Host 'Administrator full name [System Administrator]'
        $fullName = if ([string]::IsNullOrWhiteSpace($fullNameInput)) { 'System Administrator' } else { $fullNameInput }
        $bootstrapArgsProvided = -not ([string]::IsNullOrWhiteSpace($employeeCode) -or [string]::IsNullOrWhiteSpace($email))
    }

    if ($bootstrapArgsProvided) {
        $composeArgs = @(
            'compose', '-p', $Script:ComposeProjectName, '-f', $Script:ComposeFilePath, '--env-file', $Script:EnvFilePath,
            'exec', '-T', 'backend',
            'python', '-m', 'app.scripts.bootstrap_admin',
            '--employee-code', $employeeCode, '--email', $email, '--full-name', $fullName
        )
        & docker @composeArgs
        $bootstrapExit = $LASTEXITCODE
        if ($bootstrapExit -eq 0) {
            Write-InstallLog -Phase 'bootstrap' -Message "Administrator bootstrap completed for employee_code=$employeeCode (password shown above, never logged)."
        }
        else {
            Write-InstallLog -Phase 'bootstrap' -Level 'WARN' -Message 'Administrator bootstrap did not create a new account (see console output above -- an administrator likely already exists).'
        }
    }
    else {
        Write-Host 'Skipping Administrator bootstrap prompt (an installation already exists; use the existing administrator account to manage users).' -ForegroundColor Yellow
    }

    # -------------------------------------------------------------------
    # 9. Record non-secret installation metadata and print the LAN URL.
    # -------------------------------------------------------------------
    Set-InstallMetadata -SourceSha $sourceSha

    $finalEnv = Read-EnvFile
    $finalPort = if ($finalEnv.ContainsKey('LOCAL_STAGING_HTTP_PORT') -and $finalEnv['LOCAL_STAGING_HTTP_PORT']) { $finalEnv['LOCAL_STAGING_HTTP_PORT'] } else { 80 }
    $lanCandidates = Get-LikelyLanIPv4Addresses

    Write-Banner 'Install complete'
    Write-Host 'Access this deployment from any authorized device on the same LAN:' -ForegroundColor Green
    if ($lanCandidates.Count -eq 0) {
        Write-Host "  http://localhost:$finalPort  (LAN address could not be detected automatically -- reachable from this PC only)"
    }
    else {
        foreach ($addr in $lanCandidates) {
            Write-Host "  http://${addr}:$finalPort"
        }
    }
    Write-Host ''
    Write-Host 'If other devices cannot reach this address, a Windows Firewall rule may be required for the frontend port (this script does not create one automatically).' -ForegroundColor Yellow
    Write-InstallLog -Phase 'install' -Message 'install.ps1 completed successfully.'
}
finally {
    Exit-InstallLock
}
