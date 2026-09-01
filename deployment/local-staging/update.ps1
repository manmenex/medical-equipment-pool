<#
.SYNOPSIS
PR24D-L2: conservative update orchestration foundation. Rebuilds the
application from the currently checked-out repository source and applies
any pending migration.

.DESCRIPTION
Deliberately foundation-only (repository §29-31): no zero-downtime
deployment, no immutable-artifact/digest-pinned promotion (that model is
the long-term target -- see backend/scripts/deploy_migrate.py's own
--artifact-sha, reused here -- but this local execution mode currently
builds from on-disk source, and this script says so rather than
pretending otherwise). Never runs `git pull`, never checks out an
arbitrary ref, never pulls a `:latest` image tag.

PR24D-L3 has not been implemented yet, so no local backup/restore wrapper
exists to protect against an update's migration going wrong. Until then,
this script REFUSES to proceed past the migration step unless the
operator passes -AcknowledgeUpdateRisk, making that gap explicit rather
than silently updating as if it were already production-safe.

.PARAMETER AcknowledgeUpdateRisk
Required. Confirms the operator understands that no automated
backup/restore safety net exists yet for this update (planned PR24D-L3).

.EXAMPLE
.\update.ps1 -AcknowledgeUpdateRisk
#>
[CmdletBinding()]
param(
    [switch]$AcknowledgeUpdateRisk
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

function Exit-WithError {
    param([string]$Message)
    Write-InstallLog -Phase 'update' -Level 'ERROR' -Message $Message
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Update ===' -ForegroundColor Cyan
Write-InstallLog -Phase 'update' -Message 'update.ps1 started.'

if (-not (Test-EnvFileExists)) {
    Exit-WithError 'No existing installation found. Run .\install.ps1 first; update.ps1 only operates on an existing installation.'
}

if (-not $AcknowledgeUpdateRisk) {
    Write-Host 'This update will rebuild the application and may apply a database migration.' -ForegroundColor Yellow
    Write-Host 'PR24D-L3 (local backup/restore rehearsal) has not shipped yet, so there is no' -ForegroundColor Yellow
    Write-Host 'automated safety net if a migration goes wrong. Refusing to proceed.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host 'Rerun with -AcknowledgeUpdateRisk once you accept this, e.g.:' -ForegroundColor Yellow
    Write-Host '  .\update.ps1 -AcknowledgeUpdateRisk' -ForegroundColor Yellow
    exit 1
}

if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
    Exit-WithError 'Docker Engine is not available. Start Docker Desktop and rerun.'
}

try {
    Enter-InstallLock
}
catch {
    Exit-WithError $_.Exception.Message
}

try {
    # -------------------------------------------------------------------
    # Rebuild from the currently checked-out source. No `:latest`, no
    # `git pull`, no arbitrary checkout -- see module docstring.
    # -------------------------------------------------------------------
    Write-Host 'Building images from the current checked-out source...'
    $buildResult = Invoke-DockerCompose -Arguments @('build', 'backend', 'frontend') -PassThru
    if ($buildResult.ExitCode -ne 0) {
        Exit-WithError 'docker compose build failed. No running services were stopped.'
    }

    # -------------------------------------------------------------------
    # Stop only the application components -- PostgreSQL and Redis (and
    # their data) are left running/untouched.
    # -------------------------------------------------------------------
    Write-Host 'Stopping the application (PostgreSQL and Redis remain running)...'
    Invoke-DockerCompose -Arguments @('stop', 'backend', 'frontend') | Out-Null

    # -------------------------------------------------------------------
    # Explicit migration, same reused mechanism as install.ps1. Any
    # failure here stops the whole update -- the application is not
    # restarted against a database in an unknown state.
    # -------------------------------------------------------------------
    Write-Host 'Applying database migration...'
    $sourceSha = Get-CurrentSourceSha
    $migrateResult = Invoke-DockerCompose -Arguments @(
        'run', '--rm', '--name', 'mep-local-staging-migrate', '--no-deps', 'backend',
        'python', 'scripts/deploy_migrate.py',
        '--target-environment', 'local-staging-update',
        '--artifact-sha', $sourceSha
    ) -PassThru
    $migrateResult.Output | ForEach-Object { Write-Host $_ }
    if ($migrateResult.ExitCode -ne 0) {
        Exit-WithError 'Migration failed. The application was NOT restarted. Review the output above; PostgreSQL data was not deleted. Resolve the migration issue, then rerun .\update.ps1 -AcknowledgeUpdateRisk once fixed.'
    }

    # -------------------------------------------------------------------
    # Start the rebuilt application and wait for readiness.
    # -------------------------------------------------------------------
    Write-Host 'Starting the updated application...'
    $appResult = Wait-ComposeServicesHealthy -Services @('backend', 'frontend') -TimeoutSeconds 180
    if ($appResult.ExitCode -ne 0) {
        Exit-WithError 'The updated application did not become ready in time. Run .\status.ps1 for diagnostics.'
    }

    Set-InstallMetadata -SourceSha $sourceSha
    Write-Host 'Update complete. Application is ready.' -ForegroundColor Green
    Write-InstallLog -Phase 'update' -Message "update.ps1 completed successfully (source_sha=$sourceSha)."
}
finally {
    Exit-InstallLock
}
