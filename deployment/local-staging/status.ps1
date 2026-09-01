<#
.SYNOPSIS
PR24D-L2: prints concise operator status for the local Staging/UAT
deployment. Never prints a secret, token, or credential-bearing
DATABASE_URL (repository §25).

.OUTPUTS
Exit code 0 if the application is ready (GET /api/v1/ready passing);
non-zero otherwise, so this script is usable in an unattended health
check.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

Write-Host ''
Write-Host 'Medical Equipment Pool -- Local Staging/UAT' -ForegroundColor Cyan
Write-Host ''

$dockerRunning = (Test-DockerCliAvailable) -and (Test-DockerEngineRunning)
Write-Host "Docker:      $(if ($dockerRunning) { 'Running' } else { 'Not available' })"

if (-not $dockerRunning) {
    Write-Host ''
    Write-Host 'Docker Engine is not available -- no further status can be determined.' -ForegroundColor Yellow
    exit 1
}

if (-not (Test-EnvFileExists)) {
    Write-Host 'No installation found. Run .\install.ps1 to create one.' -ForegroundColor Yellow
    exit 1
}

function Get-ServiceStatusMap {
    $result = Invoke-DockerCompose -Arguments @('ps', '--format', 'json') -PassThru
    $map = @{}
    if ($result.ExitCode -ne 0 -or -not $result.Output) { return $map }
    foreach ($line in $result.Output) {
        if (-not $line -or $line.Trim() -eq '') { continue }
        try {
            $svc = $line | ConvertFrom-Json
        }
        catch { continue }
        $map[$svc.Service] = $svc
    }
    return $map
}

function Format-ServiceHealth {
    param($Entry, [string]$HealthyWord = 'Healthy', [string]$OtherWord = 'Degraded')
    if (-not $Entry) { return 'Stopped' }
    if ($Entry.State -ne 'running') { return 'Stopped' }
    if (-not $Entry.Health -or $Entry.Health -eq '') { return 'Running' }
    if ($Entry.Health -eq 'healthy') { return $HealthyWord }
    return $OtherWord
}

$services = Get-ServiceStatusMap

Write-Host "PostgreSQL:  $(Format-ServiceHealth $services['postgres'])"
Write-Host "Redis:       $(Format-ServiceHealth $services['redis'])"
Write-Host "Backend:     $(if ($services['backend'] -and $services['backend'].State -eq 'running') { 'Running' } else { 'Stopped' })"
Write-Host "Frontend:    $(if ($services['frontend'] -and $services['frontend'].State -eq 'running') { 'Running' } else { 'Stopped' })"

$env = Read-EnvFile
$port = if ($env.ContainsKey('LOCAL_STAGING_HTTP_PORT') -and $env['LOCAL_STAGING_HTTP_PORT']) { $env['LOCAL_STAGING_HTTP_PORT'] } else { 80 }

$isReady = $false
if ($services['frontend'] -and $services['frontend'].State -eq 'running') {
    # Avoids -SkipHttpErrorCheck (PowerShell 7.4+ only) so this also works
    # on Windows PowerShell 5.1: a 503 (not ready) throws a terminating
    # error here, which the catch below correctly treats as Not Ready.
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$port/api/v1/ready" -TimeoutSec 5 -UseBasicParsing
        $isReady = $response.StatusCode -eq 200
    }
    catch {
        $isReady = $false
    }
}
Write-Host "Readiness:   $(if ($isReady) { 'Ready' } else { 'Not Ready' })"

Write-Host ''
if ($isReady) {
    $lanCandidates = Get-LikelyLanIPv4Addresses
    Write-Host 'Access:' -ForegroundColor Green
    if ($lanCandidates.Count -eq 0) {
        Write-Host "  http://localhost:$port"
    }
    else {
        foreach ($addr in $lanCandidates) { Write-Host "  http://${addr}:$port" }
    }
}

exit $(if ($isReady) { 0 } else { 1 })
