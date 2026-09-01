<#
.SYNOPSIS
PR24D-L2: removes the local Staging/UAT application runtime.

.DESCRIPTION
Default behavior stops and removes the application containers only --
PostgreSQL data, .env/configuration, backups, and installer logs are all
preserved (repository §32). Never runs `docker compose down -v` in the
default path.

Destructive removal (deleting the PostgreSQL/Redis volumes and
configuration) requires BOTH -RemoveData AND typing the confirmation
phrase exactly when prompted -- a single flag is not enough to delete
data irreversibly.

.PARAMETER RemoveData
Opt-in switch for destructive removal. Without it, uninstall.ps1 never
deletes any volume or the .env file.

.EXAMPLE
.\uninstall.ps1
Stops and removes containers; PostgreSQL data and .env are preserved.

.EXAMPLE
.\uninstall.ps1 -RemoveData
Additionally deletes PostgreSQL/Redis data and .env, after an interactive
typed confirmation.
#>
[CmdletBinding()]
param(
    [switch]$RemoveData
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Uninstall ===' -ForegroundColor Cyan
Write-InstallLog -Phase 'uninstall' -Message "uninstall.ps1 started (RemoveData=$RemoveData)."

if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
    Write-Host 'ERROR: Docker Engine is not available. Start Docker Desktop and rerun.' -ForegroundColor Red
    exit 1
}

if (-not (Test-EnvFileExists)) {
    Write-Host 'No existing installation found -- nothing to uninstall.' -ForegroundColor Yellow
    exit 0
}

if ($RemoveData) {
    Write-Host ''
    Write-Host '*** DESTRUCTIVE OPERATION ***' -ForegroundColor Red
    Write-Host 'This will PERMANENTLY DELETE the PostgreSQL database volume, the Redis' -ForegroundColor Red
    Write-Host 'volume, and deployment/local-staging/.env for this local installation.' -ForegroundColor Red
    Write-Host 'This cannot be undone by this script.' -ForegroundColor Red
    Write-Host ''
    $confirmationPhrase = 'DELETE LOCAL STAGING DATA'
    $typed = Read-Host "Type exactly `"$confirmationPhrase`" to continue, or anything else to abort"
    if ($typed -ne $confirmationPhrase) {
        Write-Host 'Confirmation phrase did not match. Aborting -- nothing was deleted.' -ForegroundColor Yellow
        Write-InstallLog -Phase 'uninstall' -Message 'Destructive uninstall aborted (confirmation phrase mismatch).'
        exit 1
    }
}

Write-Host 'Stopping and removing application containers...'
$result = Invoke-DockerCompose -Arguments @('down') -PassThru
if ($result.ExitCode -ne 0) {
    Write-Host 'ERROR: docker compose down reported a failure.' -ForegroundColor Red
    exit 1
}

if (-not $RemoveData) {
    Write-Host 'Containers removed. PostgreSQL data, Redis data, and .env were preserved.' -ForegroundColor Green
    Write-Host 'Run .\install.ps1 to reinstall using the same data and secrets.'
    Write-InstallLog -Phase 'uninstall' -Message 'uninstall.ps1 completed (data preserved).'
    exit 0
}

# -RemoveData confirmed above: now, and only now, remove the named
# volumes explicitly (never a blanket `down -v`, so an operator can never
# reach this by accident via the default path).
Write-Host 'Removing PostgreSQL and Redis volumes...'
$volResult = Invoke-DockerCompose -Arguments @('down', '--volumes') -PassThru
if ($volResult.ExitCode -ne 0) {
    Write-Host 'ERROR: failed to remove volumes.' -ForegroundColor Red
    exit 1
}

Remove-Item -LiteralPath $Script:EnvFilePath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Script:MetadataFilePath -Force -ErrorAction SilentlyContinue

Write-Host 'Data removed.' -ForegroundColor Green
Write-InstallLog -Phase 'uninstall' -Message 'uninstall.ps1 completed (data removed per -RemoveData confirmation).'
