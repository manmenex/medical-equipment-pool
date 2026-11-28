# Monthly automatic restore drill: scheduling + orchestration.
#
# SAFETY. The drill adds NO restore logic. It calls the existing
# Invoke-MepRestoreFromDrive / Invoke-MepRestoreRehearsal, which restore into
# a DISPOSABLE, timestamped database through PR24C's restore_postgres.py with
# every guard intact. It never passes a live-database target, never passes
# -KeepRehearsalDatabase (so the disposable database is always dropped by the
# rehearsal's own finally block), never runs `down -v`, and never deletes a
# volume or a backup. The result file holds COUNTS only -- no row values, no
# connection strings, no secrets.
#
# Requires lib/Common.ps1, Operations.ps1, Backup.ps1, DriveBackup.ps1 and
# Schedule.ps1 to be dot-sourced first.

Set-StrictMode -Version Latest

$Script:RestoreDrillTaskName = 'MEP Monthly Restore Drill'
$Script:RestoreDrillHour = 3
$Script:RestoreDrillMinute = 17
# Waiting for the shared mutation lock: the hourly backup starts at :15 and
# the drill at 03:17, so the lock is normally held when the drill starts.
$Script:RestoreDrillLockWaitMilliseconds = 20 * 60 * 1000

function Get-MepRestoreDrillTaskName { return $Script:RestoreDrillTaskName }

function Get-MepRestoreDrillRoot {
    return (Join-Path $Script:LogDirectory 'restore-drill')
}

function Get-MepRestoreDrillResultPath {
    param([datetime]$Now = (Get-Date))
    return (Join-Path (Get-MepRestoreDrillRoot) ($Now.ToString('yyyy-MM') + '.json'))
}

function Test-MepRestoreDrillDue {
    <#
    .SYNOPSIS
    Task Scheduler has no "first Sunday" trigger via the cmdlets, so the task
    fires every Sunday and the scheduled run decides here. Due = first Sunday
    of the month (day 1-7), or a catch-up: this month has no result yet (the
    first Sunday was missed, e.g. the host was off).
    #>
    param([datetime]$Now = (Get-Date), [bool]$ResultExistsThisMonth = $false)
    if ($Now.DayOfWeek -eq [DayOfWeek]::Sunday -and $Now.Day -le 7) { return $true }
    return (-not $ResultExistsThisMonth)
}

function Test-MepRestoreDrillMonthPassed {
    <#
    .SYNOPSIS
    A month counts as done only when its result file says PASS. A FAIL (or an
    unreadable file) is retried on the next Sunday; the FAIL file is kept
    until a later run overwrites it.
    #>
    param([datetime]$Now = (Get-Date))
    $path = Get-MepRestoreDrillResultPath -Now $Now
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    try { return ((Get-Content -LiteralPath $path -Raw | ConvertFrom-Json).result -eq 'PASS') } catch { return $false }
}

function Remove-MepLeftoverRestoreDatabases {
    <#
    .SYNOPSIS
    Drops disposable rehearsal databases left by an earlier drill that was
    killed (e.g. by the task's time limit). Only names that match the
    rehearsal's own generated form (prefix + [a-z0-9_]) and are not the live
    database are ever dropped. Caller holds the mutation lock.
    #>
    $live = Get-MepConfiguredValue -Name 'POSTGRES_DB'
    $prefix = $Script:RehearsalDatabasePrefix
    Start-MepPostgres
    $list = Invoke-MepPsql -Sql "SELECT datname FROM pg_database WHERE datname LIKE '$prefix%'" -AllowNonZeroExit
    if ($list.ExitCode -ne 0) { Write-InstallLog -Phase 'restore-drill' -Level 'WARN' -Message 'Could not list leftover rehearsal databases; continuing.'; return 0 }
    $dropped = 0
    foreach ($line in @($list.Output)) {
        $name = "$line".Trim()
        if ($name -cnotmatch '^mep_local_restore_rehearsal_[a-z0-9_]+$') { continue }
        if (-not $name.StartsWith($prefix) -or $name -eq $live) { continue }
        $drop = Invoke-MepPsql -Sql "DROP DATABASE IF EXISTS $name" -AllowNonZeroExit
        if ($drop.ExitCode -eq 0) { $dropped++ }
        else { Write-InstallLog -Phase 'restore-drill' -Level 'WARN' -Message "Could not drop leftover rehearsal database $name." }
    }
    if ($dropped -gt 0) { Write-InstallLog -Phase 'restore-drill' -Message "Dropped $dropped leftover rehearsal database(s) from an earlier drill." }
    return $dropped
}

function ConvertFrom-MepRestoreDrillOutput {
    <#
    .SYNOPSIS
    Extracts ONLY non-sensitive facts from PR24C restore output: backup file
    name, checksum verdict, Alembic revision, per-table row COUNTS.
    #>
    param([AllowNull()] $Output)
    $text = (@($Output) | ForEach-Object { "$_" }) -join "`n"
    $file = $null
    $m = [regex]::Match($text, 'verifying checksum of\s+\S*?(mep-postgres-[a-z0-9]+-\d{8}T\d{6}Z\.dump)')
    if ($m.Success) { $file = $m.Groups[1].Value }
    $revision = $null
    $m = [regex]::Match($text, 'Alembic revision verified:\s*([A-Za-z0-9_]+)')
    if ($m.Success) { $revision = $m.Groups[1].Value }
    $counts = [ordered]@{}
    $m = [regex]::Match($text, 'restored row counts:\s*\{([^}]*)\}')
    if ($m.Success) {
        foreach ($c in [regex]::Matches($m.Groups[1].Value, "['""]([A-Za-z0-9_.]+)['""]\s*:\s*(\d+)")) {
            $counts[$c.Groups[1].Value] = [int64]$c.Groups[2].Value
        }
    }
    return [pscustomobject]@{
        BackupFile      = $file
        ChecksumOk      = ($text -match '\[restore\]\s+checksum OK')
        AlembicRevision = $revision
        RowCounts       = $counts
    }
}

function New-MepRestoreDrillResult {
    param(
        [Parameter(Mandatory)] [datetime]$Started,
        [Parameter(Mandatory)] [datetime]$Finished,
        [string]$Source,
        $Parsed,
        [string]$ErrorMessage
    )
    $checksum = if ($Parsed -and $Parsed.ChecksumOk) { 'PASS' } else { 'FAIL' }
    $revision = if ($Parsed) { $Parsed.AlembicRevision } else { $null }
    $counts = if ($Parsed) { $Parsed.RowCounts } else { [ordered]@{} }
    $pass = (-not $ErrorMessage) -and $checksum -eq 'PASS' -and $revision -and @($counts.Keys).Count -gt 0
    $safeError = $null
    if ($ErrorMessage) {
        # Bounded, with any URL (possible credential carrier) removed.
        $safeError = ($ErrorMessage -replace '\w+(\+\w+)?://\S+', '[url removed]')
        if ($safeError.Length -gt 300) { $safeError = $safeError.Substring(0, 300) }
    }
    return [ordered]@{
        started          = $Started.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        finished         = $Finished.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        source           = $Source
        backup_file      = $(if ($Parsed) { $Parsed.BackupFile } else { $null })
        elapsed_seconds  = [Math]::Round(($Finished - $Started).TotalSeconds, 1)
        checksum         = $checksum
        alembic_revision = $revision
        row_counts       = $counts
        result           = $(if ($pass) { 'PASS' } else { 'FAIL' })
        error            = $safeError
    }
}

function Write-MepRestoreDrillResult {
    param([Parameter(Mandatory)] $Result, [datetime]$Now = (Get-Date))
    $root = Get-MepRestoreDrillRoot
    if (-not (Test-Path -LiteralPath $root)) { New-Item -ItemType Directory -Path $root -Force | Out-Null }
    $path = Get-MepRestoreDrillResultPath -Now $Now
    ($Result | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $path -Encoding utf8
    return $path
}

function Get-MepLastRestoreDrillResult {
    $root = Get-MepRestoreDrillRoot
    if (-not (Test-Path -LiteralPath $root)) { return $null }
    $file = Get-ChildItem -LiteralPath $root -Filter '????-??.json' -File -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $file) { return $null }
    try { return (Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json) } catch { return $null }
}

function Invoke-MepRestoreDrill {
    <#
    .SYNOPSIS
    Runs one drill and records the result. Caller holds the mutation lock.
    Never throws for a drill failure: it records FAIL and returns the result
    (the script turns FAIL into a non-zero exit code).
    #>
    $started = Get-Date
    $source = if (Test-MepDriveConfigured) { 'drive' } else { 'local' }
    $parsed = $null
    $err = $null
    try { Remove-MepLeftoverRestoreDatabases | Out-Null }
    catch { Write-InstallLog -Phase 'restore-drill' -Level 'WARN' -Message 'Leftover rehearsal database cleanup failed; continuing.' }
    try {
        if ($source -eq 'drive') {
            $run = Invoke-MepRestoreFromDrive
        }
        else {
            Write-Host 'Drive is not configured; drilling the newest LOCAL backup. / ยังไม่ได้ตั้งค่า Drive จึงทดสอบกับสำรองข้อมูลในเครื่องล่าสุดแทน'
            $run = Invoke-MepRestoreRehearsal
        }
        $parsed = ConvertFrom-MepRestoreDrillOutput -Output $run.Output
    }
    catch {
        $err = $_.Exception.Message
    }
    $finished = Get-Date
    $result = New-MepRestoreDrillResult -Started $started -Finished $finished -Source $source -Parsed $parsed -ErrorMessage $err
    $path = Write-MepRestoreDrillResult -Result $result -Now $started
    $level = if ($result.result -eq 'PASS') { 'INFO' } else { 'ERROR' }
    Write-InstallLog -Phase 'restore-drill' -Level $level -Message ("Restore drill $($result.result) (source=$source, file=$($result.backup_file), elapsed_seconds=$($result.elapsed_seconds), checksum=$($result.checksum), tables=$(@($result.row_counts.Keys).Count), result_file=$(Split-Path -Leaf $path)).")
    return [pscustomobject]$result
}

# ---------------------------------------------------------------------------
# Scheduling (same pattern, account and pwsh rules as Schedule.ps1)
# ---------------------------------------------------------------------------

function Get-MepRestoreDrillScriptPath {
    $path = Join-Path $Script:DeploymentRoot 'run-restore-drill.ps1'
    if (-not (Test-Path -LiteralPath $path)) {
        throw (New-MepFailure "run-restore-drill.ps1 was not found at $path; refusing to register a schedule that would point at nothing.")
    }
    return $path
}

function Get-MepRestoreDrillSchedule {
    return Get-ScheduledTask -TaskName $Script:RestoreDrillTaskName -ErrorAction SilentlyContinue
}

function Register-MepRestoreDrillSchedule {
    param(
        [Parameter(Mandatory)] [securestring]$Password,
        [string]$UserName = "$env:USERDOMAIN\$env:USERNAME"
    )
    $pwshPath = Get-MepPwshPath
    $script = Get-MepRestoreDrillScriptPath

    # -Scheduled makes run-restore-drill.ps1 skip Sundays that are not the
    # first of the month (see Test-MepRestoreDrillDue).
    $action = New-ScheduledTaskAction -Execute $pwshPath `
        -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$script`" -Scheduled" `
        -WorkingDirectory $Script:DeploymentRoot
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday `
        -At ([datetime]::Today.AddHours($Script:RestoreDrillHour).AddMinutes($Script:RestoreDrillMinute))
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
        -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 4)

    $plain = $null
    try {
        $plain = [System.Net.NetworkCredential]::new('', $Password).Password
        Register-ScheduledTask -TaskName $Script:RestoreDrillTaskName `
            -Action $action -Trigger $trigger -Settings $settings `
            -User $UserName -Password $plain -RunLevel Limited `
            -Description 'First Sunday of each month 03:17: restores the newest backup into a disposable database, verifies it, drops it. Never touches the live DB. Registered by schedule-restore-drill.ps1.' `
            -Force | Out-Null
    }
    finally { $plain = $null }
    Write-InstallLog -Phase 'schedule' -Message "Restore drill schedule registered (task='$Script:RestoreDrillTaskName')."
}

function Unregister-MepRestoreDrillSchedule {
    $existing = Get-MepRestoreDrillSchedule
    if ($null -eq $existing) {
        Write-Host 'No restore drill schedule is registered; nothing to remove. / ไม่มีงานทดสอบกู้คืนที่ลงทะเบียนไว้'
        return $false
    }
    Unregister-ScheduledTask -TaskName $Script:RestoreDrillTaskName -Confirm:$false
    Write-InstallLog -Phase 'schedule' -Message "Restore drill schedule removed (task='$Script:RestoreDrillTaskName')."
    return $true
}

function Show-MepRestoreDrillStatus {
    $task = Get-MepRestoreDrillSchedule
    if ($null -eq $task) {
        Write-Host 'Restore drill schedule: NOT REGISTERED / ยังไม่ได้ลงทะเบียน' -ForegroundColor Yellow
        Write-Host '  Run .\schedule-restore-drill.ps1 -Register'
    }
    else {
        Write-Host "Restore drill schedule: REGISTERED ($($task.State)) / ลงทะเบียนแล้ว" -ForegroundColor Green
        $info = Get-ScheduledTaskInfo -TaskName $Script:RestoreDrillTaskName -ErrorAction SilentlyContinue
        if ($info) {
            Write-Host "  Last run: $($info.LastRunTime)"
            Write-Host "  Next run: $($info.NextRunTime)"
            $r = [int64]$info.LastTaskResult
            if ($r -eq 0) { Write-Host '  Last task result: SUCCESS' -ForegroundColor Green }
            elseif ($r -in 267008, 267009, 267011) { Write-Host "  Last task result: not a failure (code $r; running / ready / not run yet)" }
            else { Write-Host "  Last task result: FAILED (code $r) / ล้มเหลว" -ForegroundColor Red }
        }
    }
    $last = Get-MepLastRestoreDrillResult
    if ($null -eq $last) {
        Write-Host 'Last drill result: none yet / ยังไม่เคยทดสอบ' -ForegroundColor Yellow
        return
    }
    $color = if ($last.result -eq 'PASS') { 'Green' } else { 'Red' }
    Write-Host "Last drill result: $($last.result) / ผลทดสอบล่าสุด" -ForegroundColor $color
    Write-Host "  Started: $($last.started)   Source: $($last.source)   Backup: $($last.backup_file)"
    Write-Host "  Elapsed: $($last.elapsed_seconds)s   Checksum: $($last.checksum)   Alembic: $($last.alembic_revision)"
    if ($last.error) { Write-Host "  Error: $($last.error)" -ForegroundColor Red }
}
