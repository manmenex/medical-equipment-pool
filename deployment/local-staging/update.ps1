<#
.SYNOPSIS
PR24D-L2: conservative update orchestration foundation. Rebuilds the
application from the currently checked-out repository source and applies
any pending migration.

.DESCRIPTION
Deliberately foundation-only: no zero-downtime deployment, no
immutable-artifact/digest-pinned promotion (that model is the long-term
target -- see backend/scripts/deploy_migrate.py's own --artifact-sha,
reused here -- but this local execution mode currently builds from
on-disk source, and this script says so rather than pretending
otherwise). Never runs `git pull`, never checks out an arbitrary ref,
never pulls a `:latest` image tag.

REQUIRES A COMPLETED INSTALLATION. update.ps1 is an update mechanism, not
an installation-recovery mechanism: it refuses to run unless a previous
install actually finished, including its mandatory Administrator
bootstrap. Only EXISTING_HEALTHY and EXISTING_STOPPED may be updated;
PARTIAL, AMBIGUOUS, and FRESH all fail closed.

If a first install failed after the containers came up but before the
Administrator was created, the recovery path is to run `.\install.ps1`
AGAIN -- not this script. A second install preserves .env, the generated
secrets, and the PostgreSQL data, converges the deployment, and completes
the Administrator bootstrap; only then is the installation marked
completed.

Sequence (see Invoke-MepUpdate in lib/Operations.ps1, which owns it and
is covered by tests/Invoke-InstallerTests.ps1): acquire the deployment
mutation lock -> require a previously completed installation -> capture
the initial state ONCE -> BUILD the intended images -> stop the
application (only when it was running) -> converge PostgreSQL to healthy
-> explicit migration -> start the new stack -> readiness -> refresh
metadata.

Both accepted entry states are handled explicitly:

  EXISTING_HEALTHY -> build -> stop backend/frontend and VERIFY they are
    actually stopped -> ensure PostgreSQL healthy -> migrate -> start ->
    ready -> metadata.

  EXISTING_STOPPED -> build -> no stop is issued (the application is
    already down, and a "failed to stop" error against an intentionally
    stopped deployment would be misleading) -> START PostgreSQL and wait
    for it to be healthy -> migrate -> start -> ready -> metadata.

PostgreSQL availability is a HARD precondition of the migration, not an
assumption: the migration container runs with --no-deps, so Compose will
not start the database for it. Both paths therefore call the same
health-gated PostgreSQL step before migrating. PostgreSQL is never
stopped by an update; only backend/frontend are. Redis is not involved
and remains non-blocking.

POST-UPDATE CONTRACT: a successful update always ends with the
application RUNNING and READY, whichever state it started from. Updating
a deployment that was stopped therefore leaves it started. This is
deliberate and stated here so it is not surprising; preserving an
original stopped state is not implemented and would be a separate
Owner-requested change.

A failed build never stops the running application; a failed or
unverified stop never allows a migration to run; an unhealthy PostgreSQL
never allows a migration to run; and update can never be the operation
that marks an installation completed for the first time.

PR24D-L3 has not been implemented yet, so no local backup/restore wrapper
exists to protect against an update's migration going wrong. Until then,
this script REFUSES to run unless the operator passes
-AcknowledgeUpdateRisk, making that gap explicit rather than silently
updating as if it were already production-safe.

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
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Local Staging/UAT Update ===' -ForegroundColor Cyan
Write-InstallLog -Phase 'update' -Message 'update.ps1 started.'

if (-not $AcknowledgeUpdateRisk) {
    Write-Host 'This update will rebuild the application and may apply a database migration.' -ForegroundColor Yellow
    Write-Host 'PR24D-L3 (local backup/restore rehearsal) has not shipped yet, so there is no' -ForegroundColor Yellow
    Write-Host 'automated safety net if a migration goes wrong. Refusing to proceed.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host 'Rerun with -AcknowledgeUpdateRisk once you accept this, e.g.:' -ForegroundColor Yellow
    Write-Host '  .\update.ps1 -AcknowledgeUpdateRisk' -ForegroundColor Yellow
    exit 1
}

$lock = $null
try {
    if (-not (Test-DockerCliAvailable) -or -not (Test-DockerEngineRunning)) {
        throw 'Docker Engine is not available. Start Docker Desktop and rerun.'
    }

    $lock = Enter-MepMutationLock
    $sourceSha = Invoke-MepUpdate
    Write-Host "Update complete. Application is ready (source_sha=$sourceSha)." -ForegroundColor Green
}
catch {
    Write-InstallLog -Phase 'update' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'The update did NOT complete. PostgreSQL data was not deleted.' -ForegroundColor Red
    exit 1
}
finally {
    Exit-MepMutationLock $lock
}
