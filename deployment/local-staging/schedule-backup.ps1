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

WHO IT RUNS AS (PR25A). The task is registered with the Windows account's
PASSWORD, so it runs whether or not anyone is logged in (Task Scheduler
starts it in a non-interactive session), the same way the Owner's other
tools on this host are registered. You are prompted for the password at
-Install; it is passed straight to Task Scheduler and never stored, logged
or echoed. It still needs Docker Desktop's engine to be running: Docker
Desktop starts when the account signs in at boot, so keep it signed in (or
auto-logon) and set Docker Desktop to start with Windows. Windows
credential changes (password rotation) require re-running -Install.
S4U (no password) was not chosen because Docker access under it cannot be
verified from the repository.

WHEN. Runs at :15 past each hour -- deliberately not :00 or :30, which the
other tools on this host use to reach N Smart.

Each run is backup.ps1: local backup first, then the Google Drive upload
(PR25A). A Drive failure never fails the backup; check
.\drive-backup.ps1 -Status as well as this script's report.

.PARAMETER Install
Register (or replace) the recurring task.

.PARAMETER UserName
Windows account the task runs as. Default: the current user. You are asked
for its password.

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
    [int]$IntervalHours = 1,
    [string]$UserName = "$env:USERDOMAIN\$env:USERNAME"
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
        $securePassword = Read-Host -Prompt "Windows password for $UserName (needed so the task runs when no one is logged in)" -AsSecureString
        $hours = Register-MepBackupSchedule -IntervalHours $IntervalHours -Password $securePassword -UserName $UserName
        Write-Host ''
        Write-Host "Backup schedule registered: every $hours hour(s), at :15 past the hour." -ForegroundColor Green
        Write-Host '  Each run executes .\backup.ps1 -- same lock, same verification, same retention, then the Drive upload.'
        Write-Host '  Runs whether or not anyone is logged in, as long as Docker Desktop is running.' -ForegroundColor Yellow
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
