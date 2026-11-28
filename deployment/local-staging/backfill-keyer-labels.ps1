<#
.SYNOPSIS
Backfill BME names (D22) onto rows already synced from the Google Sheet.

.DESCRIPTION
Runs backend/app/scripts/backfill_keyer_labels.py inside the backend
container. Default is a DRY-RUN (writes nothing); add -Apply to write. Safe to
re-run: it only fills empty labels on rows created by the sheet sync and never
overwrites an existing one. Prints counts only, never names.

    .\backfill-keyer-labels.ps1           # preview / ดูตัวอย่าง
    .\backfill-keyer-labels.ps1 -Apply    # write / บันทึกจริง
    .\backfill-keyer-labels.ps1 -Repair          # preview repair / ดูตัวอย่างการซ่อม
    .\backfill-keyer-labels.ps1 -Repair -Apply   # repair labels holding system-note text / ซ่อมจริง
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Repair
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

Write-Host ''
Write-Host '=== เติมชื่อ BME ย้อนหลัง / Backfill BME names ===' -ForegroundColor Cyan

try {
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine ยังไม่ทำงาน เปิด Docker Desktop แล้วลองใหม่ (Docker Engine is not running)'
    }
    if (-not (Test-EnvFileExists)) { throw 'ไม่พบการติดตั้ง รัน .\install.ps1 ก่อน (not installed)' }

    $toolArgs = @('exec', '-T', 'backend', 'python', '-m', 'app.scripts.backfill_keyer_labels')
    if ($Repair) { $toolArgs += '--repair' }
    if ($Apply) { $toolArgs += '--apply' }
    $r = Invoke-DockerCompose -Arguments $toolArgs -AllowNonZeroExit -Phase 'backfill-keyer-labels'
    foreach ($line in @($r.Output)) { Write-Host $line }
    if ($r.ExitCode -ne 0) { throw "ไม่สำเร็จ (exit $($r.ExitCode)) / failed" }

    Write-Host ''
    if ($Apply) {
        $doneMsg = if ($Repair) { 'เสร็จแล้ว / Done: ซ่อมป้ายชื่อที่เป็นข้อความระบบแล้ว (repaired).' } else { 'เสร็จแล้ว / Done: บันทึกชื่อ BME แล้ว (written).' }
        Write-Host $doneMsg -ForegroundColor Green
    }
    else {
        Write-Host 'นี่คือการดูตัวอย่างเท่านั้น ยังไม่บันทึก ใส่ -Apply เพื่อบันทึกจริง (Preview only; add -Apply to write).' -ForegroundColor Yellow
    }
    Write-InstallLog -Phase 'backfill-keyer-labels' -Level 'INFO' -Message "Keyer label backfill finished (apply=$([bool]$Apply)); counts only."
    $code = 0
}
catch {
    Write-InstallLog -Phase 'backfill-keyer-labels' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    $code = 1
}
exit $code
