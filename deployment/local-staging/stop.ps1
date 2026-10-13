<#
.SYNOPSIS
PR24D-L2: stops the local Staging/UAT application stack safely.

.DESCRIPTION
Uses `docker compose stop` (containers stopped, not removed) -- never
`down -v`: the PostgreSQL volume, configuration, and any backups are
preserved. Repeatable: stopping an already-stopped installation is a
no-op, not an error. Holds the shared deployment mutation lock so it can
never race an install or update.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Stop ===' -ForegroundColor Cyan
Write-InstallLog -Phase 'stop' -Message 'stop.ps1 started.'

$lock = $null
try {
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun .\stop.ps1.'
    }

    $lock = Enter-MepMutationLock
    Invoke-MepStop
    Write-Host 'Stopped. PostgreSQL data, configuration, and backups were preserved.' -ForegroundColor Green
}
catch {
    Write-InstallLog -Phase 'stop' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Exit-MepMutationLock $lock
}
