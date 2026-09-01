<#
.SYNOPSIS
PR24D-L2: starts an already-installed local Staging/UAT deployment.

.DESCRIPTION
Does NOT generate or regenerate secrets, does NOT run a migration
(repository §23 -- migrations belong to install.ps1/update.ps1 only,
never start.ps1). Requires an existing .env; if none exists, directs the
operator to .\install.ps1 instead of silently creating one.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Start ===' -ForegroundColor Cyan
Write-InstallLog -Phase 'start' -Message 'start.ps1 started.'

if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
    Write-Host 'ERROR: Docker Engine is not available. Start Docker Desktop and rerun .\start.ps1.' -ForegroundColor Red
    exit 1
}

if (-not (Test-EnvFileExists)) {
    Write-Host 'ERROR: No existing installation found (deployment/local-staging/.env is missing).' -ForegroundColor Red
    Write-Host 'ACTION: Run .\install.ps1 first.' -ForegroundColor Yellow
    exit 1
}

$configExit = Invoke-DockerComposeConfigOnly
if ($configExit -ne 0) {
    Write-Host 'ERROR: docker compose config failed against the existing .env. See deployment/local-staging/.env.example.' -ForegroundColor Red
    exit 1
}

Write-Host 'Starting PostgreSQL...'
$pgResult = Wait-ComposeServicesHealthy -Services @('postgres') -TimeoutSeconds 120
if ($pgResult.ExitCode -ne 0) {
    Write-Host 'ERROR: PostgreSQL did not become healthy in time.' -ForegroundColor Red
    exit 1
}

Invoke-DockerCompose -Arguments @('up', '-d', 'redis') | Out-Null

Write-Host 'Starting the application...'
$appResult = Wait-ComposeServicesHealthy -Services @('backend', 'frontend') -TimeoutSeconds 180
if ($appResult.ExitCode -ne 0) {
    Write-Host 'ERROR: The application did not become ready in time (GET /api/v1/ready). Run .\status.ps1 for diagnostics.' -ForegroundColor Red
    exit 1
}

$env = Read-EnvFile
$port = if ($env.ContainsKey('LOCAL_STAGING_HTTP_PORT') -and $env['LOCAL_STAGING_HTTP_PORT']) { $env['LOCAL_STAGING_HTTP_PORT'] } else { 80 }
$lanCandidates = Get-LikelyLanIPv4Addresses

Write-Host 'Application is ready.' -ForegroundColor Green
if ($lanCandidates.Count -eq 0) {
    Write-Host "  http://localhost:$port"
}
else {
    foreach ($addr in $lanCandidates) { Write-Host "  http://${addr}:$port" }
}
Write-InstallLog -Phase 'start' -Message 'start.ps1 completed successfully.'
