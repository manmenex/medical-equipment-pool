<#
.SYNOPSIS
PR24D-L2: prints concise operator status for the local Staging/UAT
deployment. Never prints a secret, token, or credential-bearing
DATABASE_URL.

.DESCRIPTION
Read-only: deliberately does NOT take the deployment mutation lock, so
status stays usable while an install or update is running. It reports
whether such an operation is in progress by probing the lock without
holding it.

Uses `docker compose ps --all` so stopped/exited services are visible --
plain `ps` hides them and would make a fully stopped installation look
like it had no containers at all.

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

# Probe the mutation lock without holding it: if another operation owns
# it, report BUSY rather than blocking or failing.
$busy = $false
try {
    $probe = Enter-MepMutationLock
    Exit-MepMutationLock $probe
}
catch {
    $busy = $true
}
if ($busy) {
    Write-Host 'Deployment operation: BUSY (an install/update/stop is currently running)' -ForegroundColor Yellow
}

function Format-ServiceHealth {
    param($Entry, [string]$HealthyWord = 'Healthy', [string]$OtherWord = 'Degraded')
    if (-not $Entry) { return 'Not created' }
    if ($Entry.State -ne 'running') { return 'Stopped' }
    if (-not $Entry.PSObject.Properties.Name.Contains('Health') -or -not $Entry.Health -or $Entry.Health -eq '') { return 'Running' }
    if ($Entry.Health -eq 'healthy') { return $HealthyWord }
    return $OtherWord
}

function Format-OptionalServiceHealth {
    <#
    .SYNOPSIS
    Reports an optional (non-blocking) service. Fix Round 3: Redis no
    longer affects the deployment's state, but its failure must still be
    VISIBLE -- non-blocking is not the same as unimportant. Absent,
    stopped, and unhealthy all read as "Degraded" here, because from an
    operator's point of view all three mean the cache is not serving.
    #>
    param($Entry)
    if (-not $Entry) { return 'Degraded (not created)' }
    if ($Entry.State -ne 'running') { return 'Degraded (stopped)' }
    if (-not $Entry.PSObject.Properties.Name.Contains('Health') -or -not $Entry.Health -or $Entry.Health -eq '') { return 'Running' }
    if ($Entry.Health -eq 'healthy') { return 'Healthy' }
    return 'Degraded (unhealthy)'
}

$services = Get-MepServiceStates
if ($null -eq $services) {
    Write-Host 'Could not inspect container state (docker compose ps failed).' -ForegroundColor Red
    exit 1
}

$pg = if ($services.ContainsKey('postgres')) { $services['postgres'] } else { $null }
$redis = if ($services.ContainsKey('redis')) { $services['redis'] } else { $null }
$backend = if ($services.ContainsKey('backend')) { $services['backend'] } else { $null }
$frontend = if ($services.ContainsKey('frontend')) { $services['frontend'] } else { $null }

Write-Host "PostgreSQL:  $(Format-ServiceHealth $pg)"
# Redis is non-blocking by contract, so it never changes the deployment
# State line below -- but its failure is still shown plainly here rather
# than hidden behind "non-blocking".
Write-Host "Redis:       $(Format-OptionalServiceHealth $redis) (non-blocking)"
Write-Host "Backend:     $(if ($backend -and $backend.State -eq 'running') { 'Running' } elseif ($backend) { 'Stopped' } else { 'Not created' })"
Write-Host "Frontend:    $(if ($frontend -and $frontend.State -eq 'running') { 'Running' } elseif ($frontend) { 'Stopped' } else { 'Not created' })"
Write-Host "State:       $(Get-InstallationState)"

$port = Get-ConfiguredHttpPort

$isReady = $false
if ($frontend -and $frontend.State -eq 'running') {
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
