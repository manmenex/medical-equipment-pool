<#
.SYNOPSIS
Trim the full Google Sheet export (.xlsx) to the 4 sheets and date range the
"นำเข้าข้อมูลเดิม" menu accepts.

.DESCRIPTION
Runs backend/app/scripts/prepare_legacy_history.py inside the running backend
container. The input is copied in, the result copied back, and both temp
files are removed from the container. Only counts are printed -- never cell
data (the workbook is real hospital data). History only: this does not
change current equipment status.

    .\prepare-legacy-history.ps1 -InputFile C:\MEP\history\pool-export.xlsx -Since 2026-05-25
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$InputFile,
    [Parameter(Mandatory)] [string]$Since,
    [string]$Until,
    [string]$OutputFile
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

Write-Host ''
Write-Host '=== เตรียมไฟล์นำเข้าข้อมูลเดิม ===' -ForegroundColor Cyan

$inContainer = $null
$outContainer = $null
try {
    foreach ($d in @($Since, $Until)) {
        if ($d -and $d -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "รูปแบบวันที่ต้องเป็น YYYY-MM-DD: $d" }
    }
    if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) { throw "ไม่พบไฟล์: $InputFile" }
    if ([System.IO.Path]::GetExtension($InputFile).ToLowerInvariant() -ne '.xlsx') { throw 'ต้องเป็นไฟล์ .xlsx' }
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine ยังไม่ทำงาน เปิด Docker Desktop แล้วลองใหม่'
    }
    if (-not (Test-EnvFileExists)) { throw 'ไม่พบการติดตั้ง รัน .\install.ps1 ก่อน' }

    $inFull = (Resolve-Path -LiteralPath $InputFile).ProviderPath
    if (-not $OutputFile) {
        $dir = Split-Path -Parent $inFull
        $name = [System.IO.Path]::GetFileNameWithoutExtension($inFull)
        $OutputFile = Join-Path $dir "$name-import-$Since.xlsx"
    }
    $outFull = [System.IO.Path]::GetFullPath($OutputFile)

    $id = [guid]::NewGuid().ToString('N')
    $inContainer = "/tmp/mep-prep-$id-in.xlsx"
    $outContainer = "/tmp/mep-prep-$id-out.xlsx"

    $r = Invoke-DockerCompose -Arguments @('cp', $inFull, "backend:$inContainer") -AllowNonZeroExit -Phase 'prepare-legacy-history'
    if ($r.ExitCode -ne 0) { throw 'คัดลอกไฟล์เข้า container ไม่สำเร็จ (backend ทำงานอยู่หรือไม่? ดู .\status.ps1)' }

    $toolArgs = @('exec', '-T', 'backend', 'python', '-m', 'app.scripts.prepare_legacy_history',
        '--input', $inContainer, '--output', $outContainer, '--since', $Since)
    if ($Until) { $toolArgs += @('--until', $Until) }
    $r = Invoke-DockerCompose -Arguments $toolArgs -AllowNonZeroExit -Phase 'prepare-legacy-history'
    # Console only: the tool prints counts, never cell values.
    foreach ($line in @($r.Output)) { Write-Host $line }
    if ($r.ExitCode -ne 0) { throw "เตรียมไฟล์ไม่สำเร็จ (exit $($r.ExitCode)) ไม่มีการสร้างไฟล์ผลลัพธ์" }

    $r = Invoke-DockerCompose -Arguments @('cp', "backend:$outContainer", $outFull) -AllowNonZeroExit -Phase 'prepare-legacy-history'
    if ($r.ExitCode -ne 0) { throw 'คัดลอกไฟล์ผลลัพธ์กลับไม่สำเร็จ' }

    Write-Host ''
    Write-Host "เสร็จแล้ว: $outFull" -ForegroundColor Green
    Write-Host 'นำไฟล์นี้ไปอัปโหลดที่เมนู "นำเข้าข้อมูลเดิม" (เป็นประวัติเท่านั้น ไม่เปลี่ยนสถานะเครื่องมือปัจจุบัน)'
    Write-InstallLog -Phase 'prepare-legacy-history' -Level 'INFO' -Message 'Prepared legacy history workbook (no cell data logged).'
    $code = 0
}
catch {
    Write-InstallLog -Phase 'prepare-legacy-history' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    $code = 1
}
finally {
    $tmp = @($inContainer, $outContainer) | Where-Object { $_ }
    if ($tmp) {
        try {
            $null = Invoke-DockerCompose -Arguments (@('exec', '-T', 'backend', 'rm', '-f') + $tmp) -AllowNonZeroExit -Phase 'prepare-legacy-history'
        }
        catch { Write-Host 'คำเตือน: ลบไฟล์ชั่วคราวใน container ไม่สำเร็จ' -ForegroundColor Yellow }
    }
}
exit $code
