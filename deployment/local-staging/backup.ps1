<#
.SYNOPSIS
PR24D-L3: creates one verified backup of the local Staging/UAT database.

.DESCRIPTION
A thin lock-holding wrapper. All backup, checksum, manifest and retention
work is done by the existing PR24C tooling (backend/scripts/
backup_postgres.py and prune_backups.py), invoked unchanged -- this
script contains no backup engine of its own.

The application does NOT need to be stopped. PR24C takes a single
transactionally-consistent logical backup with `pg_dump --format=custom`,
so a running backend does not compromise the snapshot.

Backups are written to deployment/local-staging/backups/ on the host --
outside the PostgreSQL Docker volume, so they survive stop/start and the
default uninstall, and can be copied elsewhere with an ordinary file
copy. Retention is PR24C's Owner-approved 30 days.

No secret is ever printed: not the database password, not JWT_SECRET_KEY,
not a credential-bearing DATABASE_URL.

.EXAMPLE
.\backup.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')
. (Join-Path $PSScriptRoot 'lib/Backup.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Backup ===' -ForegroundColor Cyan

$lock = $null
try {
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun.'
    }
    if (-not (Test-EnvFileExists)) {
        throw 'No existing installation found. Run .\install.ps1 first; there is nothing to back up.'
    }

    # The SAME shared mutation lock every other mutating script uses -- a
    # backup must not race an install, update, start, stop or uninstall.
    # There is deliberately no backup-specific lock.
    $lock = Enter-MepMutationLock
    Invoke-MepBackup -Reason 'manual' | Out-Null
}
catch {
    Write-InstallLog -Phase 'backup' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Exit-MepMutationLock $lock
}
