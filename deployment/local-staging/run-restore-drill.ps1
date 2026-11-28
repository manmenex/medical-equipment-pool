<#
.SYNOPSIS
Monthly restore drill: restores the newest backup into a DISPOSABLE database,
verifies it, drops it, and records the result. Never touches the live DB.

.DESCRIPTION
Called by the "MEP Monthly Restore Drill" task (see schedule-restore-drill.ps1)
or by hand. Uses the newest Google Drive backup when Drive is configured,
otherwise the newest local backup. Goes through the same code as
restore-from-drive.ps1 / restore.ps1 (PR24C guards unchanged), so there is no
-Force/-NonInteractive flag to add: neither script prompts.

Result: logs\restore-drill\YYYY-MM.json (counts only, no data values) plus one
line in logs\install-operations.log. Exit code 1 on FAIL so Task Scheduler
shows the failure.

.PARAMETER Scheduled
Set by the scheduled task. Skips Sundays that are not the first Sunday of the
month (unless this month has no PASS yet, so a FAIL is retried).
#>
#Requires -Version 7.0
[CmdletBinding()]
param([switch]$Scheduled)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')
. (Join-Path $PSScriptRoot 'lib/Backup.ps1')
. (Join-Path $PSScriptRoot 'lib/DriveBackup.ps1')
. (Join-Path $PSScriptRoot 'lib/Schedule.ps1')
. (Join-Path $PSScriptRoot 'lib/RestoreDrill.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Monthly Restore Drill / ทดสอบกู้คืนอัตโนมัติ ===' -ForegroundColor Cyan

$lock = $null
try {
    if ($Scheduled -and -not (Test-MepRestoreDrillDue -ResultExistsThisMonth (Test-MepRestoreDrillMonthPassed))) {
        Write-Host 'Not the first Sunday of the month; skipping. / ไม่ใช่วันอาทิตย์แรกของเดือน ข้ามการทดสอบ'
        exit 0
    }
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun. / Docker ไม่พร้อมใช้งาน'
    }
    if (-not (Test-EnvFileExists)) {
        throw 'No existing installation found. Run .\install.ps1 first.'
    }
    # Waits for the hourly backup (starts at :15) instead of failing at once.
    $lock = Enter-MepMutationLock -TimeoutMilliseconds $Script:RestoreDrillLockWaitMilliseconds
    $result = Invoke-MepRestoreDrill
    if ($result.result -eq 'PASS') {
        Write-Host "Restore drill: PASS ($($result.source), $($result.elapsed_seconds)s) / ทดสอบกู้คืนผ่าน" -ForegroundColor Green
        exit 0
    }
    Write-Host "Restore drill: FAIL / ทดสอบกู้คืนไม่ผ่าน -- $($result.error)" -ForegroundColor Red
    exit 1
}
catch {
    Write-InstallLog -Phase 'restore-drill' -Level 'ERROR' -Message "Restore drill FAIL (did not run): $($_.Exception.Message)"
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Exit-MepMutationLock $lock
}
