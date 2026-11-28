<#
.SYNOPSIS
Register, remove, inspect or run the monthly automatic restore drill.

.DESCRIPTION
-Register (default): task "MEP Monthly Restore Drill", first Sunday of each
month at 03:17 local time, same account/pwsh pattern as schedule-backup.ps1
(registered with the Windows password so it runs when nobody is logged in;
the password is asked once here, never stored or logged; pass -Password to
avoid the prompt). The task itself never prompts.
The task fires every Sunday and run-restore-drill.ps1 -Scheduled skips all but
the first Sunday (or a missed month).

-Unregister removes the task only. -Status shows task, last run and last drill
result. -RunNow runs the drill immediately in this window.
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Register,
    [switch]$Unregister,
    [switch]$Status,
    [switch]$RunNow,
    [securestring]$Password,
    [string]$UserName = "$env:USERDOMAIN\$env:USERNAME"
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')
. (Join-Path $PSScriptRoot 'lib/Backup.ps1')
. (Join-Path $PSScriptRoot 'lib/DriveBackup.ps1')
. (Join-Path $PSScriptRoot 'lib/Schedule.ps1')
. (Join-Path $PSScriptRoot 'lib/RestoreDrill.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Monthly Restore Drill Schedule / ตารางทดสอบกู้คืนรายเดือน ===' -ForegroundColor Cyan

try {
    if (@($Register, $Unregister, $Status, $RunNow | Where-Object { $_ }).Count -gt 1) {
        throw 'Specify only one of -Register, -Unregister, -Status, -RunNow. / ระบุได้เพียงหนึ่งตัวเลือก'
    }
    if ($Unregister) {
        if (Unregister-MepRestoreDrillSchedule) {
            Write-Host 'Restore drill schedule removed. Backups were not touched. / ลบงานแล้ว ไม่แตะต้องไฟล์สำรอง' -ForegroundColor Green
        }
        exit 0
    }
    if ($Status) {
        Show-MepRestoreDrillStatus
        exit 0
    }
    if ($RunNow) {
        & (Join-Path $PSScriptRoot 'run-restore-drill.ps1')
        exit $LASTEXITCODE
    }
    # Default: register.
    if (-not (Test-EnvFileExists)) {
        throw 'No existing installation found. Run .\install.ps1 first. / ยังไม่ได้ติดตั้งระบบ'
    }
    if ($null -eq $Password) {
        $Password = Read-Host -Prompt "Windows password for $UserName (so the task runs when no one is logged in) / รหัสผ่าน Windows" -AsSecureString
    }
    Register-MepRestoreDrillSchedule -Password $Password -UserName $UserName
    Write-Host 'Registered: first Sunday of each month at 03:17. / ลงทะเบียนแล้ว: วันอาทิตย์แรกของเดือน 03:17' -ForegroundColor Green
    Show-MepRestoreDrillStatus
    exit 0
}
catch {
    Write-InstallLog -Phase 'schedule' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
