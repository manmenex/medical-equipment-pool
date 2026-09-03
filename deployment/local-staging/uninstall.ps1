<#
.SYNOPSIS
PR24D-L2: removes the local Staging/UAT application runtime.

.DESCRIPTION
Default behavior stops and removes the application containers only --
PostgreSQL data, .env/configuration, backups, and installer logs are all
preserved. Never runs `docker compose down -v` in the default path.
Holds the shared deployment mutation lock so it can never race an install
or update.

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
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Uninstall ===' -ForegroundColor Cyan
Write-InstallLog -Phase 'uninstall' -Message "uninstall.ps1 started (RemoveData=$RemoveData)."

$lock = $null
try {
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun.'
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

    $lock = Enter-MepMutationLock
    Invoke-MepUninstall -RemoveData:$RemoveData

    if ($RemoveData) {
        Write-Host 'Data removed.' -ForegroundColor Green
    }
    else {
        Write-Host 'Containers removed. PostgreSQL data, Redis data, and .env were preserved.' -ForegroundColor Green
        Write-Host 'Run .\install.ps1 to reinstall using the same data and secrets.'
    }
}
catch {
    Write-InstallLog -Phase 'uninstall' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Exit-MepMutationLock $lock
}
