<#
.SYNOPSIS
PR24D-L3: rehearses restoring a local backup into a DISPOSABLE database
and verifies it. Safe by default -- it never overwrites the live local
Staging/UAT database.

.DESCRIPTION
There is no live-recovery mode in this script. Running

    .\restore.ps1

restores the newest backup into a fresh, timestamped, disposable database
(mep_local_restore_rehearsal_<UTC timestamp>) on the same PostgreSQL
server, verifies it, and drops it again. The live database is never
touched, and there is no flag here that makes it the target.

That is a deliberate scope decision, not an oversight: PR24D-L3's remit
is rehearsal-safe restore. A live-recovery path (stop the application,
back up current state, restore over it, typed confirmation) is a
separate, Owner-approved change -- until then, real recovery is performed
by an operator following the runbook with the Owner in the loop, rather
than by a one-word command that can be run by accident.

All verification is PR24C's, in PR24C's order and unmodified: checksum ->
manifest-derived source identity -> production-target guard -> same-source
guard -> empty-target guard -> pg_restore -> Alembic revision check ->
representative row counts. This wrapper adds no --force, no production
override, and no way to skip a guard.

EVIDENCE CLASS: LOCAL REHEARSAL. A PASS proves the local backup is
restorable. It does NOT satisfy the managed-Staging restore rehearsal
required before Production GO, which remains PENDING.

.PARAMETER Backup
Path to a specific .dump archive. Defaults to the newest backup that has
a manifest beside it.

.PARAMETER KeepRehearsalDatabase
Leave the disposable database in place for investigation instead of
dropping it. Only that database is ever dropped -- never a volume, never
the live database.

.EXAMPLE
.\restore.ps1

.EXAMPLE
.\restore.ps1 -Backup .\backups\mep-postgres-local-staging-20260904T120000Z.dump
#>
[CmdletBinding()]
param(
    [string]$Backup,
    [switch]$KeepRehearsalDatabase
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')
. (Join-Path $PSScriptRoot 'lib/Backup.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Restore Rehearsal ===' -ForegroundColor Cyan

$lock = $null
try {
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun.'
    }
    if (-not (Test-EnvFileExists)) {
        throw 'No existing installation found. Run .\install.ps1 first.'
    }

    # Same shared mutation lock as every other mutating operation.
    $lock = Enter-MepMutationLock
    Invoke-MepRestoreRehearsal -BackupFile $Backup -KeepRehearsalDatabase:$KeepRehearsalDatabase | Out-Null
}
catch {
    Write-InstallLog -Phase 'restore-rehearsal' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Exit-MepMutationLock $lock
}
