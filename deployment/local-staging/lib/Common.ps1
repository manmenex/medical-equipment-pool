# PR24D-L2 (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §32):
# shared primitives for the local Staging/UAT installer/operations
# scripts. Orchestration sequences live in lib/Operations.ps1, which is
# built on top of this file -- keeping the two apart is what lets
# tests/Invoke-InstallerTests.ps1 exercise the real install/update
# sequences with a mocked command layer instead of duplicated pseudo-code.
#
# THIS IS NOT A FOURTH ENVIRONMENT. OD-PR24-4's taxonomy (Development,
# Staging/UAT, Production) is unchanged -- see compose.yml's own header.

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Paths and deployment identity
# ---------------------------------------------------------------------------

# $PSScriptRoot here is deployment/local-staging/lib -- resolve everything
# relative to the deployment directory itself, never the operator's current
# working directory, so scripts behave the same regardless of where they are
# invoked from.
$Script:DeploymentRoot = Split-Path -Parent $PSScriptRoot
$Script:ComposeFilePath = Join-Path $Script:DeploymentRoot 'compose.yml'
$Script:EnvFilePath = Join-Path $Script:DeploymentRoot '.env'
$Script:EnvExamplePath = Join-Path $Script:DeploymentRoot '.env.example'
$Script:LogDirectory = Join-Path $Script:DeploymentRoot 'logs'
$Script:MetadataFilePath = Join-Path $Script:DeploymentRoot '.install-metadata.json'

# PR24D-L3: the single deterministic local backup root. Deliberately on
# the HOST filesystem beside the deployment, never inside the PostgreSQL
# Docker volume -- so backups survive `docker compose down`, survive the
# default uninstall, and can be copied elsewhere by the operator with an
# ordinary file copy. Gitignored; filenames carry no secret (PR24C's
# backup_filename() is mep-postgres-<environment>-<UTC timestamp>.dump).
$Script:BackupRoot = Join-Path $Script:DeploymentRoot 'backups'

# The environment LABEL recorded in backup manifests and filenames. This
# is the Staging/UAT class executed locally -- it is NOT a fourth
# environment (OD-PR24-4), and it is deliberately NOT the container's
# ENVIRONMENT=production setting, which exists only to keep
# validate_production_secrets() active (PR24D-L1). Labelling local
# backups "production" would be actively misleading provenance.
$Script:BackupEnvironmentLabel = 'local-staging'

# Restore rehearsal targets are created on the SAME PostgreSQL server but
# always under a distinct, timestamped database name, so PR24C's
# same-source guard (host+port+dbname) sees a genuinely different
# database and passes honestly rather than being bypassed.
$Script:RehearsalDatabasePrefix = 'mep_local_restore_rehearsal_'

# Deterministic Compose project identity: every Compose call below passes
# this explicitly with -p, so install/start/stop/status/update/uninstall
# always operate on the same deployment regardless of invocation directory.
$Script:ComposeProjectName = 'mep-local-staging'

# Service model (Fix Round 3, P1). "Expected to exist normally" is NOT the
# same as "required for operational health", and conflating the two made
# the classifier contradict the application's own architecture contract:
# a deployment whose Redis had failed was reported PARTIAL, which then
# blocked install convergence and update eligibility.
#
#   PostgreSQL  BLOCKING / REQUIRED   -- readiness fails without it
#   Backend     REQUIRED
#   Frontend    REQUIRED              -- this local deployment serves via it
#   Redis       NON-BLOCKING / DEGRADED
#
# Redis is non-blocking by the backend's own design: every path in
# backend/app/core/redis.py fails open (cache misses no-op;
# is_refresh_token_valid returns true on a Redis error), and
# GET /api/v1/ready reports Redis as "degraded" without ever failing on
# it. Redis is still operationally useful -- it is not irrelevant, just
# not a precondition for the deployment being considered healthy.
$Script:RequiredServices = @('postgres', 'backend', 'frontend')
$Script:OptionalServices = @('redis')

# Every service Compose creates for this project. Used for DISCOVERY and
# SAFETY scope -- deciding whether a machine is genuinely untouched -- not
# for operational health. An orphan Redis container still proves a machine
# is not clean, even though Redis never gates health.
$Script:KnownServices = @($Script:RequiredServices + $Script:OptionalServices)

# Single mutation-lock namespace shared by every state-changing script
# (install/update/start/stop/uninstall). status.ps1 is read-only and does
# not take it.
$Script:MutationLockName = 'MEP-LocalStaging-Deployment-Mutation'

# ---------------------------------------------------------------------------
# Logging (never logs secrets -- see Protect-LogValue)
# ---------------------------------------------------------------------------

function Initialize-InstallLog {
    if (-not (Test-Path -LiteralPath $Script:LogDirectory)) {
        New-Item -ItemType Directory -Path $Script:LogDirectory -Force | Out-Null
    }
}

function Get-InstallLogPath {
    Join-Path $Script:LogDirectory 'install-operations.log'
}

function Write-InstallLog {
    param(
        [Parameter(Mandatory)] [string]$Phase,
        [Parameter(Mandatory)] [string]$Message,
        [ValidateSet('INFO', 'WARN', 'ERROR')] [string]$Level = 'INFO'
    )
    Initialize-InstallLog
    $timestamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $line = "[$timestamp] [$Level] [$Phase] $Message"
    Add-Content -LiteralPath (Get-InstallLogPath) -Value $line
    switch ($Level) {
        'ERROR' { Write-Host $line -ForegroundColor Red }
        'WARN' { Write-Host $line -ForegroundColor Yellow }
        default { Write-Host $line }
    }
}

# Redaction helper for any value that might contain a credential -- e.g. a
# DATABASE_URL, so a diagnostic that must include *something* about it never
# writes the actual password. Mirrors backend/scripts/pg_backup_lib.py's own
# "connection strings are never logged/echoed" convention.
function Protect-LogValue {
    param([Parameter(Mandatory)] [string]$Value)
    if ($Value -match '^(?<scheme>[a-zA-Z0-9+]+)://(?<user>[^:@/]+):(?<pass>[^@]+)@(?<rest>.+)$') {
        return "$($Matches.scheme)://$($Matches.user):***REDACTED***@$($Matches.rest)"
    }
    return '***REDACTED***'
}

# ---------------------------------------------------------------------------
# Centralized native command execution (Fix Round 1, review §21)
# ---------------------------------------------------------------------------

function Invoke-MepCommand {
    <#
    .SYNOPSIS
    The single seam through which every native command in this installer
    runs. Never uses Invoke-Expression; always an executable plus an
    argument array, so paths containing spaces and values containing
    shell metacharacters are passed through safely.

    .DESCRIPTION
    Always inspects the native exit code explicitly -- PowerShell does not
    do this for you, and a silently-ignored `$LASTEXITCODE` is exactly the
    class of bug Fix Round 1 found. By default a non-zero exit throws;
    pass -AllowNonZeroExit when the caller genuinely needs to branch on
    the code (and then it must check .ExitCode itself).

    Returns [pscustomobject] @{ ExitCode; Output } where Output is the
    combined stdout/stderr lines.

    .PARAMETER NoCapture
    Streams output straight to the console instead of capturing it. Used
    for the Administrator bootstrap path, whose stdout carries a one-time
    password that must never be written to the installer log.
    #>
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [AllowEmptyCollection()] [string[]]$Arguments,
        [switch]$AllowNonZeroExit,
        [switch]$NoCapture,
        [string]$Phase = 'command'
    )

    if ($NoCapture) {
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
        $output = @()
    }
    else {
        $output = & $FilePath @Arguments 2>&1 | ForEach-Object { "$_" }
        $exitCode = $LASTEXITCODE
    }

    if ($exitCode -ne 0 -and -not $AllowNonZeroExit) {
        # Never echoes the argument array: it can legitimately contain a
        # value derived from .env (e.g. a compose --env-file path) and the
        # command's own output may contain a connection string.
        throw "$FilePath exited with code $exitCode during phase '$Phase'. See the console output above for details."
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = $output
    }
}

function Invoke-DockerCompose {
    <#
    .SYNOPSIS
    Runs `docker compose` against this installation's compose file, env
    file, and deterministic project name, through Invoke-MepCommand.
    #>
    param(
        [Parameter(Mandatory)] [string[]]$Arguments,
        [switch]$AllowNonZeroExit,
        [switch]$NoCapture,
        [string]$Phase = 'compose'
    )
    $baseArgs = @('compose', '-p', $Script:ComposeProjectName, '-f', $Script:ComposeFilePath, '--env-file', $Script:EnvFilePath)
    return Invoke-MepCommand -FilePath 'docker' -Arguments ($baseArgs + $Arguments) `
        -AllowNonZeroExit:$AllowNonZeroExit -NoCapture:$NoCapture -Phase $Phase
}

function Invoke-DockerComposeConfigOnly {
    <#
    .SYNOPSIS
    `docker compose config` does not require a running daemon -- used by
    prerequisite checks to validate the compose file/env combination is at
    least well-formed before anything is started.
    #>
    $result = Invoke-MepCommand -FilePath 'docker' `
        -Arguments @('compose', '-f', $Script:ComposeFilePath, '--env-file', $Script:EnvFilePath, 'config', '--quiet') `
        -AllowNonZeroExit -Phase 'compose-config'
    return $result.ExitCode
}

# ---------------------------------------------------------------------------
# Atomic mutation lock (Fix Round 1, P1-D)
# ---------------------------------------------------------------------------

function Enter-MepMutationLock {
    <#
    .SYNOPSIS
    Acquires the single deployment mutation lock atomically, or fails
    immediately with an actionable message.

    .DESCRIPTION
    Uses a named mutex rather than the previous Test-Path-then-write file
    pattern, which had a check-then-act (TOCTOU) race: two installers
    could both observe "no lock file" and both proceed. A named mutex's
    acquisition is atomic at the OS level and is released automatically if
    the owning process dies, so there is no stale-lock file to reason
    about. Verified to serialize correctly across separate processes on
    both Windows and Linux PowerShell.

    Returns the mutex, which the caller MUST release in a finally block
    via Exit-MepMutationLock.
    #>
    param([int]$TimeoutMilliseconds = 0)

    $createdNew = $false
    $mutex = [System.Threading.Mutex]::new($false, $Script:MutationLockName, [ref]$createdNew)
    $acquired = $false
    try {
        $acquired = $mutex.WaitOne($TimeoutMilliseconds)
    }
    catch [System.Threading.AbandonedMutexException] {
        # The previous owner died without releasing. The lock is ours now,
        # and any half-finished state it left behind is exactly what the
        # installer's own state detection is designed to classify.
        $acquired = $true
    }

    if (-not $acquired) {
        $mutex.Dispose()
        throw "Another Medical Equipment Pool deployment operation is already in progress.`nACTION: Wait for it to finish, then retry."
    }
    return $mutex
}

function Exit-MepMutationLock {
    param($Mutex)
    if ($null -eq $Mutex) { return }
    try { $Mutex.ReleaseMutex() } catch { }
    $Mutex.Dispose()
}

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

function Test-DockerCliAvailable {
    return $null -ne (Get-Command docker -ErrorAction SilentlyContinue)
}

function Test-DockerEngineRunning {
    if (-not (Test-DockerCliAvailable)) { return $false }
    $result = Invoke-MepCommand -FilePath 'docker' -Arguments @('info') -AllowNonZeroExit -Phase 'docker-info'
    return $result.ExitCode -eq 0
}

function Test-DockerComposeV2Available {
    if (-not (Test-DockerCliAvailable)) { return $false }
    $result = Invoke-MepCommand -FilePath 'docker' -Arguments @('compose', 'version') -AllowNonZeroExit -Phase 'compose-version'
    return $result.ExitCode -eq 0
}

function Test-PortAvailable {
    <#
    .SYNOPSIS
    Best-effort TCP bind test on all interfaces. Returns $true if the port
    can be bound (i.e. nothing is listening on it right now). Never kills
    or inspects the owning process.
    #>
    param([Parameter(Mandatory)] [int]$Port)
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $listener) { $listener.Stop() }
    }
}

function Test-PortOwnedByThisInstallation {
    <#
    .SYNOPSIS
    Distinguishes "port is free" from "port is already ours" -- an
    EXISTING_HEALTHY installation holding its own port is not the same
    failure as an unrelated process occupying it.
    #>
    param([Parameter(Mandatory)] [int]$Port)
    # Fix Round 2, P1-B: routed through the state inspector rather than
    # `docker compose ps`, because this runs during prerequisite checks --
    # i.e. before `.env` exists on a fresh install.
    $states = Get-MepServiceStates
    if ($null -eq $states -or -not $states.ContainsKey('frontend')) { return $false }
    $ports = "$($states['frontend'].Ports)"
    return ($ports -match [regex]::Escape(":$Port->"))
}

function Test-SufficientDiskSpace {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [double]$MinimumGigabytes = 5
    )
    $probePath = $Path
    while (-not (Test-Path -LiteralPath $probePath)) {
        $parent = Split-Path -Parent $probePath
        if ([string]::IsNullOrEmpty($parent) -or $parent -eq $probePath) { break }
        $probePath = $parent
    }
    try {
        $drive = [System.IO.DriveInfo]::new((Get-Item -LiteralPath $probePath).FullName)
        $freeGb = $drive.AvailableFreeSpace / 1GB
        return $freeGb -ge $MinimumGigabytes
    }
    catch {
        # Best-effort: an unsupported platform/path should not hard-fail the
        # installer over a diagnostic-only check.
        return $true
    }
}

function Test-PathWritable {
    param([Parameter(Mandatory)] [string]$Path)
    try {
        if (-not (Test-Path -LiteralPath $Path)) {
            New-Item -ItemType Directory -Path $Path -Force | Out-Null
        }
        $probe = Join-Path $Path ".write-test-$([guid]::NewGuid().ToString('N')).tmp"
        [System.IO.File]::WriteAllText($probe, 'ok')
        Remove-Item -LiteralPath $probe -Force
        return $true
    }
    catch {
        return $false
    }
}

function Invoke-PrerequisiteChecks {
    <#
    .SYNOPSIS
    Runs every prerequisite check and returns a list of failures (empty
    list = all passed). Each failure carries an actionable message -- never
    a bare "failed", always an ERROR + ACTION pair.
    #>
    param([int]$FrontendPort = 80)

    $failures = @()

    if (-not (Test-DockerCliAvailable)) {
        $failures += [pscustomobject]@{
            Check  = 'Docker CLI'
            Error  = 'Docker CLI was not found on PATH.'
            Action = 'Install Docker Desktop for Windows, then rerun this script from a new PowerShell session.'
        }
    }
    elseif (-not (Test-DockerEngineRunning)) {
        $failures += [pscustomobject]@{
            Check  = 'Docker Engine'
            Error  = 'Docker CLI was found but Docker Engine is not responding.'
            Action = 'Start Docker Desktop, wait until it reports "Engine running", then rerun this script.'
        }
    }
    elseif (-not (Test-DockerComposeV2Available)) {
        $failures += [pscustomobject]@{
            Check  = 'Docker Compose v2'
            Error  = 'Docker Compose v2 (the `docker compose` subcommand) is not available.'
            Action = 'Update Docker Desktop to a version that bundles Compose v2, then rerun this script.'
        }
    }

    if (-not (Test-Path -LiteralPath $Script:ComposeFilePath)) {
        $failures += [pscustomobject]@{
            Check  = 'compose.yml'
            Error  = "compose.yml was not found at $Script:ComposeFilePath."
            Action = 'Re-run this script from a checkout that includes deployment/local-staging/compose.yml.'
        }
    }

    if (-not (Test-Path -LiteralPath $Script:EnvExamplePath)) {
        $failures += [pscustomobject]@{
            Check  = '.env.example'
            Error  = '.env.example was not found next to compose.yml.'
            Action = 'Re-run this script from a checkout that includes deployment/local-staging/.env.example.'
        }
    }

    if (-not (Test-PathWritable -Path $Script:DeploymentRoot)) {
        $failures += [pscustomobject]@{
            Check  = 'Deployment directory writable'
            Error  = "$Script:DeploymentRoot is not writable by the current user."
            Action = 'Run this script from an account with write access to the deployment directory, or move the checkout to a writable location.'
        }
    }

    if (-not (Test-SufficientDiskSpace -Path $Script:DeploymentRoot -MinimumGigabytes 5)) {
        $failures += [pscustomobject]@{
            Check  = 'Disk space'
            Error  = 'Less than 5 GB of free disk space was detected on the deployment drive.'
            Action = 'Free up disk space (container images and the PostgreSQL volume both need room), then rerun this script.'
        }
    }

    # Only fail on the port if it is occupied by something that is not
    # already this installation's own frontend container.
    if (-not (Test-PortAvailable -Port $FrontendPort) -and -not (Test-PortOwnedByThisInstallation -Port $FrontendPort)) {
        $failures += [pscustomobject]@{
            Check  = 'Frontend port'
            Error  = "Port $FrontendPort is already in use by another process."
            Action = "Stop the process using port $FrontendPort, or set LOCAL_STAGING_HTTP_PORT to a different port in .env and rerun."
        }
    }

    return $failures
}

# ---------------------------------------------------------------------------
# Secret generation (cryptographically strong, URL-safe -- see .env.example)
# ---------------------------------------------------------------------------

function New-UrlSafeSecret {
    <#
    .SYNOPSIS
    Base64url-encoded random bytes, mirroring Python's
    `secrets.token_urlsafe()` (already the documented generation method in
    .env.example). Base64url's alphabet (A-Z a-z 0-9 - _) contains no
    URL-reserved character, so the result is always safe to interpolate
    directly into compose.yml's `postgresql+asyncpg://user:PASSWORD@...`
    connection string without additional encoding.
    #>
    param([int]$ByteLength = 48)
    $bytes = [byte[]]::new($ByteLength)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $b64 = [Convert]::ToBase64String($bytes)
    return $b64.TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# ---------------------------------------------------------------------------
# .env generation/preservation
# ---------------------------------------------------------------------------

function Test-EnvFileExists {
    Test-Path -LiteralPath $Script:EnvFilePath
}

function Read-EnvFile {
    <#
    .SYNOPSIS
    Parses an existing .env into a hashtable. Never printed/logged as a
    whole (may contain secrets) -- callers must use individual values
    deliberately and log only non-secret ones.
    #>
    $values = @{}
    if (-not (Test-EnvFileExists)) { return $values }
    foreach ($line in Get-Content -LiteralPath $Script:EnvFilePath) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        $idx = $trimmed.IndexOf('=')
        if ($idx -lt 0) { continue }
        $key = $trimmed.Substring(0, $idx).Trim()
        $value = $trimmed.Substring($idx + 1)
        $values[$key] = $value
    }
    return $values
}

function Get-ConfiguredHttpPort {
    $env = Read-EnvFile
    if ($env.ContainsKey('LOCAL_STAGING_HTTP_PORT') -and $env['LOCAL_STAGING_HTTP_PORT']) {
        return [int]$env['LOCAL_STAGING_HTTP_PORT']
    }
    return 80
}

function Get-MepConfiguredValue {
    <#
    .SYNOPSIS
    Reads one value from the generated .env. PR24D-L3 uses this for
    POSTGRES_DB/USER/PASSWORD when constructing the disposable restore
    rehearsal target. The value is NEVER printed or logged by this
    function -- callers must keep secret values off the console too.
    #>
    param([Parameter(Mandatory)] [string]$Name)
    $envMap = Read-EnvFile
    if (-not $envMap.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace($envMap[$Name])) {
        throw "Required configuration value '$Name' is missing from deployment/local-staging/.env."
    }
    return $envMap[$Name]
}

function New-LocalStagingEnvFile {
    <#
    .SYNOPSIS
    Fresh-install only. Generates POSTGRES_PASSWORD/JWT_SECRET_KEY with
    New-UrlSafeSecret; never called against an existing .env -- reinstall
    and update must preserve existing secrets, never regenerate them.
    #>
    param(
        [Parameter(Mandatory)] [string]$AllowedOrigins,
        [int]$HttpPort = 80
    )
    if (Test-EnvFileExists) {
        throw "New-LocalStagingEnvFile must not be called when .env already exists at $Script:EnvFilePath -- this would silently regenerate secrets."
    }

    $postgresPassword = New-UrlSafeSecret -ByteLength 32
    $jwtSecret = New-UrlSafeSecret -ByteLength 48

    $lines = @(
        '# Generated by install.ps1 -- do not commit. See .env.example for field documentation.',
        "POSTGRES_DB=mep_local_staging_db",
        "POSTGRES_USER=mep_local_staging_user",
        "POSTGRES_PASSWORD=$postgresPassword",
        "JWT_SECRET_KEY=$jwtSecret",
        "ALLOWED_ORIGINS=$AllowedOrigins",
        "LOCAL_STAGING_HTTP_PORT=$HttpPort"
    )
    Set-Content -LiteralPath $Script:EnvFilePath -Value $lines
    Write-InstallLog -Phase 'config' -Message 'Generated new .env with fresh secrets (values never logged).'
}

# ---------------------------------------------------------------------------
# LAN address detection
# ---------------------------------------------------------------------------

function Get-LikelyLanIPv4Addresses {
    <#
    .SYNOPSIS
    Best-effort candidate LAN IPv4 addresses, excluding loopback, APIPA
    (169.254.0.0/16), and container/virtual-adapter-looking interfaces
    where practical. Never modifies networking; returns candidates for the
    operator/caller to choose from rather than silently picking one when
    more than one is plausible.
    #>
    $candidates = @()
    try {
        $addresses = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
            Where-Object { $_.OperationalStatus -eq 'Up' -and $_.NetworkInterfaceType -ne 'Loopback' } |
            Where-Object { $_.Name -notmatch '(?i)docker|veth|vEthernet|virbr|bridge' }
        foreach ($iface in $addresses) {
            foreach ($addrInfo in $iface.GetIPProperties().UnicastAddresses) {
                $addr = $addrInfo.Address
                if ($addr.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { continue }
                if ([System.Net.IPAddress]::IsLoopback($addr)) { continue }
                $text = $addr.ToString()
                if ($text.StartsWith('169.254.')) { continue }
                $candidates += $text
            }
        }
    }
    catch {
        # Best-effort only -- an inability to enumerate interfaces must not
        # crash the installer; caller falls back to prompting the operator.
    }
    return @($candidates | Select-Object -Unique)
}

# ---------------------------------------------------------------------------
# Service/state inspection (Fix Round 1, P2: always --all)
# ---------------------------------------------------------------------------

function Invoke-DockerStateInspection {
    <#
    .SYNOPSIS
    Queries container state for this installation WITHOUT rendering the
    Compose model, so it works before `.env` exists.

    .DESCRIPTION
    Fix Round 2, P1-B. State inspection must not depend on a resource the
    installer has not created yet. Every `docker compose <cmd>` -- `ps`
    included -- first parses and INTERPOLATES compose.yml, so on a fresh
    checkout it fails two different ways:

      docker compose ... --env-file ./.env ps --all
        -> couldn't find env file: .../.env

      docker compose -f compose.yml ps --all      (no --env-file)
        -> error while interpolating services.postgres.environment...:
           required variable POSTGRES_DB is missing a value

    Either failure previously made a genuinely fresh machine classify as
    AMBIGUOUS, so a first install could never proceed. Both were
    reproduced against the real Docker Compose CLI (v5.1.1).

    `docker ps` takes no compose file at all. Scoping it to the
    deterministic Compose project label keeps the query narrow -- it can
    only ever see containers Compose created for THIS project, never
    unrelated containers on the machine.

    Deliberately NOT solved by writing placeholder secrets just to let
    interpolation succeed.
    #>
    $result = Invoke-MepCommand -FilePath 'docker' -Arguments @(
        'ps', '--all',
        '--filter', "label=com.docker.compose.project=$($Script:ComposeProjectName)",
        '--format', 'json'
    ) -AllowNonZeroExit -Phase 'state-inspection'
    return $result
}

function Get-MepServiceStates {
    <#
    .SYNOPSIS
    Returns a hashtable of service name -> container state entry for this
    installation, including stopped/exited containers, and WITHOUT
    requiring `.env` (see Invoke-DockerStateInspection).

    .DESCRIPTION
    Normalizes `docker ps --format json` into the shape the rest of the
    installer consumes: `.Service`, `.State` ("running", "exited", ...)
    and `.Health` ("healthy"/"unhealthy"/""). `docker ps` reports health
    only inside its human Status string (e.g. "Up 2 minutes (healthy)"),
    so it is parsed out of there.

    Returns $null if the query itself failed -- callers treat that as
    "could not determine", never as "nothing is running".
    #>
    $result = Invoke-DockerStateInspection
    if ($result.ExitCode -ne 0) { return $null }
    $map = @{}
    foreach ($line in @($result.Output)) {
        if (-not $line -or "$line".Trim() -eq '') { continue }
        try {
            $entry = "$line" | ConvertFrom-Json
        }
        catch {
            continue
        }
        # `docker ps` emits one JSON object per line; tolerate an array too.
        foreach ($container in @($entry)) {
            $service = Get-DockerLabelValue -Container $container -Label 'com.docker.compose.service'
            if ([string]::IsNullOrWhiteSpace($service)) { continue }

            $status = if ($container.PSObject.Properties.Name -contains 'Status') { "$($container.Status)" } else { '' }
            $health = ''
            if ($status -match '\((healthy|unhealthy|health: starting)\)') { $health = $Matches[1] }

            $state = if ($container.PSObject.Properties.Name -contains 'State') { "$($container.State)" } else { '' }

            $map[$service] = [pscustomobject]@{
                Service = $service
                State   = $state
                Health  = $health
                Status  = $status
                Ports   = if ($container.PSObject.Properties.Name -contains 'Ports') { "$($container.Ports)" } else { '' }
            }
        }
    }
    return $map
}

function Get-DockerLabelValue {
    <#
    .SYNOPSIS
    Extracts one label value from a `docker ps --format json` entry,
    whose Labels field is a single comma-separated "k=v,k=v" string.
    #>
    param($Container, [Parameter(Mandatory)] [string]$Label)
    if ($null -eq $Container -or -not ($Container.PSObject.Properties.Name -contains 'Labels')) { return '' }
    foreach ($pair in ("$($Container.Labels)" -split ',')) {
        $idx = $pair.IndexOf('=')
        if ($idx -lt 1) { continue }
        if ($pair.Substring(0, $idx).Trim() -eq $Label) { return $pair.Substring($idx + 1).Trim() }
    }
    return ''
}

function Test-MepServiceRunning {
    param($ServiceStates, [Parameter(Mandatory)] [string]$Service)
    if ($null -eq $ServiceStates -or -not $ServiceStates.ContainsKey($Service)) { return $false }
    return $ServiceStates[$Service].State -eq 'running'
}

function Test-MepInstallCompleted {
    <#
    .SYNOPSIS
    True only when metadata records a *completed* installation. Metadata
    is written as one of the final install steps, so its absence means the
    installation never finished -- including the case where Administrator
    bootstrap failed (Fix Round 1, P1-B/§8).
    #>
    $metadata = Get-InstallMetadata
    return ($null -ne $metadata) -and ($metadata.PSObject.Properties.Name -contains 'InstallCompleted') -and ($metadata.InstallCompleted -eq $true)
}

function Get-InstallationState {
    <#
    .SYNOPSIS
    Classifies the deployment into FRESH / EXISTING_HEALTHY /
    EXISTING_STOPPED / PARTIAL / AMBIGUOUS by cross-checking .env,
    completed-install metadata, and the full (`--all`) container set --
    never from any single signal (Fix Round 1, P2/§17/§18).

    Fix Round 2 (P1-B): the container set comes from
    Invoke-DockerStateInspection, which does NOT need `.env`. Previously
    this ran `docker compose ps`, which fails on a fresh checkout because
    Compose cannot interpolate compose.yml without the env file the
    installer has not created yet -- so every genuinely fresh machine
    classified as AMBIGUOUS and could never be installed.
    #>
    $envExists = Test-EnvFileExists
    $states = Get-MepServiceStates

    if ($null -eq $states) {
        # The container query itself failed (e.g. the Docker daemon is not
        # reachable): nothing can be concluded safely.
        return 'AMBIGUOUS'
    }

    # DISCOVERY scope: every known service counts here, Redis included. An
    # orphan Redis container still proves this machine is not clean.
    $known = @($Script:KnownServices | Where-Object { $states.ContainsKey($_) })

    if (-not $envExists) {
        if ($known.Count -eq 0) { return 'FRESH' }
        # Containers exist for this project but the configuration that
        # created them is gone -- conflicting signals, never guessed at.
        return 'AMBIGUOUS'
    }

    if ($known.Count -eq 0) {
        # .env exists but nothing was ever created (or everything was
        # removed by `uninstall.ps1`): an incomplete installation, not a
        # healthy one.
        return 'PARTIAL'
    }

    $backendRunning = Test-MepServiceRunning -ServiceStates $states -Service 'backend'
    $frontendRunning = Test-MepServiceRunning -ServiceStates $states -Service 'frontend'
    # OPERATIONAL scope: "any running" is judged against REQUIRED services
    # only, so a leftover Redis container cannot stop an intentionally
    # stopped application from being recognised as EXISTING_STOPPED. An
    # optional service must never dominate the primary application state.
    $anyRequiredRunning = @(
        $Script:RequiredServices | Where-Object { Test-MepServiceRunning -ServiceStates $states -Service $_ }
    ).Count -gt 0

    if (-not (Test-MepInstallCompleted)) {
        # The installer never recorded a completed installation (e.g. it
        # failed at migration or Administrator bootstrap) -- converge it,
        # never treat it as healthy. Redis status cannot weaken this: the
        # Administrator/completion invariant outranks it.
        return 'PARTIAL'
    }

    # Completeness is REQUIRED-service membership, not a count of the full
    # service set. The previous count comparison encoded policy as a magic
    # number and made a failed Redis look like an incomplete installation.
    $missingRequired = @($Script:RequiredServices | Where-Object { -not $states.ContainsKey($_) })
    if ($missingRequired.Count -gt 0) {
        return 'PARTIAL'
    }

    if ($backendRunning -and $frontendRunning) {
        # Redis presence, state, and health are deliberately absent from
        # this condition. A degraded Redis is surfaced by status.ps1, not
        # by demoting the deployment's state.
        return 'EXISTING_HEALTHY'
    }

    if (-not $anyRequiredRunning) {
        return 'EXISTING_STOPPED'
    }

    # A mix: some services up, the application itself not fully up.
    return 'PARTIAL'
}

# ---------------------------------------------------------------------------
# Installation metadata (non-secret only -- never a source of truth for
# database state)
# ---------------------------------------------------------------------------

function Get-InstallMetadata {
    if (-not (Test-Path -LiteralPath $Script:MetadataFilePath)) { return $null }
    try {
        return Get-Content -LiteralPath $Script:MetadataFilePath -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Set-InstallMetadata {
    <#
    .SYNOPSIS
    Records a *successful* installation/update. Callers must only reach
    this after images built, migration succeeded, the application became
    ready, and (on a first install) Administrator bootstrap succeeded.

    .PARAMETER RequireExistingCompletion
    Fix Round 2 (P1-C/§15). Passed by update, which may refresh SourceSha
    and LastUpdatedAtUtc but must never be the operation that transitions
    InstallCompleted from absent/false to true -- that transition belongs
    exclusively to a successful install that satisfied the Administrator
    invariant. This is a structural backstop: update already refuses a
    non-completed installation up front, and this makes the metadata
    writer itself incapable of laundering one.
    #>
    param(
        [Parameter(Mandatory)] [string]$SourceSha,
        [string]$SchemaVersion = '1',
        [switch]$RequireExistingCompletion
    )
    if ($RequireExistingCompletion -and -not (Test-MepInstallCompleted)) {
        throw 'Refusing to record completion metadata: this installation was never completed. Run .\install.ps1 to finish Administrator bootstrap.'
    }
    $existing = Get-InstallMetadata
    $installedAt = if ($existing -and ($existing.PSObject.Properties.Name -contains 'InstalledAtUtc') -and $existing.InstalledAtUtc) {
        $existing.InstalledAtUtc
    }
    else { (Get-Date).ToUniversalTime().ToString('o') }
    $metadata = [pscustomobject]@{
        InstallerSchemaVersion = $SchemaVersion
        InstallCompleted       = $true
        SourceSha              = $SourceSha
        InstalledAtUtc         = $installedAt
        LastUpdatedAtUtc       = (Get-Date).ToUniversalTime().ToString('o')
    }
    $metadata | ConvertTo-Json | Set-Content -LiteralPath $Script:MetadataFilePath
}

# ---------------------------------------------------------------------------
# Git source SHA (best-effort, for installation metadata / migration
# evidence only -- the current mode is a source build, not a digest-pinned
# artifact, and must never claim otherwise)
# ---------------------------------------------------------------------------

function Get-CurrentSourceSha {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $Script:DeploymentRoot)
    Push-Location $repoRoot
    try {
        $result = Invoke-MepCommand -FilePath 'git' -Arguments @('rev-parse', 'HEAD') -AllowNonZeroExit -Phase 'source-sha'
        if ($result.ExitCode -eq 0 -and $result.Output -and $result.Output.Count -gt 0) {
            return "$($result.Output[0])".Trim()
        }
    }
    catch {
        # fall through
    }
    finally {
        Pop-Location
    }
    return 'unknown-local-source'
}
