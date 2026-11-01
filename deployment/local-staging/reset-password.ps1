<#
.SYNOPSIS
Host-only password reset for one user (recovery when the Administrator
password is forgotten).

.DESCRIPTION
Runs backend/app/scripts/reset_password.py inside the running backend
container. Sets a new one-time password (shown once on this console, never
logged), requires a change at next login, and clears the login lockout.

    .\reset-password.ps1 -EmployeeCode ADMIN001
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$EmployeeCode
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

$result = Invoke-DockerCompose -Arguments @(
    'exec', '-T', 'backend',
    'python', '-m', 'app.scripts.reset_password',
    '--employee-code', $EmployeeCode
) -AllowNonZeroExit -Phase 'reset-password'

# Console only. Never Write-InstallLog: on success this carries the
# one-time password.
foreach ($line in @($result.Output)) { Write-Host $line }

if ($result.ExitCode -ne 0) {
    Write-Host 'Password reset failed. Is the backend running? Check with .\status.ps1' -ForegroundColor Red
    exit 1
}
Write-InstallLog -Phase 'reset-password' -Message "Password reset for employee_code=$EmployeeCode (one-time password shown on console only, never logged)."
exit 0
