<#
.SYNOPSIS
PR25A: restore-anywhere. Downloads the latest (or a chosen) backup from the
department's Google Drive onto THIS PC and verifies it with the existing
restore tooling.

.DESCRIPTION
For a fresh Docker-capable PC (or this one after a failure):

    1. .\install.ps1                    (creates the empty deployment)
    2. .\drive-backup.ps1 -Setup        (same OAuth client; consent again)
    3. .\restore-from-drive.ps1         (this script)

The download is checksum-verified against its manifest, then handed to the
SAME code path as .\restore.ps1 (PR24C restore_postgres.py: checksum ->
identity -> production guard -> same-source guard -> empty-target guard ->
pg_restore -> Alembic check -> row counts). It restores into a disposable
verification database and never over the live one -- no guard is bypassed
and no flag here changes that. Promoting a verified copy to live is the
Owner-supervised procedure in the runbook (section 12).

.PARAMETER Name
Exact backup filename (see -ListOnly). Default: the newest on Drive.

.PARAMETER ListOnly
Show what is on Drive and exit.

.PARAMETER KeepRehearsalDatabase
Keep the verified disposable database so it can be promoted (runbook 12.5).
#>
[CmdletBinding()]
param(
    [string]$Name,
    [switch]$ListOnly,
    [switch]$KeepRehearsalDatabase
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')
. (Join-Path $PSScriptRoot 'lib/Backup.ps1')
. (Join-Path $PSScriptRoot 'lib/DriveBackup.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Restore From Google Drive ===' -ForegroundColor Cyan

$lock = $null
try {
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun.'
    }
    if (-not (Test-EnvFileExists)) {
        throw 'No existing installation found. Run .\install.ps1 first.'
    }
    if ($ListOnly) {
        Show-MepDriveBackups | Out-Null
        exit 0
    }
    $lock = Enter-MepMutationLock
    Invoke-MepRestoreFromDrive -Name $Name -KeepRehearsalDatabase:$KeepRehearsalDatabase | Out-Null
}
catch {
    Write-InstallLog -Phase 'drive-restore' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Exit-MepMutationLock $lock
}
