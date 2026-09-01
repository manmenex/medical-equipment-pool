<#
.SYNOPSIS
PR24D-L2: stops the local Staging/UAT application stack safely.

.DESCRIPTION
Uses `docker compose stop` (containers stopped, not removed) -- never
`down -v` (repository §24: preserve the PostgreSQL volume, configuration,
and backups by default). Repeatable: stopping an already-stopped
installation is a no-op, not an error.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Stop ===' -ForegroundColor Cyan
Write-InstallLog -Phase 'stop' -Message 'stop.ps1 started.'

if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
    Write-Host 'ERROR: Docker Engine is not available. Start Docker Desktop and rerun .\stop.ps1.' -ForegroundColor Red
    exit 1
}

if (-not (Test-EnvFileExists)) {
    Write-Host 'No existing installation found -- nothing to stop.' -ForegroundColor Yellow
    exit 0
}

# `stop` (not `down`): containers are stopped but not removed, and the
# named volumes (local_staging_postgres_data / local_staging_redis_data)
# are never touched by this command regardless.
$result = Invoke-DockerCompose -Arguments @('stop') -PassThru
if ($result.ExitCode -ne 0) {
    Write-Host 'ERROR: docker compose stop reported a failure.' -ForegroundColor Red
    Write-InstallLog -Phase 'stop' -Level 'ERROR' -Message 'docker compose stop failed.'
    exit 1
}

Write-Host 'Stopped. PostgreSQL data, configuration, and backups were preserved.' -ForegroundColor Green
Write-InstallLog -Phase 'stop' -Message 'stop.ps1 completed successfully.'
