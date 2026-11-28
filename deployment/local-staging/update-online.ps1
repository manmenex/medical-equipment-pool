<#
.SYNOPSIS
Owner-triggered version change for the department PC: online (public
GitHub) or offline (-SourceZip), or back to the previous version
(-Rollback). Always ends in the existing update.ps1, so its mandatory
verified backup ("no backup, no update") applies unchanged.

.DESCRIPTION
Nothing here runs by itself or on a schedule. "Production deployment is the
Owner's decision."

  .\update-online.ps1 -Version <release-tag-or-commit-sha>
      git fetch from the public repository -> the commit must exist and its
      GitHub checks must all be green (unless -Force) -> the working tree
      must be clean -> checkout that exact commit (detached) -> update.ps1.

  .\update-online.ps1 -SourceZip D:\mep-main.zip [-Version <expected-sha>]
      Offline: a GitHub "Download ZIP" of one commit (e.g. from a USB
      stick). The commit SHA is read from the ZIP itself and compared with
      -Version when given. GitHub checks cannot be verified offline.

  .\update-online.ps1 -Rollback
      Code back to the previously installed version, then update.ps1.
      Database migrations are NEVER downgraded automatically. If the newer
      version added migrations the older one lacks, the rollback is refused
      unless -ConfirmMigrationRollback is given AND a verified backup
      exists; even then only the source folder is switched and the
      restore procedure is printed.

The installed and previous versions are recorded in
deployment/local-staging/.version-history.json (gitignored, no secrets).

.PARAMETER Force
Accept a version whose GitHub checks are not all green, or an unverified
ZIP, without the question. An explicit Owner decision.
.PARAMETER Yes
Skip the final "Proceed?" question (the Owner has already decided).
#>
[CmdletBinding()]
param(
    [string]$Version = '',
    [string]$SourceZip = '',
    [switch]$Rollback,
    [switch]$Force,
    [switch]$ConfirmMigrationRollback,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/HostSetup.ps1')

# deployment/local-staging -> repository root (the install folder).
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host ''
Write-Host '=== Medical Equipment Pool -- Online / Offline Update ===' -ForegroundColor Cyan

# Leave the install folder: a ZIP update replaces files inside it and Windows
# will not remove a folder that is some process's current directory.
$originalLocation = Get-Location
Set-Location -LiteralPath (Split-Path -Parent $root)
try {
    $updateScript = Join-Path $PSScriptRoot 'update.ps1'
    $runUpdate = {
        $r = Invoke-MepHostCommand -FilePath (Get-MepPwshExecutable) -AllowNonZeroExit -NoCapture `
            -Arguments @('-NoProfile', '-File', $updateScript)
        return $r.ExitCode
    }
    $result = Invoke-MepOnlineUpdate -Root $root -Version $Version -SourceZip $SourceZip `
        -Rollback:$Rollback -Force:$Force -ConfirmMigrationRollback:$ConfirmMigrationRollback `
        -Yes:$Yes -RunUpdate $runUpdate
    Write-Host "Result: $($result.Outcome)"
    if ($result.Outcome -eq 'CodeOnlyRollback') { exit 2 }
    exit 0
}
catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    try { Set-Location -LiteralPath $originalLocation } catch { }
}
