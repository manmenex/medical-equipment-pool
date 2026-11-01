<#
.SYNOPSIS
PR25A: operate the off-host Google Drive backup.

.DESCRIPTION
Every hourly .\backup.ps1 run also uploads its archive to a folder in the
department's Google Drive. This script is the operator's control panel for
that. The engine is backend/scripts/drive_backup.py, run in the backend
container; see lib/DriveBackup.ps1.

    .\drive-backup.ps1 -Setup     one-time OAuth consent (device flow)
    .\drive-backup.ps1 -Status    last local backup, last upload, pending
                                  count, last error (exit 1 if behind)
    .\drive-backup.ps1 -Upload    upload pending backups now
    .\drive-backup.ps1 -List      backups currently on Drive
    .\drive-backup.ps1            same as -Status

Setup needs an OAuth client of type "TVs and Limited Input devices" created
once in Google Cloud Console (docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md
section 12). Only the narrow drive.file scope is requested.

.PARAMETER ReplaceCredentials
With -Setup: prompt for a new OAuth client ID/secret instead of reusing the
saved ones.
#>
[CmdletBinding()]
param(
    [switch]$Setup,
    [switch]$Status,
    [switch]$Upload,
    [switch]$List,
    [switch]$ReplaceCredentials
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')
. (Join-Path $PSScriptRoot 'lib/Backup.ps1')
. (Join-Path $PSScriptRoot 'lib/DriveBackup.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Google Drive Backup ===' -ForegroundColor Cyan

try {
    $modes = @(@($Setup, $Upload, $List) | Where-Object { $_ })
    if ($modes.Count -gt 1) {
        throw 'Specify only one of -Setup, -Upload, -List (or none for status).'
    }
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun.'
    }
    if (-not (Test-EnvFileExists)) {
        throw 'No existing installation found. Run .\install.ps1 first.'
    }

    if ($Setup) {
        Invoke-MepDriveSetup -ReplaceCredentials:$ReplaceCredentials
        Write-Host 'Drive backup is set up. Run .\drive-backup.ps1 -Upload to send existing backups now.' -ForegroundColor Green
        exit 0
    }
    if ($Upload) {
        $ok = Invoke-MepDriveUpload
        exit $(if ($ok) { 0 } else { 1 })
    }
    if ($List) {
        $ok = Show-MepDriveBackups
        exit $(if ($ok) { 0 } else { 1 })
    }
    $ok = Show-MepDriveStatus
    exit $(if ($ok) { 0 } else { 1 })
}
catch {
    Write-InstallLog -Phase 'drive' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
