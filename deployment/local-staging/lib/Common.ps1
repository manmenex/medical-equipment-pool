# PR24D-L2 (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §32):
# shared helper functions for install.ps1/start.ps1/stop.ps1/status.ps1/
# update.ps1/uninstall.ps1. Kept as a single module per that section's own
# already-committed target file structure ("a shared lib/Common.ps1") --
# functions below are grouped by concern (logging, Docker/Compose,
# prerequisites, secrets, config, network, lock, metadata) rather than
# split into several files for six thin call sites.
#
# THIS IS NOT A FOURTH ENVIRONMENT. OD-PR24-4's taxonomy (Development,
# Staging/UAT, Production) is unchanged -- see compose.yml's own header.

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# $PSScriptRoot here is deployment/local-staging/lib -- resolve everything
# relative to the deployment directory itself, never the operator's current
# working directory, so scripts behave the same regardless of where they are
# invoked from (repository §15: "scripts must not accidentally create
# separate Compose projects depending on current working directory").
$Script:DeploymentRoot = Split-Path -Parent $PSScriptRoot
$Script:ComposeFilePath = Join-Path $Script:DeploymentRoot 'compose.yml'
$Script:EnvFilePath = Join-Path $Script:DeploymentRoot '.env'
$Script:EnvExamplePath = Join-Path $Script:DeploymentRoot '.env.example'
$Script:LogDirectory = Join-Path $Script:DeploymentRoot 'logs'
$Script:LockFilePath = Join-Path $Script:DeploymentRoot '.install.lock'
$Script:MetadataFilePath = Join-Path $Script:DeploymentRoot '.install-metadata.json'

# Deterministic Compose project identity (repository §15): every script
# below passes this explicitly with -p so install/start/stop/status/update/
# uninstall always operate on the same deployment, never a second project
# accidentally created by directory-dependent Compose defaults.
$Script:ComposeProjectName = 'mep-local-staging'

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
# Safe command execution (never Invoke-Expression; argument arrays only)
# ---------------------------------------------------------------------------

function Invoke-DockerCompose {
    <#
    .SYNOPSIS
    Runs `docker compose` against this installation's compose file/env
    file/project name. Returns the exit code; caller decides whether to
    treat a non-zero exit as fatal (never assumes success).
    #>
    param(
        [Parameter(Mandatory)] [string[]]$Arguments,
        [switch]$PassThru
    )
    $baseArgs = @('compose', '-p', $Script:ComposeProjectName, '-f', $Script:ComposeFilePath, '--env-file', $Script:EnvFilePath)
    $allArgs = $baseArgs + $Arguments
    if ($PassThru) {
        $output = & docker @allArgs 2>&1
        return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $output }
    }
    & docker @allArgs
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $null }
}

function Invoke-DockerComposeConfigOnly {
    <#
    .SYNOPSIS
    `docker compose config` does not require a running daemon -- used by
    prerequisite checks to validate the compose file/env combination is at
    least well-formed before anything is started.
    #>
    $baseArgs = @('compose', '-f', $Script:ComposeFilePath, '--env-file', $Script:EnvFilePath, 'config', '--quiet')
    & docker @baseArgs 2>&1
    return $LASTEXITCODE
}

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

function Test-DockerCliAvailable {
    return $null -ne (Get-Command docker -ErrorAction SilentlyContinue)
}

function Test-DockerEngineRunning {
    docker info > $null 2>&1
    return $LASTEXITCODE -eq 0
}

function Test-DockerComposeV2Available {
    docker compose version > $null 2>&1
    return $LASTEXITCODE -eq 0
}

function Test-PortAvailable {
    <#
    .SYNOPSIS
    Best-effort TCP bind test on all interfaces. Returns $true if the port
    can be bound (i.e. nothing is listening on it right now). Never kills
    or inspects the owning process -- repository §12: "do not kill
    arbitrary processes automatically."
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
    Distinguishes "port is free" from "port is already ours" (repository
    §13: EXISTING_HEALTHY is not the same failure as an unrelated process
    occupying the port).
    #>
    param([Parameter(Mandatory)] [int]$Port)
    $result = Invoke-DockerCompose -Arguments @('ps', '--format', 'json', 'frontend') -PassThru
    if ($result.ExitCode -ne 0 -or -not $result.Output) { return $false }
    foreach ($line in $result.Output) {
        if ($line -match [regex]::Escape(":$Port->") -or $line -match [regex]::Escape("0.0.0.0:$Port")) {
            return $true
        }
    }
    return $false
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
    list = all passed). Each failure carries an actionable message --
    repository §6: never a bare "failed", always an ERROR + ACTION pair.
    #>
    param([int]$FrontendPort = 80)

    $failures = @()

    if (-not (Test-DockerCliAvailable)) {
        $failures += [pscustomobject]@{
            Check   = 'Docker CLI'
            Error   = 'Docker CLI was not found on PATH.'
            Action  = 'Install Docker Desktop for Windows, then rerun this script from a new PowerShell session.'
        }
    }
    elseif (-not (Test-DockerEngineRunning)) {
        $failures += [pscustomobject]@{
            Check   = 'Docker Engine'
            Error   = 'Docker CLI was found but Docker Engine is not responding.'
            Action  = 'Start Docker Desktop, wait until it reports "Engine running", then rerun this script.'
        }
    }
    elseif (-not (Test-DockerComposeV2Available)) {
        $failures += [pscustomobject]@{
            Check   = 'Docker Compose v2'
            Error   = 'Docker Compose v2 (the `docker compose` subcommand) is not available.'
            Action  = 'Update Docker Desktop to a version that bundles Compose v2, then rerun this script.'
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
    .env.example and backend/app/core/config.py's own COOKIE_SECURE
    comment). Base64url's alphabet (A-Z a-z 0-9 - _) contains no
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

function New-LocalStagingEnvFile {
    <#
    .SYNOPSIS
    Fresh-install only. Generates POSTGRES_PASSWORD/JWT_SECRET_KEY with
    New-UrlSafeSecret; never called against an existing .env (repository
    §8/§9: reinstall/update must preserve existing secrets, never
    regenerate them).
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
    Set-Content -LiteralPath $Script:EnvFilePath -Value $lines -NoNewline:$false
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
    more than one is plausible (repository §26).
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
    return $candidates | Select-Object -Unique
}

# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

function Wait-ComposeServicesHealthy {
    <#
    .SYNOPSIS
    Wraps `docker compose up -d --wait`, which uses Compose's own
    health-gated dependency graph (already encodes the PostgreSQL-blocking/
    Redis-non-blocking contract via compose.yml's own depends_on/
    healthcheck) instead of a hand-rolled HTTP polling loop. Bounded by
    -wait-timeout; never loops forever.
    #>
    param(
        [Parameter(Mandatory)] [string[]]$Services,
        [int]$TimeoutSeconds = 180
    )
    $composeArgs = @('up', '-d', '--wait', '--wait-timeout', "$TimeoutSeconds") + $Services
    $result = Invoke-DockerCompose -Arguments $composeArgs -PassThru
    return $result
}

# ---------------------------------------------------------------------------
# Install lock (prevents two install/update operations mutating state
# concurrently -- repository §37)
# ---------------------------------------------------------------------------

function Enter-InstallLock {
    param([int]$StaleAfterMinutes = 60)
    if (Test-Path -LiteralPath $Script:LockFilePath) {
        try {
            $existing = Get-Content -LiteralPath $Script:LockFilePath -Raw | ConvertFrom-Json
            $age = (Get-Date).ToUniversalTime() - [datetime]::Parse($existing.AcquiredAtUtc)
            if ($age.TotalMinutes -lt $StaleAfterMinutes) {
                throw "Another install/update operation appears to be in progress (pid=$($existing.ProcessId), started $($existing.AcquiredAtUtc)). If that process no longer exists, delete $Script:LockFilePath and retry."
            }
            Write-InstallLog -Phase 'lock' -Level 'WARN' -Message "Ignoring stale lock file (older than $StaleAfterMinutes minutes)."
        }
        catch [System.Management.Automation.RuntimeException] {
            throw
        }
        catch {
            Write-InstallLog -Phase 'lock' -Level 'WARN' -Message 'Existing lock file could not be parsed; treating as stale.'
        }
    }
    $lock = [pscustomobject]@{
        ProcessId    = $PID
        AcquiredAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    }
    $lock | ConvertTo-Json | Set-Content -LiteralPath $Script:LockFilePath
}

function Exit-InstallLock {
    if (Test-Path -LiteralPath $Script:LockFilePath) {
        Remove-Item -LiteralPath $Script:LockFilePath -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# Installation metadata (non-secret only -- never a source of truth for
# database state; repository §38)
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
    param(
        [Parameter(Mandatory)] [string]$SourceSha,
        [string]$SchemaVersion = '1'
    )
    $existing = Get-InstallMetadata
    $installedAt = if ($existing -and $existing.InstalledAtUtc) { $existing.InstalledAtUtc } else { (Get-Date).ToUniversalTime().ToString('o') }
    $metadata = [pscustomobject]@{
        InstallerSchemaVersion = $SchemaVersion
        SourceSha              = $SourceSha
        InstalledAtUtc         = $installedAt
        LastUpdatedAtUtc        = (Get-Date).ToUniversalTime().ToString('o')
    }
    $metadata | ConvertTo-Json | Set-Content -LiteralPath $Script:MetadataFilePath
}

# ---------------------------------------------------------------------------
# Installation state detection (repository §13)
# ---------------------------------------------------------------------------

function Get-InstallationState {
    if (-not (Test-EnvFileExists)) {
        return 'FRESH'
    }
    $psResult = Invoke-DockerCompose -Arguments @('ps', '--format', 'json') -PassThru
    if ($psResult.ExitCode -ne 0) {
        return 'AMBIGUOUS'
    }
    $lines = @($psResult.Output | Where-Object { $_ -and $_.Trim() -ne '' })
    if ($lines.Count -eq 0) {
        return 'EXISTING_STOPPED'
    }
    $runningCount = 0
    $unhealthyCount = 0
    foreach ($line in $lines) {
        try {
            $svc = $line | ConvertFrom-Json
        }
        catch {
            continue
        }
        if ($svc.State -eq 'running') { $runningCount++ }
        if ($svc.Health -and $svc.Health -ne 'healthy' -and $svc.Health -ne '') { $unhealthyCount++ }
    }
    if ($runningCount -eq 0) { return 'EXISTING_STOPPED' }
    if ($unhealthyCount -gt 0) { return 'PARTIAL' }
    return 'EXISTING_HEALTHY'
}

# ---------------------------------------------------------------------------
# Git source SHA (best-effort, for installation metadata / migration
# evidence only -- repository §30: current mode is source-build, not a
# digest-pinned artifact, and must never claim otherwise)
# ---------------------------------------------------------------------------

function Get-CurrentSourceSha {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $Script:DeploymentRoot)
    Push-Location $repoRoot
    try {
        $sha = git rev-parse HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $sha) { return $sha.Trim() }
    }
    catch {
        # fall through
    }
    finally {
        Pop-Location
    }
    return 'unknown-local-source'
}
