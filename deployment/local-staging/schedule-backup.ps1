<#
.SYNOPSIS
PR24D: register, remove, or inspect the recurring local Staging/UAT backup.

.DESCRIPTION
Schedules the EXISTING .\backup.ps1 with Windows Task Scheduler. There is no
second backup implementation here and no way to bypass anything: every
scheduled run goes through backup.ps1, which takes the same deployment
mutation lock as install/update/stop, produces a verified archive with its
manifest, and prunes to the retention policy.

WHY THIS EXISTS. docs/evidence/PR24D_LOCAL_STAGING_WINDOWS_VALIDATION.md
records "RPO <= 1 hour: NOT PROVEN" for a simple reason -- nothing backed up
on a schedule, so every backup was whenever an operator remembered. An
unattended hourly backup is the smallest change that makes an RPO claim
provable at all. It does not by itself PROVE one: that needs the schedule to
be observed actually succeeding over time, which is an operational
observation, not a code change.

RETENTION. An hourly cadence keeps 720 archives under a flat 30-day window.
The retention policy is therefore tiered (PR24C's prune_backups.py, which
backup.ps1 already calls): every archive for 48 hours, then one per UTC day
up to 30 days. That is roughly 78 archives, while keeping hour-level
granularity across the two days most recoveries actually reach back into.

LIMITATION, stated plainly rather than discovered later. The task runs as the
CURRENT USER with an interactive logon, because Docker Desktop runs inside
that user's session -- a task running as SYSTEM could not reach the Docker
daemon at all. Backups therefore only happen while that user is logged in. On
a dedicated always-on Staging/UAT PC that is usually fine; if the machine is
logged out or shut down, no backup runs, and the schedule silently covers
nothing. Check .\schedule-backup.ps1 (no arguments) periodically: it reports
the last run and whether it succeeded.

.PARAMETER Install
Register (or replace) the recurring task.

.PARAMETER Remove
Remove the task. Existing backups on disk are never touched.

.PARAMETER IntervalHours
Hours between backups, 1-24. Defaults to 1. A larger value is a deliberate,
stated weakening of the RPO target.

.EXAMPLE
.\schedule-backup.ps1
Shows whether a schedule exists and whether it is succeeding.

.EXAMPLE
.\schedule-backup.ps1 -Install

.EXAMPLE
.\schedule-backup.ps1 -Remove
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Remove,
    [int]$IntervalHours = 1
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Schedule.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Backup Schedule ===' -ForegroundColor Cyan

try {
    if ($Install -and $Remove) {
        throw 'Specify -Install or -Remove, not both.'
    }

    if ($Remove) {
        if (Unregister-MepBackupSchedule) {
            Write-Host 'Backup schedule removed. Existing backups on disk were not touched.' -ForegroundColor Green
            Write-Host 'Backups are now manual again; an RPO target cannot be claimed.' -ForegroundColor Yellow
        }
        exit 0
    }

    if ($Install) {
        if (-not (Test-EnvFileExists)) {
            throw 'No existing installation found. Run .\install.ps1 first; there is nothing to schedule backups for.'
        }
        $hours = Register-MepBackupSchedule -IntervalHours $IntervalHours
        Write-Host ''
        Write-Host "Backup schedule registered: every $hours hour(s)." -ForegroundColor Green
        Write-Host '  Each run executes .\backup.ps1 -- same lock, same verification, same retention.'
        Write-Host '  Runs only while this Windows user is logged in (Docker Desktop lives in that session).' -ForegroundColor Yellow
        Write-Host ''
        Show-MepBackupScheduleStatus | Out-Null
        exit 0
    }

    # No switch: report.
    Show-MepBackupScheduleStatus | Out-Null
    exit 0
}
catch {
    Write-InstallLog -Phase 'schedule' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
