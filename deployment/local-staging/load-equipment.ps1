<#
.SYNOPSIS
Re-runnable load of the hospital's pool equipment export (Excel) into the
equipment table. Run AFTER load-master-data.ps1 (categories must exist).

.DESCRIPTION
The engine is backend/scripts/load_equipment.py, run in the backend
container. This wrapper only mounts the Excel file READ-ONLY into the
container (it is never copied into the repository or the image) and passes
the switches through.

    .\load-equipment.ps1 -PoolFile C:\data\pool.xltx
        DRY RUN (default): prints the plan and summary, writes nothing.
    .\load-equipment.ps1 -PoolFile ... -Apply
        writes everything in ONE transaction with ONE audit entry.

Accepted: .xlsx .xlsm .xltx .xltm (first sheet; header row found by name).
Existing equipment (matched by BCM) is never changed unless -UpdateExisting,
and even then only brand/model/S/N/Asset ID/Item No -- never status.

GO-LIVE NOTE (Owner decision): items marked "ยังไม่ส่งคืน" load as available.
Staff must not dispatch an item that is not physically on the shelf. Loans
made before the system cannot be received in it; when such an item returns,
nothing needs to be recorded.

.PARAMETER Apply
Write the plan. Without it nothing is written.

.PARAMETER UpdateExisting
Update brand/model/serial/asset_id/item_no on existing equipment whose values
differ (default: report and skip).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$PoolFile,
    [switch]$Apply,
    [switch]$UpdateExisting
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Pool Equipment Loader ===' -ForegroundColor Cyan

try {
    if (-not (Test-Path -LiteralPath $PoolFile -PathType Leaf)) {
        throw "Pool file not found: $PoolFile"
    }
    $ext = [System.IO.Path]::GetExtension($PoolFile).ToLowerInvariant()
    if ($ext -notin @('.xlsx', '.xlsm', '.xltx', '.xltm')) {
        throw "Unsupported file type '$ext'. Use .xlsx, .xlsm, .xltx or .xltm."
    }
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun.'
    }
    if (-not (Test-EnvFileExists)) {
        throw 'No existing installation found. Run .\install.ps1 first.'
    }
    $poolFull = (Resolve-Path -LiteralPath $PoolFile).ProviderPath

    # Keep the extension: the engine uses it to detect Excel templates.
    $inContainer = "/mep-input/pool$ext"
    $toolArgs = @('python', 'scripts/load_equipment.py', '--pool-file', $inContainer)
    if ($Apply) { $toolArgs += '--apply' }
    if ($UpdateExisting) { $toolArgs += '--update-existing' }

    if (-not $Apply) {
        Write-Host 'DRY RUN -- nothing will be written. Add -Apply after reviewing the plan.' -ForegroundColor Yellow
    }
    # -T: no TTY. Output is streamed (never logged to the installer log: it
    # contains hospital equipment identifiers).
    $result = Invoke-DockerCompose -Arguments (@(
            'run', '--rm', '-T',
            '-v', "${poolFull}:${inContainer}:ro",
            'backend') + $toolArgs) -AllowNonZeroExit -Phase 'load-equipment'
    foreach ($line in @($result.Output)) { Write-Host $line }
    if ($result.ExitCode -ne 0) {
        Write-InstallLog -Phase 'load-equipment' -Level 'ERROR' -Message "Loader exited with code $($result.ExitCode)."
        Write-Host "Loader failed (exit code $($result.ExitCode)). Nothing was written." -ForegroundColor Red
        exit $result.ExitCode
    }
    if ($Apply) {
        Write-Host 'GO-LIVE NOTE: items marked "ยังไม่ส่งคืน" were loaded as available. Staff must not dispatch an item that is not physically on the shelf.' -ForegroundColor Yellow
    }
    Write-InstallLog -Phase 'load-equipment' -Level 'INFO' -Message "Loader finished (apply=$([bool]$Apply), updateExisting=$([bool]$UpdateExisting))."
    exit 0
}
catch {
    Write-InstallLog -Phase 'load-equipment' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
