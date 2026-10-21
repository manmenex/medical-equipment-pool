<#
.SYNOPSIS
One-shot, resumable setup of the department PC (CES-BCM): preflight,
prerequisites, source, install, optional master data, Drive backup, backup
schedule, final status.

.DESCRIPTION
Run it from PowerShell 7 as administrator, from a copy of this repository
(for example the GitHub "Download ZIP" extracted anywhere). It installs the
application into -InstallDir (default C:\MEP\app) and records progress in
setup-state.json beside it. Run the same command again after any stop and
it continues from the first unfinished step.

It NEVER deletes data, Docker volumes, backups or .env, never runs
`docker compose down -v`, and never asks for, prints or stores a token or
password. The repository is public, so no GitHub token is needed. The
Administrator account, the Windows password for the backup task and the
Google consent are asked by the existing scripts (install.ps1,
schedule-backup.ps1, drive-backup.ps1), not by this one.

This script does not claim the system is production-ready. Production
deployment is the Owner's decision.

Steps: preflight, prerequisites (Docker Desktop, Git), source, install,
masterdata, drive, schedule, final.

.PARAMETER Version
Release tag or commit SHA to install. Default: the newest commit on the
default branch that is verified green (public API, no token): its own checks
are all green, or (CI runs on pull requests, so usually) it is the squash-merge
commit of a merged pull request whose head checks are all green. If GitHub
cannot be queried, -Version is required. With -SourceZip it is the commit SHA
the ZIP is expected to be. Re-running with a different -Version after the
source step was done repeats the source step to that version (a dirty tree is
refused); apply it to the running system with update.ps1.
.PARAMETER SourceZip
Offline: a GitHub "Download ZIP" of one commit instead of git.
.PARAMETER WardsCsv
Optional. With -CategoriesCsv: loaded with load-master-data.ps1 -Apply.
Paths are given at run time; no hospital data lives in the repository.
.PARAMETER Force
Accept an explicit -Version whose GitHub checks are not all green.
.PARAMETER SkipDrive
Skip Google Drive backup setup for now (run drive-backup.ps1 -Setup later).
.PARAMETER SkipSchedule
Skip the hourly backup task for now (run schedule-backup.ps1 -Install later).

.EXAMPLE
pwsh -File .\setup-ces-bcm.ps1
.EXAMPLE
pwsh -File .\setup-ces-bcm.ps1 -Version v0.1.0 -WardsCsv D:\wards.csv -CategoriesCsv D:\categories.csv
#>
[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\MEP\app',
    [string]$Version = '',
    [string]$SourceZip = '',
    [string]$WardsCsv = '',
    [string]$CategoriesCsv = '',
    [switch]$Force,
    [switch]$SkipDrive,
    [switch]$SkipSchedule
)

# This first block must stay parseable and runnable by Windows PowerShell 5.1
# (no ternary, no ??, no &&/||): a 5.1 launch gets the exact winget command
# instead of a parser error.
if ($PSVersionTable.PSVersion.Major -lt 7) {
    Write-Host 'This setup needs PowerShell 7 (you started Windows PowerShell 5.1).' -ForegroundColor Red
    Write-Host 'Install it with this command, then open "PowerShell 7" from the Start menu as administrator and run this script again:'
    Write-Host '    winget install -e --id Microsoft.PowerShell'
    exit 1
}

$ErrorActionPreference = 'Stop'
$libPath = Join-Path $PSScriptRoot 'lib/HostSetup.ps1'
if (-not (Test-Path -LiteralPath $libPath)) {
    Write-Host "lib/HostSetup.ps1 was not found beside this script ($PSScriptRoot). Run it from a full copy of the repository." -ForegroundColor Red
    exit 1
}
. $libPath

Write-Host ''
Write-Host '=== Medical Equipment Pool -- CES-BCM host setup ===' -ForegroundColor Cyan
Show-MepOwnerDecisionNotice

try {
    if (([bool]$WardsCsv) -ne ([bool]$CategoriesCsv)) {
        throw 'Give both -WardsCsv and -CategoriesCsv, or neither.'
    }
    if ($SourceZip -and -not (Test-Path -LiteralPath $SourceZip -PathType Leaf)) {
        throw "ZIP file not found: $SourceZip"
    }
    foreach ($p in @($WardsCsv, $CategoriesCsv)) {
        if ($p -and -not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "CSV file not found: $p" }
    }
    $InstallDir = [IO.Path]::GetFullPath($InstallDir)
    $statePath = Get-MepSetupStatePath -InstallDir $InstallDir
    $historyPath = Get-MepVersionHistoryPath -Root $InstallDir

    $steps = [ordered]@{}

    $steps['preflight'] = {
        $facts = Get-MepHostFacts -InstallDir $InstallDir
        $res = Test-MepPreflightFacts -Facts $facts
        foreach ($w in $res.Warnings) { Write-Host "WARNING: $w" -ForegroundColor Yellow }
        if ($res.Errors.Count -gt 0) {
            foreach ($e in $res.Errors) { Write-Host "  - $e" -ForegroundColor Red }
            throw 'Preflight failed. Fix the items above and run this command again; nothing was changed.'
        }
        Write-Host 'Windows 11, administrator, PowerShell 7, RAM and disk: OK' -ForegroundColor Green
    }

    $steps['prerequisites'] = {
        if ((Invoke-MepEnsureDocker) -eq 'halt') { return 'halt' }
        if (-not $SourceZip) {
            if ((Invoke-MepEnsureGit) -eq 'halt') { return 'halt' }
        }
        Write-Host 'Docker Desktop is running.' -ForegroundColor Green
        return 'done'
    }

    $steps['source'] = {
        if ($SourceZip) {
            $info = Install-MepSourceFromZip -ZipPath $SourceZip -TargetDir $InstallDir -ExpectedSha $Version
            $recordSha = if ($info.Sha) { $info.Sha } else { 'unverified-zip' }
            Set-MepVersionRecord -Path $historyPath -Sha $recordSha -Ref $recordSha -Source zip -ZipSha256 $info.Sha256
            Write-Host "Source installed from ZIP: $recordSha"
            return 'done'
        }
        $sha = Invoke-MepGitSourceStep -InstallDir $InstallDir -HistoryPath $historyPath -Version $Version -Force:$Force
        Write-Host "Source ready at $sha"
        return 'done'
    }

    $steps['install'] = {
        Write-Host 'Running install.ps1 (it will ask for the LAN URL, port and the Administrator details).'
        $code = Invoke-MepDeploymentScript -Root $InstallDir -Script 'install.ps1'
        if ($code -ne 0) { throw "install.ps1 failed (exit $code). Fix the cause shown above and run this command again; install.ps1 is safe to repeat." }
        return 'done'
    }

    $steps['masterdata'] = {
        if (-not $WardsCsv) {
            Write-Host 'No -WardsCsv/-CategoriesCsv given: master data skipped. Load it later with'
            Write-Host '  .\load-master-data.ps1 -WardsCsv <file> -CategoriesCsv <file> -Apply   (runbook section 8.5)'
            return 'skipped'
        }
        $wards = (Resolve-Path -LiteralPath $WardsCsv).ProviderPath
        $cats = (Resolve-Path -LiteralPath $CategoriesCsv).ProviderPath
        $code = Invoke-MepDeploymentScript -Root $InstallDir -Script 'load-master-data.ps1' `
            -ScriptArguments @('-WardsCsv', $wards, '-CategoriesCsv', $cats, '-Apply')
        if ($code -ne 0) { throw "load-master-data.ps1 failed (exit $code). Nothing is half-written (one transaction). Check the CSV files and run this command again." }
        return 'done'
    }

    $steps['drive'] = {
        if ($SkipDrive) { Write-Host 'Drive backup skipped (-SkipDrive).'; return 'skipped' }
        Write-Host 'Google Drive backup needs an OAuth client created once in Google Cloud (runbook PR24_BACKUP_RESTORE_RUNBOOK.md section 12.2).'
        if (-not (Read-MepConfirm 'Is the OAuth client ID/secret ready to enter now?')) {
            Write-Host 'Skipped for now. Later: .\drive-backup.ps1 -Setup'
            return 'skipped'
        }
        Write-Host 'You will get a URL and a code: open the URL on any device, sign in as the department Google account and approve.'
        $code = Invoke-MepDeploymentScript -Root $InstallDir -Script 'drive-backup.ps1' -ScriptArguments @('-Setup')
        if ($code -ne 0) { throw "drive-backup.ps1 -Setup failed (exit $code). Run this command again to retry." }
        return 'done'
    }

    $steps['schedule'] = {
        if ($SkipSchedule) { Write-Host 'Backup schedule skipped (-SkipSchedule).'; return 'skipped' }
        Write-Host 'The hourly backup task runs whether or not anyone is signed in, so Windows asks for this account''s password.'
        Write-Host 'It goes straight to Task Scheduler; this script never sees, stores or prints it.'
        if (-not (Read-MepConfirm 'Register the hourly backup task now?')) {
            Write-Host 'Skipped for now. Later: .\schedule-backup.ps1 -Install'
            return 'skipped'
        }
        $code = Invoke-MepDeploymentScript -Root $InstallDir -Script 'schedule-backup.ps1' -ScriptArguments @('-Install')
        if ($code -ne 0) { throw "schedule-backup.ps1 -Install failed (exit $code). Run this command again to retry." }
        return 'done'
    }

    $steps['final'] = {
        Invoke-MepDeploymentScript -Root $InstallDir -Script 'status.ps1' | Out-Null
        return 'done'
    }

    # A finished source step is repeated when -Version now names a different
    # commit (a dirty tree is refused before anything changes).
    Reset-MepStaleSourceStep -StatePath $statePath -InstallDir $InstallDir -Version $Version -SourceZip $SourceZip | Out-Null

    $outcome = Invoke-MepSetupSteps -StatePath $statePath -Steps $steps

    if ($outcome.Halted) {
        Write-Host ''
        Write-Host "Setup paused at step '$($outcome.HaltedStep)'. Follow the instruction above, then run the same command again." -ForegroundColor Yellow
        exit 0
    }

    Write-Host ''
    Write-Host '=== Summary ===' -ForegroundColor Cyan
    $port = Get-MepConfiguredPort -Root $InstallDir
    $urls = @(Get-MepLanUrls -Port $port)
    if ($urls.Count -eq 0) { Write-Host "  URL on this PC: http://localhost:$port" }
    foreach ($u in $urls) { Write-Host "  LAN URL: $u" }
    # Report the ACTUAL source on disk (git HEAD), not a possibly stale record
    # (e.g. after a manual `git checkout`); the record is brought in line so
    # update-online.ps1 -Rollback targets the right previous version.
    Sync-MepVersionRecordWithHead -InstallDir $InstallDir -HistoryPath $historyPath | Out-Null
    $hist = Get-MepVersionHistory -Path $historyPath
    if ($hist.current) { Write-Host "  Installed version: $($hist.current.sha)" }
    foreach ($s in $outcome.AlreadyDone + $outcome.Ran) { Write-Host "  done    : $s" -ForegroundColor Green }
    foreach ($s in $outcome.Skipped) { Write-Host "  PENDING : $s (run this command again, or the script named above, when ready)" -ForegroundColor Yellow }
    Show-MepFirewallGuidance -Port $port
    Show-MepAutoLogonGuidance
    Write-Host ''
    Write-Host 'This setup does not prove production readiness or any backup RPO target.' -ForegroundColor Yellow
    Write-Host "Production deployment is the Owner's decision." -ForegroundColor Yellow
    exit 0
}
catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Nothing was deleted. Fix the cause and run the same command again; setup resumes.' -ForegroundColor Red
    exit 1
}
