# Host bootstrap + Owner-triggered online/offline update helpers for the
# department PC (CES-BCM). Used by setup-ces-bcm.ps1 and update-online.ps1.
#
# SCOPE. This module only decides WHICH source tree is on disk and walks the
# one-time host setup steps. It contains no build, backup, migration or
# restore logic: after the source is in place, every deployment action is
# the existing install.ps1 / update.ps1 / load-master-data.ps1 /
# drive-backup.ps1 / schedule-backup.ps1, run as child processes so each
# resolves its own lib/ from the on-disk tree it lives in.
#
# GUARANTEES (covered by tests/Invoke-HostSetupTests.ps1):
#   * never deletes data, Docker volumes, backups or .env. The only deletion
#     is the superseded SOURCE CODE during a -SourceZip replace, and that
#     skips the preserved runtime names below.
#   * never runs `docker compose down -v`.
#   * never asks for, stores or prints a token or password. The public
#     repository needs no GitHub token; Windows and OAuth prompts are done by
#     the existing child scripts.
#   * never schedules or triggers an update on its own.
#
# This file deliberately does NOT dot-source lib/Common.ps1: Common.ps1
# binds paths to the directory it lives in, whereas setup runs before the
# install tree exists. Every native call goes through the one seam
# Invoke-MepHostCommand, and the GitHub API through Invoke-MepGitHubApi, so
# tests replace exactly those.

Set-StrictMode -Version Latest

$Script:MepRepoSlug = 'manmenex/medical-equipment-pool'
$Script:MepRepoUrl = 'https://github.com/manmenex/medical-equipment-pool.git'
$Script:MepGitHubApiBase = 'https://api.github.com'
$Script:MepDefaultInstallDir = 'C:\MEP\app'
$Script:MepMigrationsPath = 'backend/alembic/versions'
$Script:MepMinRamBytes = 7GB       # an "8 GB" PC reports ~7.7-7.9 GB usable
$Script:MepMinFreeDiskBytes = 15GB
# Names under deployment/local-staging that hold this host's runtime state.
# A -SourceZip replace never deletes these.
$Script:MepPreservedRuntimeNames = @(
    '.env', '.install-metadata.json', '.install.lock', '.version-history.json',
    'backups', 'logs', 'secrets'
)

# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------

function Invoke-MepHostCommand {
    <#
    .SYNOPSIS
    The single seam for every native command in this module. Executable
    plus argument array only (never a command string), explicit exit-code
    check. Returns @{ ExitCode; Output } where Output is always an array.
    #>
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [AllowEmptyCollection()] [string[]]$Arguments,
        [switch]$AllowNonZeroExit,
        [switch]$NoCapture
    )
    if ($NoCapture) {
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
        $output = @()
    }
    else {
        $output = @(& $FilePath @Arguments 2>&1 | ForEach-Object { "$_" })
        $exitCode = $LASTEXITCODE
    }
    if ($exitCode -ne 0 -and -not $AllowNonZeroExit) {
        throw "$FilePath exited with code $exitCode."
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
}

function Invoke-MepGit {
    param(
        [string]$RepoDir,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [switch]$AllowNonZeroExit
    )
    $all = @()
    if ($RepoDir) { $all += @('-C', $RepoDir) }
    $all += $Arguments
    return Invoke-MepHostCommand -FilePath 'git' -Arguments $all -AllowNonZeroExit:$AllowNonZeroExit
}

function Invoke-MepGitHubApi {
    <#
    .SYNOPSIS
    Unauthenticated GET against the public GitHub API. No token is ever
    sent: the repository is public. (Unauthenticated limit is 60 requests
    per hour per IP; this module uses a handful per run.)
    #>
    param([Parameter(Mandatory)] [string]$Path)
    return Invoke-RestMethod -Uri ($Script:MepGitHubApiBase + $Path) -Method Get -TimeoutSec 30 -Headers @{
        'User-Agent'           = 'mep-ces-bcm-setup'
        'Accept'               = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
    }
}

function Read-MepConfirm {
    param([Parameter(Mandatory)] [string]$Prompt)
    $answer = Read-Host "$Prompt [y/N]"
    return ($answer -match '^(?i:y|yes)$')
}

function Start-MepSleep {
    param([Parameter(Mandatory)] [int]$Seconds)
    Start-Sleep -Seconds $Seconds
}

function Get-MepPwshExecutable {
    $current = (Get-Process -Id $PID -ErrorAction SilentlyContinue).Path
    if ($current -and ((Split-Path -Leaf $current) -in @('pwsh', 'pwsh.exe'))) { return $current }
    return 'pwsh'
}

function Get-MepDeploymentDir {
    param([Parameter(Mandatory)] [string]$Root)
    return Join-Path (Join-Path $Root 'deployment') 'local-staging'
}

function Invoke-MepDeploymentScript {
    <#
    .SYNOPSIS
    Runs one of the existing deployment/local-staging scripts as a child
    pwsh process from the given install tree, with output streamed to the
    console (interactive prompts such as the administrator details, the
    Windows password and the OAuth consent stay with that script; this
    module never sees them). Returns the exit code.
    #>
    param(
        [Parameter(Mandatory)] [string]$Root,
        [Parameter(Mandatory)] [string]$Script,
        [string[]]$ScriptArguments = @()
    )
    $path = Join-Path (Get-MepDeploymentDir $Root) $Script
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Script not found: $path"
    }
    $r = Invoke-MepHostCommand -FilePath (Get-MepPwshExecutable) `
        -Arguments (@('-NoProfile', '-File', $path) + $ScriptArguments) -AllowNonZeroExit -NoCapture
    return $r.ExitCode
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

function Get-MepHostFacts {
    <#
    .SYNOPSIS
    Collects the machine facts preflight needs. Isolated so tests feed
    Test-MepPreflightFacts synthetic facts instead.
    #>
    param([Parameter(Mandatory)] [string]$InstallDir)
    $isWin = [bool]$IsWindows
    $isAdmin = $false
    $ram = 0
    $free = 0
    if ($isWin) {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $isAdmin = ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        $ram = [int64](Get-CimInstance -ClassName Win32_ComputerSystem).TotalPhysicalMemory
        $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($InstallDir))
        $drive = Get-PSDrive -Name ($root.Substring(0, 1)) -ErrorAction SilentlyContinue
        if ($drive) { $free = [int64]$drive.Free }
    }
    return [pscustomobject]@{
        IsWindows     = $isWin
        OsBuild       = [Environment]::OSVersion.Version.Build
        IsAdmin       = $isAdmin
        PwshMajor     = $PSVersionTable.PSVersion.Major
        RamBytes      = $ram
        FreeDiskBytes = $free
    }
}

function Test-MepPreflightFacts {
    <#
    .SYNOPSIS
    Pure evaluation of host facts. Returns @{ Errors = @(); Warnings = @() }.
    Windows 11 is build 22000 or later.
    #>
    param([Parameter(Mandatory)] $Facts)
    $errors = @()
    $warnings = @()
    if (-not $Facts.IsWindows) {
        $errors += 'This script installs the department host and must run on Windows 11.'
    }
    elseif ($Facts.OsBuild -lt 22000) {
        $errors += "Windows 11 is required (build 22000 or later); this is build $($Facts.OsBuild)."
    }
    if ($Facts.IsWindows -and -not $Facts.IsAdmin) {
        $errors += 'Administrator rights are required. Right-click PowerShell 7 and choose "Run as administrator", then run this script again.'
    }
    if ($Facts.PwshMajor -lt 7) {
        $errors += 'PowerShell 7 is required.'
    }
    if ($Facts.IsWindows) {
        if ($Facts.RamBytes -lt $Script:MepMinRamBytes) {
            $errors += ("At least 8 GB of RAM is required; this PC reports {0:N1} GB." -f ($Facts.RamBytes / 1GB))
        }
        if ($Facts.FreeDiskBytes -lt $Script:MepMinFreeDiskBytes) {
            $errors += ("At least 15 GB of free disk space is required on the install drive; {0:N1} GB is free." -f ($Facts.FreeDiskBytes / 1GB))
        }
    }
    return [pscustomobject]@{ Errors = $errors; Warnings = $warnings }
}

function Test-MepCommandExists {
    param([Parameter(Mandatory)] [string]$Name)
    return [bool](Get-Command -Name $Name -ErrorAction SilentlyContinue)
}

function Test-MepDockerEngineUp {
    $r = Invoke-MepHostCommand -FilePath 'docker' -Arguments @('info') -AllowNonZeroExit
    return ($r.ExitCode -eq 0)
}

function Get-MepDockerDesktopPath {
    if (-not $env:ProgramFiles) { return $null }
    $p = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path -LiteralPath $p) { return $p }
    return $null
}

function Install-MepWithWinget {
    param([Parameter(Mandatory)] [string]$Id)
    if (-not (Test-MepCommandExists 'winget')) {
        throw "winget was not found. Install 'App Installer' from the Microsoft Store, then run this script again."
    }
    Invoke-MepHostCommand -FilePath 'winget' -NoCapture -Arguments @(
        'install', '-e', '--id', $Id, '--accept-package-agreements', '--accept-source-agreements') | Out-Null
}

function Invoke-MepEnsureDocker {
    <#
    .SYNOPSIS
    Returns 'done' when the Docker engine answers, otherwise 'halt' after
    telling the operator exactly what to do next. Installs Docker Desktop
    only after an explicit confirmation. A reboot is never forced.
    #>
    $installed = (Test-MepCommandExists 'docker') -or [bool](Get-MepDockerDesktopPath)
    if (-not $installed) {
        Write-Host 'Docker Desktop was not found.' -ForegroundColor Yellow
        if (-not (Read-MepConfirm 'Install Docker Desktop now with winget (winget install -e --id Docker.DockerDesktop)?')) {
            throw 'Docker Desktop is required. Install it, then run this script again.'
        }
        Install-MepWithWinget -Id 'Docker.DockerDesktop'
        # Docker Desktop's Linux containers run on WSL2.
        Invoke-MepHostCommand -FilePath 'wsl' -Arguments @('--install', '--no-distribution') -AllowNonZeroExit -NoCapture | Out-Null
        Write-Host ''
        Write-Host 'Docker Desktop and WSL2 were installed.' -ForegroundColor Green
        Write-Host 'RESTART WINDOWS now, sign in, start Docker Desktop once (accept its terms),' -ForegroundColor Yellow
        Write-Host 'then run this same command again. Setup resumes where it stopped.' -ForegroundColor Yellow
        return 'halt'
    }
    if ((Test-MepCommandExists 'docker') -and (Test-MepDockerEngineUp)) { return 'done' }

    $exe = Get-MepDockerDesktopPath
    if ($exe) {
        Write-Host 'Starting Docker Desktop...'
        Start-Process -FilePath $exe | Out-Null
    }
    for ($i = 0; $i -lt 24; $i++) {
        Start-MepSleep -Seconds 5
        if ((Test-MepCommandExists 'docker') -and (Test-MepDockerEngineUp)) { return 'done' }
    }
    Write-Host 'Docker Desktop is installed but its engine is not running.' -ForegroundColor Yellow
    Write-Host 'Open Docker Desktop, wait until it says "Engine running", then run this command again.' -ForegroundColor Yellow
    return 'halt'
}

function Invoke-MepEnsureGit {
    <#
    .SYNOPSIS
    Returns 'done' when git is on PATH, otherwise installs it (after
    confirmation) and returns 'halt' because the new PATH is only visible
    to a NEW terminal.
    #>
    if (Test-MepCommandExists 'git') { return 'done' }
    Write-Host 'Git was not found.' -ForegroundColor Yellow
    if (-not (Read-MepConfirm 'Install Git now with winget (winget install -e --id Git.Git)?')) {
        throw 'Git is required (or use -SourceZip for an offline install). Install it, then run this script again.'
    }
    Install-MepWithWinget -Id 'Git.Git'
    Write-Host 'Git was installed. Close this window, open a NEW PowerShell 7 as administrator and run this command again.' -ForegroundColor Yellow
    return 'halt'
}

# ---------------------------------------------------------------------------
# Resumable step runner
# ---------------------------------------------------------------------------

function Get-MepSetupStatePath {
    param([Parameter(Mandatory)] [string]$InstallDir)
    return Join-Path (Split-Path -Parent $InstallDir) 'setup-state.json'
}

function Read-MepSetupState {
    <#
    .SYNOPSIS
    Reads the state file. A missing file is a fresh state; a CORRUPT file
    is an error and is never overwritten, because silently starting over
    could repeat steps the operator believes are finished.
    #>
    param([Parameter(Mandatory)] [string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return @{ schemaVersion = 1; steps = @{}; lastError = $null }
    }
    try {
        $state = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable
        if ($null -eq $state -or -not $state.ContainsKey('steps')) { throw 'missing steps' }
        return $state
    }
    catch {
        throw "The setup state file $Path is unreadable ($($_.Exception.Message)). It was NOT modified. Move it aside (rename it) to start the step list over; nothing installed is affected."
    }
}

function Write-MepSetupState {
    param([Parameter(Mandatory)] [string]$Path, [Parameter(Mandatory)] $State)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $tmp = "$Path.tmp"
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tmp -Encoding utf8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Invoke-MepSetupSteps {
    <#
    .SYNOPSIS
    Runs ordered steps, persisting after each. Re-running continues from the
    first step that is not 'done'.

    .DESCRIPTION
    Each step is a scriptblock whose LAST output may be one of:
      'done' (default) -> recorded complete, never run again
      'skipped'        -> optional step not applicable now; re-evaluated on
                          the next run (e.g. master-data CSVs given later)
      'halt'           -> stop cleanly now (e.g. reboot required); the step
                          is NOT recorded complete and runs again next time
    A thrown error is recorded in lastError (message only) and rethrown.
    #>
    param(
        [Parameter(Mandatory)] [string]$StatePath,
        [Parameter(Mandatory)] [System.Collections.IDictionary]$Steps
    )
    $state = Read-MepSetupState -Path $StatePath
    $outcome = [pscustomobject]@{ Halted = $false; HaltedStep = $null; Ran = @(); Skipped = @(); AlreadyDone = @() }
    foreach ($name in @($Steps.Keys)) {
        $existing = $null
        if ($state.steps.ContainsKey($name)) { $existing = $state.steps[$name] }
        if ($existing -and $existing.status -eq 'done') {
            Write-Host "[done earlier] $name"
            $outcome.AlreadyDone += $name
            continue
        }
        Write-Host ''
        Write-Host "=== Step: $name ===" -ForegroundColor Cyan
        try {
            $result = @(& $Steps[$name])
        }
        catch {
            $state.lastError = @{ step = $name; message = $_.Exception.Message; atUtc = (Get-Date).ToUniversalTime().ToString('o') }
            Write-MepSetupState -Path $StatePath -State $state
            throw
        }
        $status = 'done'
        if ($result.Count -gt 0 -and ("$($result[-1])" -in @('done', 'skipped', 'halt'))) { $status = "$($result[-1])" }
        $now = (Get-Date).ToUniversalTime().ToString('o')
        $state.lastError = $null
        if ($status -eq 'halt') {
            $state.steps[$name] = @{ status = 'halted'; atUtc = $now }
            Write-MepSetupState -Path $StatePath -State $state
            $outcome.Halted = $true
            $outcome.HaltedStep = $name
            return $outcome
        }
        $state.steps[$name] = @{ status = $status; atUtc = $now }
        Write-MepSetupState -Path $StatePath -State $state
        if ($status -eq 'skipped') { $outcome.Skipped += $name } else { $outcome.Ran += $name }
    }
    return $outcome
}

# ---------------------------------------------------------------------------
# Version selection (GitHub, unauthenticated)
# ---------------------------------------------------------------------------

function Assert-MepSafeRef {
    <#
    .SYNOPSIS
    A tag, branch or commit SHA only. Rejects anything that could be read as
    a git option or contain shell/ref-syntax tricks.
    #>
    param([Parameter(Mandatory)] [string]$Ref)
    if ($Ref -notmatch '^[A-Za-z0-9][A-Za-z0-9._/\-]{0,99}$' -or $Ref -match '\.\.') {
        throw "Invalid version '$Ref'. Use a release tag or a commit SHA."
    }
}

function Test-MepCheckRunsGreen {
    <#
    .SYNOPSIS
    NOTE: only GitHub CHECK RUNS (Actions and check-run apps) are evaluated.
    Legacy commit statuses (the /status API) are deliberately not consulted;
    this repository's CI reports as check runs.

    True only when the response lists at least one check run, lists ALL of
    them (not a truncated page), every one has completed, and every
    conclusion is success, neutral or skipped. Anything uncertain is not
    green.
    #>
    param([Parameter(Mandatory)] $Response)
    $total = [int]$Response.total_count
    $runs = @($Response.check_runs)
    if ($total -le 0 -or $runs.Count -lt $total) { return $false }
    foreach ($run in $runs) {
        if ("$($run.status)" -ne 'completed') { return $false }
        if ("$($run.conclusion)" -notin @('success', 'neutral', 'skipped')) { return $false }
    }
    return $true
}

function Get-MepCheckRuns {
    param([Parameter(Mandatory)] [string]$Sha)
    $all = @()
    $total = 0
    for ($page = 1; $page -le 5; $page++) {
        $resp = Invoke-MepGitHubApi -Path "/repos/$($Script:MepRepoSlug)/commits/$Sha/check-runs?per_page=100&page=$page"
        $total = [int]$resp.total_count
        $all += @($resp.check_runs)
        if ($all.Count -ge $total) { break }
    }
    return [pscustomobject]@{ total_count = $total; check_runs = $all }
}

function Test-MepCommitChecksGreen {
    param([Parameter(Mandatory)] [string]$Sha)
    return Test-MepCheckRunsGreen -Response (Get-MepCheckRuns -Sha $Sha)
}

function Get-MepLatestGreenCommit {
    <#
    .SYNOPSIS
    Newest commit on the repository's default branch whose check runs are
    all green, scanning at most -MaxCommits. Throws on any API failure or
    when none qualifies; the caller then requires an explicit -Version.
    #>
    param([int]$MaxCommits = 15)
    try {
        $repo = Invoke-MepGitHubApi -Path "/repos/$($Script:MepRepoSlug)"
        $branch = "$($repo.default_branch)"
        if (-not $branch) { throw 'default branch not reported' }
        $commits = @(Invoke-MepGitHubApi -Path ("/repos/$($Script:MepRepoSlug)/commits?sha=" + [uri]::EscapeDataString($branch) + "&per_page=$MaxCommits"))
    }
    catch {
        throw "Could not query GitHub for the latest verified version ($($_.Exception.Message)). Re-run with -Version <release-tag-or-commit-sha>."
    }
    $skipped = 0
    foreach ($c in $commits) {
        $sha = "$($c.sha)"
        $green = $false
        try { $green = Test-MepCommitChecksGreen -Sha $sha }
        catch {
            throw "Could not read GitHub check results ($($_.Exception.Message)). Re-run with -Version <release-tag-or-commit-sha>."
        }
        if ($green) {
            return [pscustomobject]@{ Sha = $sha; Branch = $branch; NewerNotGreen = $skipped }
        }
        $skipped++
    }
    throw "None of the newest $MaxCommits commits on '$branch' has all checks green. Re-run with -Version <release-tag-or-commit-sha>."
}

function Assert-MepCommitVerified {
    <#
    .SYNOPSIS
    Requires the commit's GitHub checks to be all green unless -Force. An
    API failure also refuses (unverified), because -Force is an explicit
    Owner decision, not a fallback.
    #>
    param([Parameter(Mandatory)] [string]$Sha, [switch]$Force)
    if ($Force) {
        Write-Host "WARNING: -Force given; GitHub checks for $Sha were NOT verified." -ForegroundColor Yellow
        return
    }
    $green = $false
    try { $green = Test-MepCommitChecksGreen -Sha $Sha }
    catch {
        throw "Could not verify GitHub checks for $Sha ($($_.Exception.Message)). Refusing. The Owner may re-run with -Force to accept an unverified version."
    }
    if (-not $green) {
        throw "Commit $Sha does not have all GitHub checks green (missing, running or failed). Refusing. The Owner may re-run with -Force to accept it."
    }
}

# ---------------------------------------------------------------------------
# Git working-tree operations
# ---------------------------------------------------------------------------

function Test-MepIsGitRepo {
    param([Parameter(Mandatory)] [string]$RepoDir)
    return (Test-Path -LiteralPath (Join-Path $RepoDir '.git'))
}

function Assert-MepOriginIsPublicRepo {
    param([Parameter(Mandatory)] [string]$RepoDir)
    $r = Invoke-MepGit -RepoDir $RepoDir -Arguments @('remote', 'get-url', 'origin') -AllowNonZeroExit
    $url = if ($r.ExitCode -eq 0 -and $r.Output.Count -gt 0) { "$($r.Output[0])".Trim() } else { '' }
    $norm = ($url -replace '\.git$', '').TrimEnd('/')
    if ($norm -ne ($Script:MepRepoUrl -replace '\.git$', '')) {
        throw "The 'origin' remote of $RepoDir is not $($Script:MepRepoUrl). Refusing to fetch code from another source."
    }
}

function Test-MepWorkingTreeClean {
    param([Parameter(Mandatory)] [string]$RepoDir)
    $r = Invoke-MepGit -RepoDir $RepoDir -Arguments @('status', '--porcelain', '--untracked-files=normal') -AllowNonZeroExit
    if ($r.ExitCode -ne 0) { return $false }
    return (@($r.Output | Where-Object { "$_".Trim() -ne '' }).Count -eq 0)
}

function Assert-MepWorkingTreeClean {
    param([Parameter(Mandatory)] [string]$RepoDir)
    if (-not (Test-MepWorkingTreeClean -RepoDir $RepoDir)) {
        throw "The source folder $RepoDir has local changes (git status is not clean). Refusing to change versions over them. Ask the system administrator; do not delete files yourself."
    }
}

function Get-MepHeadSha {
    param([Parameter(Mandatory)] [string]$RepoDir)
    $r = Invoke-MepGit -RepoDir $RepoDir -Arguments @('rev-parse', 'HEAD') -AllowNonZeroExit
    if ($r.ExitCode -ne 0 -or $r.Output.Count -eq 0) { return $null }
    $sha = "$($r.Output[0])".Trim()
    if ($sha -match '^[0-9a-f]{40}$') { return $sha }
    return $null
}

function Resolve-MepCommit {
    <#
    .SYNOPSIS
    Resolves a tag, branch or SHA (full or abbreviated) to a full commit
    SHA in the repo, fetching a bare 40-hex SHA from origin if needed.
    Returns $null when it does not exist.
    #>
    param([Parameter(Mandatory)] [string]$RepoDir, [Parameter(Mandatory)] [string]$Ref)
    Assert-MepSafeRef $Ref
    $candidates = @("refs/tags/$Ref", $Ref, "refs/remotes/origin/$Ref")
    foreach ($cand in $candidates) {
        $r = Invoke-MepGit -RepoDir $RepoDir -Arguments @('rev-parse', '--verify', '--quiet', "$cand^{commit}") -AllowNonZeroExit
        if ($r.ExitCode -eq 0 -and $r.Output.Count -gt 0 -and "$($r.Output[0])".Trim() -match '^[0-9a-f]{40}$') {
            return "$($r.Output[0])".Trim()
        }
    }
    if ($Ref -match '^[0-9a-f]{40}$') {
        $f = Invoke-MepGit -RepoDir $RepoDir -Arguments @('fetch', 'origin', $Ref) -AllowNonZeroExit
        if ($f.ExitCode -eq 0) {
            $r = Invoke-MepGit -RepoDir $RepoDir -Arguments @('rev-parse', '--verify', '--quiet', "$Ref^{commit}") -AllowNonZeroExit
            if ($r.ExitCode -eq 0 -and $r.Output.Count -gt 0) { return "$($r.Output[0])".Trim() }
        }
    }
    return $null
}

function Invoke-MepCheckoutDetached {
    param([Parameter(Mandatory)] [string]$RepoDir, [Parameter(Mandatory)] [string]$Sha)
    if ($Sha -notmatch '^[0-9a-f]{40}$') { throw "Refusing to check out '$Sha': a full commit SHA is required." }
    Invoke-MepGit -RepoDir $RepoDir -Arguments @('checkout', '--detach', '--quiet', $Sha) | Out-Null
    $head = Get-MepHeadSha -RepoDir $RepoDir
    if ($head -ne $Sha) { throw "Checkout verification failed: HEAD is '$head', expected '$Sha'." }
}

function Invoke-MepFetchPublicRepo {
    param([Parameter(Mandatory)] [string]$RepoDir)
    $r = Invoke-MepGit -RepoDir $RepoDir -Arguments @('fetch', '--tags', '--prune', '--quiet', 'origin') -AllowNonZeroExit
    if ($r.ExitCode -ne 0) {
        throw 'Could not fetch from GitHub (no network, or GitHub unreachable). Use -SourceZip with a ZIP downloaded elsewhere.'
    }
}

function Initialize-MepSourceClone {
    <#
    .SYNOPSIS
    Ensures InstallDir is a clone of the public repo. Creates it when
    missing/empty, fetches when it already is one, refuses anything else
    (never deletes or overwrites unknown content). autocrlf is off so
    Linux-container build inputs keep LF line endings.
    #>
    param([Parameter(Mandatory)] [string]$InstallDir)
    $exists = Test-Path -LiteralPath $InstallDir
    $empty = (-not $exists) -or (@(Get-ChildItem -LiteralPath $InstallDir -Force).Count -eq 0)
    if ($empty) {
        $parent = Split-Path -Parent $InstallDir
        if ($parent -and -not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Invoke-MepGit -Arguments @('clone', '--quiet', '-c', 'core.autocrlf=false', '-c', 'core.longpaths=true', $Script:MepRepoUrl, $InstallDir) | Out-Null
        return
    }
    if (-not (Test-MepIsGitRepo -RepoDir $InstallDir)) {
        throw "$InstallDir exists, is not empty and is not a git clone. Refusing to touch it. Choose another -InstallDir or move it away yourself."
    }
    Assert-MepOriginIsPublicRepo -RepoDir $InstallDir
    Invoke-MepFetchPublicRepo -RepoDir $InstallDir
}

# ---------------------------------------------------------------------------
# Version history (installed / previous)
# ---------------------------------------------------------------------------

function Get-MepVersionHistoryPath {
    param([Parameter(Mandatory)] [string]$Root)
    return Join-Path (Get-MepDeploymentDir $Root) '.version-history.json'
}

function Get-MepVersionHistory {
    param([Parameter(Mandatory)] [string]$Path)
    $empty = [pscustomobject]@{ current = $null; previous = $null }
    if (-not (Test-Path -LiteralPath $Path)) { return $empty }
    try {
        $h = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        $cur = if ($h.PSObject.Properties.Name -contains 'current') { $h.current } else { $null }
        $prev = if ($h.PSObject.Properties.Name -contains 'previous') { $h.previous } else { $null }
        return [pscustomobject]@{ current = $cur; previous = $prev }
    }
    catch {
        throw "The version history file $Path is unreadable. It was not modified."
    }
}

function Set-MepVersionRecord {
    <#
    .SYNOPSIS
    Records the version now installed. The version it replaces becomes
    'previous' (PreviousSha, or else the recorded current). Called only
    after a successful install/update.
    #>
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Sha,
        [string]$Ref = '',
        [ValidateSet('git', 'zip')] [string]$Source = 'git',
        [string]$PreviousSha = '',
        [string]$ZipSha256 = ''
    )
    $h = Get-MepVersionHistory -Path $Path
    $prev = $h.previous
    if ($PreviousSha -and $PreviousSha -ne $Sha) {
        if ($h.current -and "$($h.current.sha)" -eq $PreviousSha) { $prev = $h.current }
        else { $prev = [pscustomobject]@{ sha = $PreviousSha; ref = $PreviousSha; source = 'git'; atUtc = $null } }
    }
    elseif ($h.current -and "$($h.current.sha)" -ne $Sha) {
        $prev = $h.current
    }
    $record = [pscustomobject]@{
        current  = [pscustomobject]@{
            sha = $Sha; ref = $(if ($Ref) { $Ref } else { $Sha }); source = $Source
            zipSha256 = $ZipSha256; atUtc = (Get-Date).ToUniversalTime().ToString('o')
        }
        previous = $prev
    }
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Path -Encoding utf8
}

# ---------------------------------------------------------------------------
# Migration boundary (rollback safety)
# ---------------------------------------------------------------------------

function Get-MepMigrationNamesFromGit {
    param([Parameter(Mandatory)] [string]$RepoDir, [Parameter(Mandatory)] [string]$Ref)
    $r = Invoke-MepGit -RepoDir $RepoDir -Arguments @('ls-tree', '-r', '--name-only', $Ref, '--', $Script:MepMigrationsPath) -AllowNonZeroExit
    if ($r.ExitCode -ne 0) { throw "Could not list database migrations at $Ref." }
    return @($r.Output | Where-Object { "$_" -match '\.py$' } | ForEach-Object { ("$_" -split '/')[-1] })
}

function Get-MepMigrationNamesFromDir {
    param([Parameter(Mandatory)] [string]$Root)
    $dir = Join-Path (Join-Path (Join-Path $Root 'backend') 'alembic') 'versions'
    if (-not (Test-Path -LiteralPath $dir)) { return @() }
    return @(Get-ChildItem -LiteralPath $dir -Filter '*.py' -File | ForEach-Object { $_.Name })
}

function Get-MepMigrationBoundary {
    <#
    .SYNOPSIS
    Moving from a newer tree to an older one crosses a migration boundary
    when the newer tree has migration files the older one lacks: the
    database may already carry those revisions, and the older code cannot
    interpret them. Alembic downgrades are never run automatically.
    #>
    param([string[]]$FromNames = @(), [string[]]$ToNames = @())
    $missing = @($FromNames | Where-Object { $_ -notin $ToNames } | Sort-Object)
    return [pscustomobject]@{ Crosses = ($missing.Count -gt 0); Migrations = $missing }
}

function Get-MepLatestBackupPath {
    param([Parameter(Mandatory)] [string]$Root)
    $dir = Join-Path (Get-MepDeploymentDir $Root) 'backups'
    if (-not (Test-Path -LiteralPath $dir)) { return $null }
    $f = Get-ChildItem -LiteralPath $dir -Filter '*.dump' -File -Recurse |
        Where-Object { Test-Path -LiteralPath ($_.FullName -replace '\.dump$', '.manifest.json') } |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if ($f) { return $f.FullName }
    return $null
}

# ---------------------------------------------------------------------------
# Offline ZIP
# ---------------------------------------------------------------------------

function Get-MepZipComment {
    <#
    .SYNOPSIS
    Reads the archive comment from the End Of Central Directory record.
    GitHub "Download ZIP" archives (git archive) store the commit SHA there.
    Returns $null when absent.
    #>
    param([Parameter(Mandatory)] [string]$Path)
    $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $n = [int][Math]::Min($fs.Length, 65557)
        if ($n -lt 22) { return $null }
        [void]$fs.Seek(-[int64]$n, [IO.SeekOrigin]::End)
        $buf = New-Object byte[] $n
        $off = 0
        while ($off -lt $n) {
            $got = $fs.Read($buf, $off, $n - $off)
            if ($got -le 0) { break }
            $off += $got
        }
        for ($i = $n - 22; $i -ge 0; $i--) {
            if ($buf[$i] -eq 0x50 -and $buf[$i + 1] -eq 0x4B -and $buf[$i + 2] -eq 5 -and $buf[$i + 3] -eq 6) {
                $len = [int]$buf[$i + 20] + ([int]$buf[$i + 21] * 256)
                if ($i + 22 + $len -eq $n -and $len -gt 0) {
                    return [Text.Encoding]::ASCII.GetString($buf, $i + 22, $len).Trim()
                }
                return $null
            }
        }
        return $null
    }
    finally { $fs.Dispose() }
}

function Test-MepSourceZip {
    <#
    .SYNOPSIS
    Validates a source ZIP and establishes its commit SHA where possible.

    .DESCRIPTION
    Requires a single top-level folder (GitHub's layout) containing
    deployment/local-staging/compose.yml and update.ps1 and
    backend/alembic/versions. The commit SHA comes from the archive comment
    (GitHub embeds it) or, failing that, a 40-hex suffix on the folder name.
    With -ExpectedSha (a commit SHA, >= 7 hex digits) the ZIP must match; if
    the ZIP carries no embedded SHA the expectation cannot be checked and the
    ZIP is refused rather than trusted. Without -ExpectedSha an unverifiable
    ZIP is accepted with a loud warning (Sha = $null).
    #>
    param([Parameter(Mandatory)] [string]$ZipPath, [string]$ExpectedSha = '')
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { throw "ZIP file not found: $ZipPath" }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try { $zip = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $ZipPath).ProviderPath) }
    catch { throw "$ZipPath is not a valid ZIP archive ($($_.Exception.Message))." }
    try {
        $names = @($zip.Entries | ForEach-Object { $_.FullName })
    }
    finally { $zip.Dispose() }
    $roots = @($names | ForEach-Object { ($_ -split '/')[0] } | Where-Object { $_ } | Select-Object -Unique)
    if ($roots.Count -ne 1) {
        throw 'The ZIP must contain exactly one top-level folder, as produced by GitHub "Download ZIP". Do not re-zip it.'
    }
    $root = $roots[0]
    foreach ($required in @("$root/deployment/local-staging/compose.yml", "$root/deployment/local-staging/update.ps1")) {
        if ($required -notin $names) { throw "The ZIP is not this project's source: '$required' is missing." }
    }
    if (-not ($names | Where-Object { $_ -like "$root/backend/alembic/versions/*" })) {
        throw "The ZIP is not this project's source: backend/alembic/versions is missing."
    }

    $sha = $null
    $comment = Get-MepZipComment -Path $ZipPath
    if ($comment -and $comment -match '^[0-9a-f]{40}$') { $sha = $comment }
    elseif ($root -match '-([0-9a-f]{40})$') { $sha = $Matches[1] }

    if ($ExpectedSha) {
        if ($ExpectedSha -notmatch '^[0-9a-fA-F]{7,40}$') {
            throw "-Version with -SourceZip must be the expected commit SHA (7 to 40 hex digits); got '$ExpectedSha'."
        }
        if (-not $sha) {
            throw 'The ZIP carries no embedded commit SHA, so -Version cannot be checked against it. Download the ZIP of the exact commit from GitHub (its page: Code > Download ZIP) or omit -Version and accept that the ZIP is unverified.'
        }
        if (-not $sha.StartsWith($ExpectedSha.ToLowerInvariant())) {
            throw "The ZIP is commit $sha but -Version expects $ExpectedSha. Refusing."
        }
    }
    $hash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    return [pscustomobject]@{ Root = $root; Sha = $sha; Sha256 = $hash; Verified = [bool]($ExpectedSha -and $sha) }
}

function Expand-MepSourceZip {
    <#
    .SYNOPSIS
    Extracts into an empty directory, entry by entry, refusing any entry
    that would land outside it. Returns the extracted project root.
    #>
    param([Parameter(Mandatory)] [string]$ZipPath, [Parameter(Mandatory)] [string]$Destination, [Parameter(Mandatory)] [string]$Root)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $destFull = [IO.Path]::GetFullPath($Destination).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $prefix = $destFull + [IO.Path]::DirectorySeparatorChar
    $zip = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $ZipPath).ProviderPath)
    try {
        foreach ($e in $zip.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $destFull $e.FullName))
            if (-not $target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "ZIP entry '$($e.FullName)' would extract outside the target folder. Refusing."
            }
            if ($e.FullName.EndsWith('/')) {
                New-Item -ItemType Directory -Path $target -Force | Out-Null
                continue
            }
            $parent = Split-Path -Parent $target
            if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $target, $true)
        }
    }
    finally { $zip.Dispose() }
    return Join-Path $destFull $Root
}

function Assert-MepRecognisedInstallDir {
    <#
    .SYNOPSIS
    The code-replace below deletes files, so it only acts on a directory
    that is empty/missing or demonstrably this project's install tree.
    #>
    param([Parameter(Mandatory)] [string]$TargetDir)
    $full = [IO.Path]::GetFullPath($TargetDir)
    if ($full -eq [IO.Path]::GetPathRoot($full) -or $full.TrimEnd('\', '/').Length -lt 6) {
        throw "Refusing to use '$TargetDir' as an install folder."
    }
    if (-not (Test-Path -LiteralPath $TargetDir)) { return }
    if (@(Get-ChildItem -LiteralPath $TargetDir -Force).Count -eq 0) { return }
    $dep = Get-MepDeploymentDir $TargetDir
    $recognised = Test-Path -LiteralPath (Join-Path $dep 'compose.yml')
    foreach ($n in $Script:MepPreservedRuntimeNames) {
        if (Test-Path -LiteralPath (Join-Path $dep $n)) { $recognised = $true }
    }
    if (-not $recognised) {
        throw "$TargetDir is not empty and is not a Medical Equipment Pool install folder. Refusing to replace its contents."
    }
}

function Join-MepRelative {
    param([Parameter(Mandatory)] [string]$Base, [Parameter(Mandatory)] [string]$Relative)
    $p = $Base
    foreach ($seg in ($Relative -split '/')) { $p = Join-Path $p $seg }
    return $p
}

function Get-MepSourceUnits {
    <#
    .SYNOPSIS
    The replaceable units of an install tree as '/'-separated relative
    paths: every top-level item, except that deployment/ and
    deployment/local-staging/ are opened one level so the preserved runtime
    names (.env, backups, ...) are never a unit.
    #>
    param([Parameter(Mandatory)] [string]$Root)
    $units = @()
    foreach ($child in @(Get-ChildItem -LiteralPath $Root -Force)) {
        if ($child.Name -eq 'deployment' -and $child.PSIsContainer) {
            foreach ($d in @(Get-ChildItem -LiteralPath $child.FullName -Force)) {
                if ($d.Name -eq 'local-staging' -and $d.PSIsContainer) {
                    foreach ($f in @(Get-ChildItem -LiteralPath $d.FullName -Force)) {
                        if ($f.Name -in $Script:MepPreservedRuntimeNames) { continue }
                        $units += "deployment/local-staging/$($f.Name)"
                    }
                }
                else { $units += "deployment/$($d.Name)" }
            }
        }
        else { $units += $child.Name }
    }
    return $units
}

function Get-MepFreeBytes {
    param([Parameter(Mandatory)] [string]$Path)
    $full = [IO.Path]::GetFullPath($Path)
    return [int64]([IO.DriveInfo]::new([IO.Path]::GetPathRoot($full))).AvailableFreeSpace
}

function Copy-MepUnit {
    <# Seam: one unit copy. Tests replace it to inject a failure. #>
    param([Parameter(Mandatory)] [string]$Source, [Parameter(Mandatory)] [string]$Destination)
    $parent = Split-Path -Parent $Destination
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function Install-MepSourceTree {
    <#
    .SYNOPSIS
    Replaces the SOURCE CODE in TargetDir with the staged tree, leaving the
    preserved runtime names under deployment/local-staging (.env, backups,
    logs, secrets, metadata) untouched. Stale code is removed first so an
    old Alembic migration cannot linger beside the new ones.

    .DESCRIPTION
    Transactional. Checks free space against the staged size first. Each
    superseded unit is RENAMED into a sibling .mep-old-<guid> folder (same
    volume, so no copy and no data loss), the staged units are copied in, and
    only after every copy succeeded is .mep-old removed. On any failure
    (antivirus lock, disk full, long path, Ctrl+C) partial copies are removed
    and every moved unit is moved back, so the tree is never left
    half-installed.
    #>
    param([Parameter(Mandatory)] [string]$StagedRoot, [Parameter(Mandatory)] [string]$TargetDir)
    Assert-MepRecognisedInstallDir -TargetDir $TargetDir
    if (-not (Test-Path -LiteralPath (Join-Path (Get-MepDeploymentDir $StagedRoot) 'compose.yml'))) {
        throw 'The staged source is incomplete (deployment/local-staging/compose.yml missing); nothing was changed.'
    }
    if (-not (Test-Path -LiteralPath $TargetDir)) { New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null }

    $stagedBytes = [int64](Get-ChildItem -LiteralPath $StagedRoot -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum
    $needed = $stagedBytes + 200MB
    $free = Get-MepFreeBytes -Path $TargetDir
    if ($free -lt $needed) {
        throw ("Not enough free disk space to replace the code: {0:N0} MB needed, {1:N0} MB free. Nothing was changed." -f ($needed / 1MB), ($free / 1MB))
    }

    $oldRoot = Join-Path (Split-Path -Parent ([IO.Path]::GetFullPath($TargetDir))) ('.mep-old-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    Write-Host "The previous code is kept in $oldRoot until the replace succeeds (do not delete it while this runs)."
    $moved = New-Object System.Collections.Generic.List[string]
    $copied = New-Object System.Collections.Generic.List[string]
    $committed = $false
    $failure = $null
    try {
        foreach ($rel in (Get-MepSourceUnits -Root $TargetDir)) {
            $src = Join-MepRelative $TargetDir $rel
            $dst = Join-MepRelative $oldRoot $rel
            $dstParent = Split-Path -Parent $dst
            if (-not (Test-Path -LiteralPath $dstParent)) { New-Item -ItemType Directory -Path $dstParent -Force | Out-Null }
            Move-Item -LiteralPath $src -Destination $dst
            $moved.Add($rel)
        }
        foreach ($rel in (Get-MepSourceUnits -Root $StagedRoot)) {
            $dst = Join-MepRelative $TargetDir $rel
            $copied.Add($rel)   # recorded first: a half-copied unit must be removed too
            Copy-MepUnit -Source (Join-MepRelative $StagedRoot $rel) -Destination $dst
        }
        $committed = $true
    }
    catch {
        # Ordinary errors only. Ctrl+C raises PipelineStoppedException, which
        # skips this block, so the restore below lives in `finally`.
        $failure = $_.Exception.Message
    }
    finally {
        if (-not $committed) {
            $problems = @()
            foreach ($rel in $copied) {
                $dst = Join-MepRelative $TargetDir $rel
                try { if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force } }
                catch { $problems += "could not remove partial copy $dst" }
            }
            foreach ($rel in $moved) {
                $src = Join-MepRelative $TargetDir $rel
                $old = Join-MepRelative $oldRoot $rel
                try {
                    $parent = Split-Path -Parent $src
                    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
                    Move-Item -LiteralPath $old -Destination $src
                }
                catch { $problems += "could not restore $src from $old" }
            }
            if ($problems.Count -gt 0) {
                throw "Replacing the code was interrupted AND automatic restore was incomplete: $($problems -join '; '). The previous files are in $oldRoot. Ask the system administrator; do not delete that folder."
            }
            if (Test-Path -LiteralPath $oldRoot) {
                try { Remove-Item -LiteralPath $oldRoot -Recurse -Force } catch { Write-Host "WARNING: could not remove leftover folder $oldRoot" -ForegroundColor Yellow }
            }
        }
    }
    if ($null -ne $failure) {
        throw "Replacing the code failed ($failure). The previous version was restored; nothing was changed."
    }
    try { Remove-Item -LiteralPath $oldRoot -Recurse -Force }
    catch { Write-Host "WARNING: the replace succeeded but the leftover folder $oldRoot could not be removed; delete it later." -ForegroundColor Yellow }
}

function Install-MepSourceFromZip {
    <#
    .SYNOPSIS
    Validates, extracts to a sibling staging folder, replaces the code, and
    removes only that staging folder. Returns the Test-MepSourceZip result.
    #>
    param([Parameter(Mandatory)] [string]$ZipPath, [Parameter(Mandatory)] [string]$TargetDir, [string]$ExpectedSha = '')
    $info = Test-MepSourceZip -ZipPath $ZipPath -ExpectedSha $ExpectedSha
    Assert-MepRecognisedInstallDir -TargetDir $TargetDir
    $parent = Split-Path -Parent ([IO.Path]::GetFullPath($TargetDir))
    $staging = Join-Path $parent (".mep-staging-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    try {
        $staged = Expand-MepSourceZip -ZipPath $ZipPath -Destination $staging -Root $info.Root
        Install-MepSourceTree -StagedRoot $staged -TargetDir $TargetDir
    }
    finally {
        if (Test-Path -LiteralPath $staging) {
            try { Remove-Item -LiteralPath $staging -Recurse -Force }
            catch { Write-Host "WARNING: could not remove leftover folder $staging; delete it later." -ForegroundColor Yellow }
        }
    }
    if (-not $info.Sha) {
        Write-Host 'WARNING: this ZIP carries no commit SHA; its version could not be verified. Recorded as "unverified-zip".' -ForegroundColor Yellow
    }
    return $info
}

# ---------------------------------------------------------------------------
# Online / offline update orchestration
# ---------------------------------------------------------------------------

function Show-MepOwnerDecisionNotice {
    Write-Host ''
    Write-Host "Production deployment is the Owner's decision." -ForegroundColor Yellow
    Write-Host 'This script changes the running system only when the Owner has chosen to run it. Nothing updates automatically.'
}

function Show-MepRestoreGuidance {
    param([string]$BackupPath)
    Write-Host ''
    Write-Host 'DATABASE RESTORE (manual, supervised by the Owner):' -ForegroundColor Yellow
    if ($BackupPath) { Write-Host "  Newest verified backup: $BackupPath" }
    Write-Host '  Rehearse it first (never touches the live database):'
    if ($BackupPath) { Write-Host "    .\restore.ps1 -Backup `"$BackupPath`" -KeepRehearsalDatabase" }
    else { Write-Host '    .\restore.ps1 -KeepRehearsalDatabase' }
    Write-Host '  Then promote the verified copy to live by following docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md section 12.6.'
    Write-Host '  No one-word live-restore command exists by design.'
}

function Invoke-MepOnlineUpdate {
    <#
    .SYNOPSIS
    Owner-triggered version change that ends in the existing update.ps1
    (and so its mandatory verified backup). Modes: -Version (git),
    -SourceZip [-Version expected-sha], or -Rollback.

    .PARAMETER RunUpdate
    Scriptblock that runs update.ps1 and returns its exit code. A seam so
    tests can observe ordering without Docker.

    .OUTPUTS
    [pscustomobject] with Outcome: Updated, RolledBack, CodeOnlyRollback or
    Unchanged.
    #>
    param(
        [Parameter(Mandatory)] [string]$Root,
        [string]$Version = '',
        [string]$SourceZip = '',
        [switch]$Rollback,
        [switch]$Force,
        [switch]$ConfirmMigrationRollback,
        [switch]$Yes,
        [Parameter(Mandatory)] [scriptblock]$RunUpdate
    )
    Show-MepOwnerDecisionNotice
    if ($Rollback -and ($Version -or $SourceZip)) { throw '-Rollback cannot be combined with -Version or -SourceZip.' }
    if (-not $Rollback -and -not $Version -and -not $SourceZip) { throw 'Specify -Version <tag-or-sha>, -SourceZip <path>, or -Rollback. Nothing updates by itself.' }
    $historyPath = Get-MepVersionHistoryPath -Root $Root

    if ($SourceZip) { return Invoke-MepZipUpdate -Root $Root -ZipPath $SourceZip -ExpectedSha $Version -Force:$Force -ConfirmMigrationRollback:$ConfirmMigrationRollback -Yes:$Yes -RunUpdate $RunUpdate -HistoryPath $historyPath }

    if (-not (Test-MepIsGitRepo -RepoDir $Root)) {
        throw "$Root is not a git clone (it was installed from a ZIP). Use -SourceZip with the new version's ZIP."
    }
    Assert-MepOriginIsPublicRepo -RepoDir $Root
    Assert-MepWorkingTreeClean -RepoDir $Root
    $head = Get-MepHeadSha -RepoDir $Root
    if (-not $head) { throw 'Could not read the current commit of the source folder.' }

    if ($Rollback) {
        $h = Get-MepVersionHistory -Path $historyPath
        # After a failed update HEAD is ahead of the last good version
        # (current); go back to that. Otherwise go to previous.
        $targetRec = $null
        if ($h.current -and "$($h.current.sha)" -ne $head) { $targetRec = $h.current }
        elseif ($h.previous) { $targetRec = $h.previous }
        if (-not $targetRec -or -not $targetRec.sha) { throw 'No previous version is recorded, so there is nothing to roll back to.' }
        if ("$($targetRec.source)" -eq 'zip') {
            throw "The previous version came from a ZIP (sha $($targetRec.sha)); roll back by running update-online.ps1 -SourceZip with that ZIP."
        }
        $target = Resolve-MepCommit -RepoDir $Root -Ref "$($targetRec.sha)"
        if (-not $target) { throw "The previous version $($targetRec.sha) is not in the local git history. Fetch it with -Version <sha> instead." }
        return Invoke-MepGitChange -Root $Root -Head $head -Target $target -Ref "$($targetRec.ref)" -IsRollback -Force:$Force -ConfirmMigrationRollback:$ConfirmMigrationRollback -Yes:$Yes -RunUpdate $RunUpdate -HistoryPath $historyPath
    }

    Assert-MepSafeRef $Version
    Invoke-MepFetchPublicRepo -RepoDir $Root
    $target = Resolve-MepCommit -RepoDir $Root -Ref $Version
    if (-not $target) { throw "Version '$Version' does not exist in $($Script:MepRepoUrl)." }
    Assert-MepCommitVerified -Sha $target -Force:$Force
    return Invoke-MepGitChange -Root $Root -Head $head -Target $target -Ref $Version -Force:$Force -ConfirmMigrationRollback:$ConfirmMigrationRollback -Yes:$Yes -RunUpdate $RunUpdate -HistoryPath $historyPath
}

function Invoke-MepGitChange {
    param(
        [Parameter(Mandatory)] [string]$Root, [Parameter(Mandatory)] [string]$Head, [Parameter(Mandatory)] [string]$Target,
        [string]$Ref = '', [switch]$IsRollback, [switch]$Force, [switch]$ConfirmMigrationRollback, [switch]$Yes,
        [Parameter(Mandatory)] [scriptblock]$RunUpdate, [Parameter(Mandatory)] [string]$HistoryPath
    )
    if ($Target -eq $Head -and -not $IsRollback) {
        Write-Host "Already at $Target; nothing to change."
        return [pscustomobject]@{ Outcome = 'Unchanged'; Sha = $Head }
    }
    # A target that is an ancestor of HEAD is a downgrade, whichever flag
    # asked for it, so it gets the same migration-boundary treatment.
    $anc = Invoke-MepGit -RepoDir $Root -Arguments @('merge-base', '--is-ancestor', $Target, $Head) -AllowNonZeroExit
    $downgrade = $IsRollback -or ($anc.ExitCode -eq 0 -and $Target -ne $Head)
    $boundary = Get-MepMigrationBoundary -FromNames (Get-MepMigrationNamesFromGit -RepoDir $Root -Ref $Head) `
        -ToNames (Get-MepMigrationNamesFromGit -RepoDir $Root -Ref $Target)

    Write-Host "Current : $Head"
    Write-Host "Target  : $Target$(if ($downgrade) { '  (older: code rollback)' })"
    $codeOnly = $false
    if ($downgrade -and $boundary.Crosses) {
        Write-Host ''
        Write-Host 'This rollback crosses a DATABASE MIGRATION boundary. The newer version added:' -ForegroundColor Red
        $boundary.Migrations | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        Write-Host 'The database may already contain these changes and the older code cannot read them. Migrations are never downgraded automatically.'
        $backup = Get-MepLatestBackupPath -Root $Root
        if (-not $ConfirmMigrationRollback) {
            Show-MepRestoreGuidance -BackupPath $backup
            throw 'Refusing to roll back across a migration boundary. If the Owner has decided to, re-run with -ConfirmMigrationRollback (a verified backup must exist).'
        }
        if (-not $backup) {
            throw 'Refusing: -ConfirmMigrationRollback requires an existing verified backup (backups folder), and none was found. Run .\backup.ps1 first.'
        }
        $codeOnly = $true
    }
    if (-not $Yes -and -not (Read-MepConfirm 'Proceed? The Owner must have decided this change.')) {
        throw 'Cancelled. Nothing was changed.'
    }

    Invoke-MepCheckoutDetached -RepoDir $Root -Sha $Target
    if ($codeOnly) {
        Write-Host ''
        Write-Host 'The source folder is now at the older version, but the running containers and the database were NOT changed and update.ps1 was NOT run (it would fail against the newer database).' -ForegroundColor Yellow
        Show-MepRestoreGuidance -BackupPath (Get-MepLatestBackupPath -Root $Root)
        Write-Host 'After the database is restored from a backup taken at the older version, run .\update.ps1.'
        return [pscustomobject]@{ Outcome = 'CodeOnlyRollback'; Sha = $Target }
    }

    $code = & $RunUpdate
    if ($code -ne 0) {
        Write-Host ''
        Write-Host "update.ps1 did not complete (exit $code). The source folder is at $Target; the last good version was $Head." -ForegroundColor Red
        Write-Host 'Re-run the same command to retry, or run update-online.ps1 -Rollback to return the code to the last good version.' -ForegroundColor Red
        throw 'The update did not complete. Data was not deleted.'
    }
    Set-MepVersionRecord -Path $HistoryPath -Sha $Target -Ref $Ref -Source git -PreviousSha $Head
    Write-Host ''
    Write-Host "Done. Installed version: $Target (previous: $Head)." -ForegroundColor Green
    return [pscustomobject]@{ Outcome = $(if ($IsRollback) { 'RolledBack' } else { 'Updated' }); Sha = $Target }
}

function Invoke-MepZipUpdate {
    param(
        [Parameter(Mandatory)] [string]$Root, [Parameter(Mandatory)] [string]$ZipPath, [string]$ExpectedSha = '',
        [switch]$Force, [switch]$ConfirmMigrationRollback, [switch]$Yes,
        [Parameter(Mandatory)] [scriptblock]$RunUpdate, [Parameter(Mandatory)] [string]$HistoryPath
    )
    $info = Test-MepSourceZip -ZipPath $ZipPath -ExpectedSha $ExpectedSha
    $prevSha = ''
    if (Test-MepIsGitRepo -RepoDir $Root) {
        Assert-MepWorkingTreeClean -RepoDir $Root
        $head = Get-MepHeadSha -RepoDir $Root
        if ($head) { $prevSha = $head }
    }
    if (-not $prevSha) {
        $h = Get-MepVersionHistory -Path $HistoryPath
        if ($h.current) { $prevSha = "$($h.current.sha)" }
    }
    if ($info.Sha -and $prevSha -and $info.Sha -eq $prevSha) {
        Write-Host "Already at $prevSha; nothing to change."
        return [pscustomobject]@{ Outcome = 'Unchanged'; Sha = $prevSha }
    }
    if (-not $info.Verified) {
        Write-Host 'WARNING: the ZIP was not checked against an expected commit SHA. GitHub checks cannot be verified offline.' -ForegroundColor Yellow
        if (-not $Force -and -not $Yes -and -not (Read-MepConfirm 'Continue with an unverified ZIP?')) { throw 'Cancelled. Nothing was changed.' }
    }

    # Migration boundary by file lists: the installed tree vs the ZIP's.
    $stagingCheck = Join-Path (Split-Path -Parent ([IO.Path]::GetFullPath($Root))) (".mep-peek-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    try {
        $peekRoot = Expand-MepSourceZip -ZipPath $ZipPath -Destination $stagingCheck -Root $info.Root
        $boundary = Get-MepMigrationBoundary -FromNames (Get-MepMigrationNamesFromDir -Root $Root) -ToNames (Get-MepMigrationNamesFromDir -Root $peekRoot)
    }
    finally {
        if (Test-Path -LiteralPath $stagingCheck) {
            try { Remove-Item -LiteralPath $stagingCheck -Recurse -Force }
            catch { Write-Host "WARNING: could not remove leftover folder $stagingCheck; delete it later." -ForegroundColor Yellow }
        }
    }
    if ($boundary.Crosses) {
        Write-Host 'This ZIP is OLDER than the installed code: the installed version has migrations the ZIP lacks:' -ForegroundColor Red
        $boundary.Migrations | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        $backup = Get-MepLatestBackupPath -Root $Root
        Show-MepRestoreGuidance -BackupPath $backup
        throw 'Refusing to install older code over a newer database schema. The Owner must restore a backup from the older version first.'
    }

    Write-Host "Installed: $(if ($prevSha) { $prevSha } else { 'unknown' })"
    Write-Host "ZIP      : $(if ($info.Sha) { $info.Sha } else { 'unverified-zip' }) (sha256 $($info.Sha256))"
    if (-not $Yes -and -not (Read-MepConfirm 'Proceed? The Owner must have decided this change.')) { throw 'Cancelled. Nothing was changed.' }

    Install-MepSourceFromZip -ZipPath $ZipPath -TargetDir $Root -ExpectedSha $ExpectedSha | Out-Null
    $code = & $RunUpdate
    if ($code -ne 0) {
        Write-Host "update.ps1 did not complete (exit $code). The source folder now holds the ZIP's code." -ForegroundColor Red
        Write-Host 'Re-run the same command to retry. Data was not deleted.' -ForegroundColor Red
        throw 'The update did not complete.'
    }
    $recordSha = if ($info.Sha) { $info.Sha } else { 'unverified-zip' }
    Set-MepVersionRecord -Path $HistoryPath -Sha $recordSha -Ref $recordSha -Source zip -PreviousSha $prevSha -ZipSha256 $info.Sha256
    Write-Host "Done. Installed version: $recordSha (previous: $(if ($prevSha) { $prevSha } else { 'unknown' }))." -ForegroundColor Green
    return [pscustomobject]@{ Outcome = 'Updated'; Sha = $recordSha }
}

# ---------------------------------------------------------------------------
# Presentation helpers for setup
# ---------------------------------------------------------------------------

function Get-MepLanUrls {
    param([int]$Port = 80)
    $urls = @()
    try {
        foreach ($nic in [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
            if ($nic.OperationalStatus -ne 'Up' -or $nic.NetworkInterfaceType -eq 'Loopback') { continue }
            if ($nic.Name -match '(?i)docker|veth|vEthernet|virbr|bridge|wsl') { continue }
            foreach ($u in $nic.GetIPProperties().UnicastAddresses) {
                if ($u.Address.AddressFamily -ne 'InterNetwork') { continue }
                $t = $u.Address.ToString()
                if ($t.StartsWith('169.254.') -or $t.StartsWith('127.')) { continue }
                $urls += $(if ($Port -eq 80) { "http://$t" } else { "http://${t}:$Port" })
            }
        }
    }
    catch { }
    return @($urls | Select-Object -Unique)
}

function Get-MepConfiguredPort {
    param([Parameter(Mandatory)] [string]$Root)
    $envFile = Join-Path (Get-MepDeploymentDir $Root) '.env'
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile) {
            if ($line -match '^\s*LOCAL_STAGING_HTTP_PORT\s*=\s*(\d{1,5})\s*$') { return [int]$Matches[1] }
        }
    }
    return 80
}

function Show-MepAutoLogonGuidance {
    Write-Host ''
    Write-Host 'OPTIONAL: start the system automatically after a power cut' -ForegroundColor Cyan
    Write-Host '  Backups and the application need Docker Desktop running, which starts when this Windows account signs in.'
    Write-Host '  1. Docker Desktop > Settings > General > tick "Start Docker Desktop when you sign in to your computer".'
    Write-Host '  2. Optional automatic sign-in: Win+R > netplwiz > select the account > untick "Users must enter a user name'
    Write-Host '     and password" > OK. OR use Microsoft Sysinternals "Autologon", which keeps the password encrypted (LSA secret).'
    Write-Host '  Trade-off: anyone who can switch the PC on can use the signed-in account. Decide with the Owner; keep the PC'
    Write-Host '  in a controlled room. This script changes none of this and stores no password.'
}
