# PR24D: register the existing backup.ps1 with Windows Task Scheduler so a
# backup happens on a cadence instead of only when an operator remembers.
#
# The real Windows validation (docs/evidence/PR24D_LOCAL_STAGING_WINDOWS_VALIDATION.md)
# recorded RPO <= 1 hour as NOT PROVEN, for the plain reason that no
# scheduled backup existed: both backups taken were operator-initiated. An
# hourly schedule is the smallest thing that can make that claim provable.
#
# This module only ever SCHEDULES the existing entry script. It contains no
# second backup implementation, no alternative retention policy, and no way
# to bypass the mutation lock: every run goes through .\backup.ps1, which
# takes the same lock as install/update/stop and fails closed if another
# operation owns it.

$Script:BackupTaskName = 'MEP Local Staging Backup'
$Script:BackupTaskPath = '\'

function Get-MepBackupTaskName {
    return $Script:BackupTaskName
}

function Get-MepPwshPath {
    <#
    .SYNOPSIS
    Absolute path to the PowerShell 7 executable the scheduled task must
    run.

    .DESCRIPTION
    Explicitly pwsh, never powershell.exe. Under Windows PowerShell 5.1
    `$ErrorActionPreference = 'Stop'` turns `docker compose`'s ordinary
    stderr progress lines into terminating errors, so a task launched with
    5.1 would fail every hour with a message that is not an error at all
    ("Container mep-local-staging-postgres-1 Running"). That cost real
    operator time once already; a schedule that does it unattended, hourly,
    would be worse.
    #>
    $current = (Get-Process -Id $PID -ErrorAction SilentlyContinue).Path
    if ($current -and (Split-Path -Leaf $current) -in @('pwsh', 'pwsh.exe')) {
        return $current
    }
    $command = Get-Command -Name 'pwsh' -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) { return $command.Source }
    throw (New-MepFailure @'
PowerShell 7 (pwsh) was not found on PATH, so a scheduled backup cannot be
registered against it.
ACTION: Install PowerShell 7 and rerun. The task must run pwsh, not
powershell.exe -- under Windows PowerShell 5.1 the backup fails on docker's
ordinary progress output.
'@)
}

function Get-MepBackupScriptPath {
    $path = Join-Path $Script:DeploymentRoot 'backup.ps1'
    if (-not (Test-Path -LiteralPath $path)) {
        throw (New-MepFailure "backup.ps1 was not found at $path; refusing to register a schedule that would point at nothing.")
    }
    return $path
}

function Get-MepBackupSchedule {
    <#
    .SYNOPSIS
    The registered task, or $null. Never throws merely because the task
    does not exist -- "not scheduled" is a normal state to report.
    #>
    return Get-ScheduledTask -TaskName $Script:BackupTaskName -ErrorAction SilentlyContinue
}

function Register-MepBackupSchedule {
    <#
    .SYNOPSIS
    Creates (or replaces) the recurring backup task.

    .PARAMETER IntervalHours
    How often to back up. Defaults to 1, which is what makes an RPO of one
    hour achievable at all; a larger value is a deliberate, stated
    weakening of that target.
    #>
    param([int]$IntervalHours = 1)

    if ($IntervalHours -lt 1 -or $IntervalHours -gt 24) {
        throw (New-MepFailure "IntervalHours must be between 1 and 24; got $IntervalHours.")
    }

    $pwshPath = Get-MepPwshPath
    $backupScript = Get-MepBackupScriptPath

    # -NonInteractive and a hidden window: this runs unattended, and must
    # never block on a prompt or flash a console at the operator every hour.
    $action = New-ScheduledTaskAction -Execute $pwshPath `
        -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$backupScript`"" `
        -WorkingDirectory $Script:DeploymentRoot

    # Repetition runs from the next whole interval, indefinitely.
    $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(5)) `
        -RepetitionInterval (New-TimeSpan -Hours $IntervalHours)

    # IgnoreNew, not Parallel: a slow backup must never have the next hour's
    # run stack on top of it. backup.ps1 would fail closed on the mutation
    # lock anyway, but not even starting is cleaner than an hourly failure
    # in the log.
    #
    # ExecutionTimeLimit is deliberately shorter than a day but longer than
    # any plausible backup, so a wedged run is reaped rather than blocking
    # every subsequent one.
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)

    # Interactive, as the current user: Docker Desktop runs inside the
    # operator's own session, so a task running as SYSTEM could not reach
    # the daemon at all. The cost is stated plainly in the runbook -- these
    # backups only happen while that user is logged in.
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask -TaskName $Script:BackupTaskName `
        -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
        -Description "Runs deployment/local-staging/backup.ps1 every $IntervalHours hour(s). Registered by schedule-backup.ps1." `
        -Force | Out-Null

    Write-InstallLog -Phase 'schedule' -Message "Backup schedule registered (interval_hours=$IntervalHours, task='$Script:BackupTaskName')."
    return $IntervalHours
}

function Unregister-MepBackupSchedule {
    <#
    .SYNOPSIS
    Removes the task. Scoped to exactly the task this module registers --
    never a wildcard, never another task.
    #>
    $existing = Get-MepBackupSchedule
    if ($null -eq $existing) {
        Write-Host 'No backup schedule is registered; nothing to remove.'
        return $false
    }
    Unregister-ScheduledTask -TaskName $Script:BackupTaskName -Confirm:$false
    Write-InstallLog -Phase 'schedule' -Message "Backup schedule removed (task='$Script:BackupTaskName')."
    return $true
}

function Show-MepBackupScheduleStatus {
    <#
    .SYNOPSIS
    Reports whether a schedule exists and, if it does, whether it is
    actually succeeding. A registered task that fails every hour is worse
    than no task, because it looks like coverage.
    #>
    $task = Get-MepBackupSchedule
    if ($null -eq $task) {
        Write-Host 'Backup schedule: NOT REGISTERED' -ForegroundColor Yellow
        Write-Host '  Run .\schedule-backup.ps1 -Install to back up automatically.'
        Write-Host '  Until then every backup is manual, and an RPO target cannot be claimed.'
        return $false
    }

    Write-Host "Backup schedule: REGISTERED ($($task.State))" -ForegroundColor Green
    $info = Get-ScheduledTaskInfo -TaskName $Script:BackupTaskName -ErrorAction SilentlyContinue
    if ($info) {
        Write-Host "  Last run:  $($info.LastRunTime)"
        Write-Host "  Next run:  $($info.NextRunTime)"
        # 0 = success; 267011 is "task has not yet run", which is not a failure.
        $result = $info.LastTaskResult
        if ($result -eq 0) {
            Write-Host "  Last result: SUCCESS" -ForegroundColor Green
        }
        elseif ($result -eq 267011) {
            Write-Host "  Last result: has not run yet"
        }
        else {
            Write-Host "  Last result: FAILED (code $result)" -ForegroundColor Red
            Write-Host '  A registered schedule that fails is not backup coverage. Check logs/install-operations.log.' -ForegroundColor Yellow
        }
    }
    return $true
}
