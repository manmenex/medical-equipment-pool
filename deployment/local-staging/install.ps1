<#
.SYNOPSIS
PR24D-L2 (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §32):
installs or converges the local Staging/UAT Docker deployment on a Windows
host with Docker Desktop.

THIS IS NOT A FOURTH ENVIRONMENT -- see compose.yml's own header and
OD-PR24-4. This script only orchestrates the existing Staging/UAT
execution mode; it introduces no new environment type, no new backup
engine, and no new user-creation logic (Administrator bootstrap is the
existing PR24B `app.scripts.bootstrap_admin` CLI, invoked unchanged).

.DESCRIPTION
Sequence (see Invoke-MepInstall in lib/Operations.ps1, which owns it and
is covered by tests/Invoke-InstallerTests.ps1): acquire the deployment
mutation lock -> prerequisite checks -> full state inspection (container
state, which deliberately does NOT require the .env this script has not
created yet) -> generate or preserve configuration -> validate Compose ->
BUILD backend/frontend from current source -> start PostgreSQL and wait
healthy -> explicit Alembic migration against the just-built image ->
start the application and wait for /api/v1/ready -> mandatory
Administrator bootstrap when the installation has never completed ->
write success metadata -> print the LAN URL.

Fails closed at every step: a failed build, migration, readiness wait, or
Administrator bootstrap stops the installation and leaves no
"installation completed" metadata behind.

THIS SCRIPT IS ALSO THE RECOVERY PATH. If a previous install failed after
the containers started but before the Administrator was created, run
`.\install.ps1` again -- NOT `.\update.ps1`, which refuses any
installation that never completed. Re-running install preserves the
existing .env, its generated secrets, and the PostgreSQL data; it
converges the deployment and retries the Administrator bootstrap, and
only marks the installation completed once that invariant is satisfied.
If the backend reports that an administrator already exists, that counts
as satisfied -- the backend, not this script, is the source of truth.

.EXAMPLE
.\install.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')
. (Join-Path $PSScriptRoot 'lib/Operations.ps1')

function Write-Banner {
    param([string]$Text)
    Write-Host ''
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

Write-Banner 'Medical Equipment Pool -- Local Staging/UAT Install'
Write-InstallLog -Phase 'install' -Message 'install.ps1 started.'

# Interactive configuration for a genuinely fresh installation.
$configCallback = {
    Write-Banner 'Generating local configuration'
    $candidates = Get-LikelyLanIPv4Addresses
    $suggested = if ($candidates.Count -ge 1) { $candidates[0] } else { $null }
    if ($candidates.Count -gt 1) {
        Write-Host 'Multiple LAN addresses were detected on this machine:' -ForegroundColor Yellow
        $candidates | ForEach-Object { Write-Host "  - $_" }
        Write-Host 'Choose the one other devices on your hospital LAN will actually use to reach this PC.'
    }
    $defaultOrigin = if ($suggested) { "http://$suggested" } else { 'http://<this-computer-LAN-IP>' }
    $originInput = Read-Host "LAN URL this deployment will be reached at [$defaultOrigin]"
    $allowedOrigins = if ([string]::IsNullOrWhiteSpace($originInput)) { $defaultOrigin } else { $originInput }

    $portInput = Read-Host 'Frontend port [80]'
    $httpPort = if ([string]::IsNullOrWhiteSpace($portInput)) { 80 } else { [int]$portInput }

    return @{ AllowedOrigins = $allowedOrigins; HttpPort = $httpPort }
}

# Administrator details. All three are required -- Invoke-MepAdminBootstrap
# rejects blank input, and a failed bootstrap fails the whole installation
# (no usable administrator means the deployment is not usable).
$adminCallback = {
    Write-Banner 'Administrator account'
    Write-Host 'This deployment needs one administrator account. All three fields are required.'
    Write-Host 'The backend generates a one-time password and prints it once below -- this installer never handles it.'
    $employeeCode = Read-Host 'Administrator employee code (e.g. ADMIN001)'
    $email = Read-Host 'Administrator email'
    $fullName = Read-Host 'Administrator full name'
    return @{ EmployeeCode = $employeeCode; Email = $email; FullName = $fullName }
}

$lock = $null
try {
    $lock = Enter-MepMutationLock
    Invoke-MepInstall -AdminCredentialCallback $adminCallback -ConfigCallback $configCallback | Out-Null

    $finalPort = Get-ConfiguredHttpPort
    $lanCandidates = Get-LikelyLanIPv4Addresses

    Write-Banner 'Install complete'
    Write-Host 'Access this deployment from any authorized device on the same LAN:' -ForegroundColor Green
    if ($lanCandidates.Count -eq 0) {
        Write-Host "  http://localhost:$finalPort  (LAN address could not be detected automatically -- reachable from this PC only)"
    }
    else {
        foreach ($addr in $lanCandidates) { Write-Host "  http://${addr}:$finalPort" }
    }
    Write-Host ''
    Write-Host 'If other devices cannot reach this address, a Windows Firewall rule may be required for the frontend port (this script does not create one automatically).' -ForegroundColor Yellow
}
catch {
    Write-InstallLog -Phase 'install' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Installation did NOT complete. No "installation completed" state was recorded.' -ForegroundColor Red
    exit 1
}
finally {
    Exit-MepMutationLock $lock
}
