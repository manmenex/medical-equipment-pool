<#
.SYNOPSIS
DEMO-ONLY: turn the legacy pool Google Sheet shadow sync on or off.

.DESCRIPTION
Governance 2026-10-21 (docs/DECISION_LOG.md). Mirrors dispatches and returns
from the pool team's current Google Sheet into this system so the normal flow
runs on real traffic during the demo. Read-only against the sheet. MUST be
switched off (-Disable) before Production go-live.

    .\enable-legacy-sheet-sync.ps1 -KeyFile C:\path\key.json -SpreadsheetId <id>
    .\enable-legacy-sheet-sync.ps1 -Status
    .\enable-legacy-sheet-sync.ps1 -Disable

Enabling first runs a dry run (reads the sheet, writes nothing) and only turns
the sync on if it succeeds. The key file is copied into
deployment/local-staging/secrets/legacy-sheet/ with an owner-only ACL;
-Disable stops the service and deletes it.

.PARAMETER KeyFile
Path to the service-account JSON key the Owner placed on this host.
.PARAMETER SpreadsheetId
The id in the sheet URL (docs.google.com/spreadsheets/d/<id>/edit).
.PARAMETER StartDate
Optional YYYY-MM-DD (Bangkok). Default: rolling now-7 days. Older rows go to
the review page as OP_TOO_OLD.
.PARAMETER EmployeeCode
Employee code of the Equipment Pool Staff user the operations are recorded
under (must already exist). Default LEGACY-SYNC.
#>
[CmdletBinding(DefaultParameterSetName = 'Enable')]
param(
    [Parameter(ParameterSetName = 'Enable', Mandatory)] [string]$KeyFile,
    [Parameter(ParameterSetName = 'Enable', Mandatory)] [string]$SpreadsheetId,
    [Parameter(ParameterSetName = 'Enable')] [string]$StartDate = '',
    [Parameter(ParameterSetName = 'Enable')] [string]$EmployeeCode = 'LEGACY-SYNC',
    [Parameter(ParameterSetName = 'Enable')] [ValidateRange(60, 86400)] [int]$IntervalSeconds = 300,
    [Parameter(ParameterSetName = 'Disable', Mandatory)] [switch]$Disable,
    [Parameter(ParameterSetName = 'Status', Mandatory)] [switch]$Status
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')
. (Join-Path $PSScriptRoot 'lib/LegacySheetSync.ps1')

Write-Host ''
Write-Host '=== Legacy pool sheet shadow sync (DEMO ONLY) ===' -ForegroundColor Cyan

try {
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun.'
    }
    if (-not (Test-EnvFileExists)) {
        throw 'No existing installation found. Run .\install.ps1 first.'
    }
    if ($Disable) { Disable-MepLegacySheetSync; exit 0 }
    if ($Status) { Show-MepLegacySheetSyncStatus; exit 0 }
    Enable-MepLegacySheetSync -KeyFile $KeyFile -SpreadsheetId $SpreadsheetId -StartDate $StartDate `
        -EmployeeCode $EmployeeCode -IntervalSeconds $IntervalSeconds
    exit 0
}
catch {
    Write-InstallLog -Phase 'legacy-sync' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
