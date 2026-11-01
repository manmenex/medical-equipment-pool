<#
.SYNOPSIS
One-time, re-runnable load of ward / department / equipment-category master
data from two CSV files, so names match the external Nsmart Realtime tool.

.DESCRIPTION
The engine is backend/scripts/load_master_data.py, run in the backend
container. This wrapper only mounts the two CSV files READ-ONLY into the
container (they are never copied into the repository or the image) and
passes the switches through.

    .\load-master-data.ps1 -WardsCsv C:\data\wards.csv -CategoriesCsv C:\data\categories.csv
        DRY RUN (default): prints the plan, writes nothing.
    .\load-master-data.ps1 -WardsCsv ... -CategoriesCsv ... -Apply
        writes everything in ONE transaction with ONE audit entry.

wards CSV header:      ward_name,nsmart_department,phone
categories CSV header: category_name
Both files must be UTF-8 (a BOM is fine). Existing rows are matched by exact
name and left unchanged; nothing is deleted or renamed.

.PARAMETER Apply
Write the plan. Without it nothing is written.

.PARAMETER OverwritePhones
Replace phones that are already set on existing rows (default: only fill
empty phones).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$WardsCsv,
    [Parameter(Mandatory)] [string]$CategoriesCsv,
    [switch]$Apply,
    [switch]$OverwritePhones
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Master Data Loader ===' -ForegroundColor Cyan

try {
    foreach ($p in @($WardsCsv, $CategoriesCsv)) {
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
            throw "CSV file not found: $p"
        }
    }
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun.'
    }
    if (-not (Test-EnvFileExists)) {
        throw 'No existing installation found. Run .\install.ps1 first.'
    }
    $wardsFull = (Resolve-Path -LiteralPath $WardsCsv).ProviderPath
    $catsFull = (Resolve-Path -LiteralPath $CategoriesCsv).ProviderPath

    $toolArgs = @(
        'python', 'scripts/load_master_data.py',
        '--wards', '/mep-input/wards.csv',
        '--categories', '/mep-input/categories.csv'
    )
    if ($Apply) { $toolArgs += '--apply' }
    if ($OverwritePhones) { $toolArgs += '--overwrite-phones' }

    if (-not $Apply) {
        Write-Host 'DRY RUN -- nothing will be written. Add -Apply after reviewing the plan.' -ForegroundColor Yellow
    }
    # -T: no TTY. Output is streamed (never logged to the installer log: it
    # contains hospital ward names).
    $result = Invoke-DockerCompose -Arguments (@(
            'run', '--rm', '-T',
            '-v', "${wardsFull}:/mep-input/wards.csv:ro",
            '-v', "${catsFull}:/mep-input/categories.csv:ro",
            'backend') + $toolArgs) -AllowNonZeroExit -Phase 'load-master-data'
    foreach ($line in @($result.Output)) { Write-Host $line }
    if ($result.ExitCode -ne 0) {
        Write-InstallLog -Phase 'load-master-data' -Level 'ERROR' -Message "Loader exited with code $($result.ExitCode)."
        Write-Host "Loader failed (exit code $($result.ExitCode)). Nothing was written." -ForegroundColor Red
        exit $result.ExitCode
    }
    Write-InstallLog -Phase 'load-master-data' -Level 'INFO' -Message "Loader finished (apply=$([bool]$Apply))."
    exit 0
}
catch {
    Write-InstallLog -Phase 'load-master-data' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
