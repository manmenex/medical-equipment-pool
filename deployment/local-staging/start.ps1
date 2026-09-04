<#
.SYNOPSIS
PR24D-L2: starts an already-installed local Staging/UAT deployment.

.DESCRIPTION
Does NOT generate or regenerate secrets, and does NOT run a migration --
migrations belong to install.ps1/update.ps1 only. Requires an existing
.env; if none exists, directs the operator to .\install.ps1 instead of
silently creating one. Holds the shared deployment mutation lock for the
duration, so it can never race an install, update, or uninstall.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Start ===' -ForegroundColor Cyan
Write-InstallLog -Phase 'start' -Message 'start.ps1 started.'

$lock = $null
try {
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun .\start.ps1.'
    }

    $lock = Enter-MepMutationLock
    Invoke-MepStart

    $port = Get-ConfiguredHttpPort
    $lanCandidates = Get-LikelyLanIPv4Addresses
    Write-Host 'Application is ready.' -ForegroundColor Green
    if ($lanCandidates.Count -eq 0) {
        Write-Host "  http://localhost:$port"
    }
    else {
        foreach ($addr in $lanCandidates) { Write-Host "  http://${addr}:$port" }
    }
}
catch {
    Write-InstallLog -Phase 'start' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Exit-MepMutationLock $lock
}
