<#
.SYNOPSIS
Behavior tests for lib/HostSetup.ps1 (setup-ces-bcm.ps1 and
update-online.ps1): resumable state file, version selection, dirty-tree
refusal, rollback migration-boundary refusal, offline ZIP handling.

.DESCRIPTION
Same dependency-free harness as Invoke-InstallerTests.ps1 (no Pester: CI's
PowerShell job runs this with nothing but `pwsh`). git, docker, winget, the
GitHub API and every prompt are replaced by mocks of the module's own seams
(Invoke-MepHostCommand, Invoke-MepGitHubApi, Read-MepConfirm, ...), so the
real orchestration code runs while nothing touches a network, a daemon or a
real repository. The ZIP tests build real archives in a temp folder.

EVIDENCE CLASS: POWERSHELL UNIT/MOCK. Not executed against a real Windows
host, winget, Docker Desktop or GitHub.

.EXAMPLE
pwsh -NoProfile -File deployment/local-staging/tests/Invoke-HostSetupTests.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:DeploymentRoot = Split-Path -Parent $PSScriptRoot
$script:LibPath = Join-Path $script:DeploymentRoot 'lib/HostSetup.ps1'
$script:Passed = 0
$script:Failed = 0
$script:Failures = @()

function Assert-True {
    param([Parameter(Mandatory)] [bool]$Condition, [Parameter(Mandatory)] [string]$Because)
    if (-not $Condition) { throw "Assertion failed: $Because" }
}

function Assert-Equal {
    param($Expected, $Actual, [Parameter(Mandatory)] [string]$Because)
    if ("$Expected" -ne "$Actual") { throw "Assertion failed: $Because (expected '$Expected', got '$Actual')" }
}

function Assert-Throws {
    param([Parameter(Mandatory)] [scriptblock]$Body, [Parameter(Mandatory)] [string]$Pattern, [Parameter(Mandatory)] [string]$Because)
    $msg = $null
    try { & $Body | Out-Null } catch { $msg = $_.Exception.Message }
    if ($null -eq $msg) { throw "Assertion failed: $Because (nothing was thrown)" }
    if ($msg -notmatch $Pattern) { throw "Assertion failed: $Because (threw '$msg', expected match '$Pattern')" }
}

function Test-Case {
    param([Parameter(Mandatory)] [string]$Name, [Parameter(Mandatory)] [scriptblock]$Body)
    try {
        & $Body
        $script:Passed++
        Write-Host "  PASS  $Name" -ForegroundColor Green
    }
    catch {
        $script:Failed++
        $script:Failures += "$Name :: $($_.Exception.Message)"
        Write-Host "  FAIL  $Name" -ForegroundColor Red
        Write-Host "        $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Invoke-Isolated {
    <# Runs Body in a child scope with the real HostSetup.ps1 dot-sourced. #>
    param([Parameter(Mandatory)] [scriptblock]$Body)
    $runner = {
        param($lib, $body)
        Set-StrictMode -Version Latest
        . $lib
        & $body
    }
    & $runner $script:LibPath $Body
}

function New-TempDir {
    $p = Join-Path ([IO.Path]::GetTempPath()) ('mep-hs-' + [guid]::NewGuid().ToString('N').Substring(0, 10))
    New-Item -ItemType Directory -Path $p -Force | Out-Null
    return $p
}

function Remove-TempDir {
    param([string]$Path)
    if ($Path -and (Test-Path -LiteralPath $Path)) { Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue }
}

$script:ShaA = 'a' * 40
$script:ShaB = 'b' * 40
$script:ShaC = 'c' * 40

# A fake install tree that looks like a git clone with a deployment folder.
function New-FakeInstall {
    param([Parameter(Mandatory)] [string]$Base)
    $root = Join-Path $Base 'app'
    New-Item -ItemType Directory -Path (Join-Path $root '.git') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path (Join-Path $root 'deployment') 'local-staging') -Force | Out-Null
    return $root
}

# Mocks of the module's seams. Dot-sourced INTO the isolated scope; they read
# $ctx from there (PowerShell scoping is dynamic along the call chain).
$script:GitMockBlock = {
    function Invoke-MepHostCommand {
        param([string]$FilePath, [string[]]$Arguments, [switch]$AllowNonZeroExit, [switch]$NoCapture)
        $a = @($Arguments)
        if ($a.Count -gt 2 -and $a[0] -eq '-C') { $a = @($a[2..($a.Count - 1)]) }
        $ctx.Calls += "$FilePath $($a -join ' ')"
        $code = 0
        $out = @()
        if ($FilePath -eq 'git') {
            switch ($a[0]) {
                'remote' { $out = @($ctx.Origin) }
                'status' { if ($ctx.Dirty) { $out = @(' M backend/app/main.py') } }
                'rev-parse' {
                    if ($a -contains 'HEAD') { $out = @($ctx.Head) }
                    else {
                        $ref = $a[$a.Count - 1] -replace '\^\{commit\}$', ''
                        if ($ctx.Refs.ContainsKey($ref)) { $out = @($ctx.Refs[$ref]) } else { $code = 1 }
                    }
                }
                'fetch' { if (-not $ctx.FetchOk) { $code = 128 } }
                'checkout' { $ctx.Head = $a[$a.Count - 1] }
                'ls-tree' {
                    $names = @(); if ($ctx.Migrations.ContainsKey($a[3])) { $names = @($ctx.Migrations[$a[3]]) }
                    $out = @($names | ForEach-Object { "backend/alembic/versions/$_" })
                }
                'merge-base' { if ($ctx.Ancestors -notcontains ("$($a[2])>$($a[3])")) { $code = 1 } }
            }
        }
        if ($code -ne 0 -and -not $AllowNonZeroExit) { throw "$FilePath exited with code $code." }
        return [pscustomobject]@{ ExitCode = $code; Output = @($out) }
    }
    function Read-MepConfirm { param([string]$Prompt) $ctx.Prompts += $Prompt; return [bool]$ctx.Confirm }
    function Invoke-MepGitHubApi {
        param([string]$Path)
        $ctx.ApiCalls += $Path
        if ($ctx.ApiDown) { throw 'network unreachable' }
        if ($Path -match '/commits/([0-9a-f]{40})/check-runs') {
            $state = $ctx.Checks[$Matches[1]]
            if ($state -eq 'error') { throw 'HTTP 500' }
            $conclusion = if ($state -eq 'green') { 'success' } else { 'failure' }
            return [pscustomobject]@{ total_count = 2; check_runs = @(
                    [pscustomobject]@{ status = 'completed'; conclusion = 'success' },
                    [pscustomobject]@{ status = 'completed'; conclusion = $conclusion }) }
        }
        if ($Path -match '/commits\?sha=') { return @($ctx.CommitList | ForEach-Object { [pscustomobject]@{ sha = $_ } }) }
        return [pscustomobject]@{ default_branch = 'main' }
    }
}

function Get-CallIndex {
    param($Calls, [string]$Pattern)
    for ($i = 0; $i -lt @($Calls).Count; $i++) { if (@($Calls)[$i] -like $Pattern) { return $i } }
    return -1
}

function New-Ctx {
    param([hashtable]$Overrides = @{})
    $c = @{
        Calls = @(); ApiCalls = @(); Prompts = @(); Confirm = $true; Dirty = $false; FetchOk = $true; ApiDown = $false
        Head = $script:ShaA; Origin = 'https://github.com/manmenex/medical-equipment-pool.git'
        Refs = @{}; Migrations = @{}; Ancestors = @(); Checks = @{}; CommitList = @(); UpdateExit = 0
    }
    foreach ($k in $Overrides.Keys) { $c[$k] = $Overrides[$k] }
    return $c
}

function New-TestZip {
    param([Parameter(Mandatory)] [string]$Path, [Parameter(Mandatory)] [hashtable]$Entries, [string]$Comment = '')
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force }
    $zip = [IO.Compression.ZipFile]::Open($Path, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($k in $Entries.Keys) {
            $e = $zip.CreateEntry($k)
            $w = New-Object IO.StreamWriter($e.Open())
            $w.Write($Entries[$k])
            $w.Dispose()
        }
    }
    finally { $zip.Dispose() }
    if ($Comment) {
        $bytes = [IO.File]::ReadAllBytes($Path)
        $cb = [Text.Encoding]::ASCII.GetBytes($Comment)
        $n = $bytes.Length
        $bytes[$n - 2] = [byte]($cb.Length -band 0xFF)
        $bytes[$n - 1] = [byte]($cb.Length -shr 8)
        [IO.File]::WriteAllBytes($Path, [byte[]]($bytes + $cb))
    }
}

function Get-SourceEntries {
    param([string]$Root, [string[]]$Migrations = @('0001_init.py'))
    $e = @{
        "$Root/deployment/local-staging/compose.yml" = 'services: {}'
        "$Root/deployment/local-staging/update.ps1"  = '# new update'
        "$Root/README.md"                            = 'new readme'
    }
    foreach ($m in $Migrations) { $e["$Root/backend/alembic/versions/$m"] = '# migration' }
    return $e
}

# ===========================================================================
Write-Host ''
Write-Host 'Setup state file (resume)' -ForegroundColor Cyan

Test-Case 'a failed step is retried on re-run; completed steps are not repeated' {
    $tmp = New-TempDir
    try {
        $r = Invoke-Isolated {
            $sp = Join-Path $tmp 'setup-state.json'
            $ctx = @{ a = 0; b = 0; c = 0; fail = $true }
            $steps = [ordered]@{
                a = { $ctx.a++; return 'done' }
                b = { $ctx.b++ }
                c = { $ctx.c++; if ($ctx.fail) { throw 'boom' }; return 'done' }
            }
            try { Invoke-MepSetupSteps -StatePath $sp -Steps $steps | Out-Null } catch { }
            $afterFirst = Read-MepSetupState -Path $sp
            $ctx.fail = $false
            $out = Invoke-MepSetupSteps -StatePath $sp -Steps $steps
            return [pscustomobject]@{ ctx = $ctx; first = $afterFirst; out = $out }
        }
        Assert-Equal 1 $r.ctx.a 'step a ran once across both runs'
        Assert-Equal 1 $r.ctx.b 'step b ran once across both runs'
        Assert-Equal 2 $r.ctx.c 'failed step c ran again'
        Assert-Equal 'boom' $r.first.lastError.message 'failure recorded'
        Assert-Equal 'done' $r.first.steps.a.status 'a persisted as done'
        Assert-True (-not $r.first.steps.ContainsKey('c')) 'failed step not recorded as done'
        Assert-Equal 2 @($r.out.AlreadyDone).Count 'second run reports a and b as already done'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'skipped steps are re-evaluated; halt stops cleanly and is retried' {
    $tmp = New-TempDir
    try {
        $r = Invoke-Isolated {
            $sp = Join-Path $tmp 'setup-state.json'
            $ctx = @{ md = 0; reboot = $true; after = 0 }
            $steps = [ordered]@{
                masterdata = { $ctx.md++; return 'skipped' }
                prereq     = { if ($ctx.reboot) { return 'halt' }; return 'done' }
                after      = { $ctx.after++ }
            }
            $o1 = Invoke-MepSetupSteps -StatePath $sp -Steps $steps
            $afterHalt = $ctx.after
            $ctx.reboot = $false
            $o2 = Invoke-MepSetupSteps -StatePath $sp -Steps $steps
            return [pscustomobject]@{ ctx = $ctx; o1 = $o1; o2 = $o2; afterHalt = $afterHalt }
        }
        Assert-True $r.o1.Halted 'first run halted'
        Assert-Equal 'prereq' $r.o1.HaltedStep 'halted at prerequisites'
        Assert-Equal 0 $r.afterHalt 'later steps did not run while halted'
        Assert-Equal 2 $r.ctx.md 'skipped step evaluated again on the next run'
        Assert-True (-not $r.o2.Halted) 'second run completes'
        Assert-Equal 1 $r.ctx.after 'later step ran once after the halt cleared'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'a corrupt state file is refused and left untouched' {
    $tmp = New-TempDir
    try {
        $sp = Join-Path $tmp 'setup-state.json'
        Set-Content -LiteralPath $sp -Value '{ not json'
        $ran = Invoke-Isolated {
            try { Invoke-MepSetupSteps -StatePath $sp -Steps ([ordered]@{ a = { 'done' } }) | Out-Null } catch { return $_.Exception.Message }
            return 'no error'
        }
        Assert-True ($ran -match 'unreadable') "corrupt state must throw (got '$ran')"
        Assert-Equal '{ not json' ((Get-Content -LiteralPath $sp -Raw).Trim()) 'file was not modified'
    }
    finally { Remove-TempDir $tmp }
}

# ===========================================================================
Write-Host ''
Write-Host 'Version selection' -ForegroundColor Cyan

Test-Case 'Test-MepCheckRunsGreen: only complete, successful, untruncated results are green' {
    Invoke-Isolated {
        function New-Run($s, $c) { [pscustomobject]@{ status = $s; conclusion = $c } }
        Assert-True (Test-MepCheckRunsGreen ([pscustomobject]@{ total_count = 3; check_runs = @((New-Run 'completed' 'success'), (New-Run 'completed' 'skipped'), (New-Run 'completed' 'neutral')) })) 'success/skipped/neutral is green'
        Assert-True (-not (Test-MepCheckRunsGreen ([pscustomobject]@{ total_count = 2; check_runs = @((New-Run 'completed' 'success'), (New-Run 'completed' 'failure')) }))) 'a failure is not green'
        Assert-True (-not (Test-MepCheckRunsGreen ([pscustomobject]@{ total_count = 2; check_runs = @((New-Run 'completed' 'success'), (New-Run 'in_progress' $null)) }))) 'a running check is not green'
        Assert-True (-not (Test-MepCheckRunsGreen ([pscustomobject]@{ total_count = 0; check_runs = @() }))) 'no checks is not green'
        Assert-True (-not (Test-MepCheckRunsGreen ([pscustomobject]@{ total_count = 5; check_runs = @((New-Run 'completed' 'success')) }))) 'a truncated list is not green'
        Assert-True (-not (Test-MepCheckRunsGreen ([pscustomobject]@{ total_count = 1; check_runs = @((New-Run 'completed' 'cancelled')) }))) 'cancelled is not green'
    } | Out-Null
}

Test-Case 'default version is the newest commit whose checks are all green' {
    $r = Invoke-Isolated {
        . $script:GitMockBlock
        $ctx = New-Ctx
        $ctx.CommitList = @($script:ShaC, $script:ShaB, $script:ShaA)
        $ctx.Checks = @{ $script:ShaC = 'red'; $script:ShaB = 'green'; $script:ShaA = 'green' }
        return Get-MepLatestGreenCommit
    }
    Assert-Equal $script:ShaB $r.Sha 'skips the newer red commit'
    Assert-Equal 1 $r.NewerNotGreen 'reports one newer commit was not green'
    Assert-Equal 'main' $r.Branch 'uses the default branch the API reports'
}

Test-Case 'GitHub API failure or no green commit requires an explicit -Version' {
    Invoke-Isolated {
        . $script:GitMockBlock
        $ctx = New-Ctx -Overrides @{ ApiDown = $true }
        Assert-Throws { Get-MepLatestGreenCommit } '-Version' 'API down'
        $ctx = New-Ctx
        $ctx.CommitList = @($script:ShaC)
        $ctx.Checks = @{ $script:ShaC = 'red' }
        Assert-Throws { Get-MepLatestGreenCommit } '-Version' 'nothing green'
        $ctx.Checks = @{ $script:ShaC = 'error' }
        Assert-Throws { Get-MepLatestGreenCommit } '-Version' 'check API error'
    } | Out-Null
}

Test-Case 'explicit version: red or unverifiable checks refuse unless -Force' {
    Invoke-Isolated {
        . $script:GitMockBlock
        $ctx = New-Ctx -Overrides @{ Checks = @{ $script:ShaA = 'green'; $script:ShaB = 'red' } }
        Assert-Equal $null (Assert-MepCommitVerified -Sha $script:ShaA) 'green passes'
        Assert-Throws { Assert-MepCommitVerified -Sha $script:ShaB } 'checks green' 'red refused'
        Assert-Equal $null (Assert-MepCommitVerified -Sha $script:ShaB -Force) '-Force accepts'
        $ctx.ApiDown = $true
        Assert-Throws { Assert-MepCommitVerified -Sha $script:ShaA } 'Could not verify' 'unverifiable refused'
    } | Out-Null
}

Test-Case 'refs are validated and resolved tag-first' {
    $sha = Invoke-Isolated {
        . $script:GitMockBlock
        foreach ($bad in @('--upload-pack=evil', '-x', 'a..b', 'a b', 'a;b', '')) {
            $threw = $false
            try { Assert-MepSafeRef $bad } catch { $threw = $true }
            if (-not $threw) { throw "ref '$bad' should be rejected" }
        }
        $ctx = New-Ctx -Overrides @{ Refs = @{ 'refs/tags/v1.2.0' = $script:ShaB; 'v1.2.0' = $script:ShaC } }
        Resolve-MepCommit -RepoDir 'x' -Ref 'v1.2.0'
    }
    Assert-Equal $script:ShaB $sha 'tag wins over a same-named branch/ref'
}

# ===========================================================================
Write-Host ''
Write-Host 'Online update: dirty tree, ordering, history' -ForegroundColor Cyan

Test-Case 'dirty working tree is refused before anything is fetched or changed' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $ctx = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx -Overrides @{ Dirty = $true }
            $run = { $ctx.Calls += 'RUN-UPDATE'; 0 }
            try { Invoke-MepOnlineUpdate -Root $root -Version $script:ShaB -Yes -RunUpdate $run | Out-Null } catch { $ctx.Err = $_.Exception.Message }
            return $ctx
        }
        Assert-True ("$($ctx.Err)" -match 'local changes') 'dirty tree refused with a clear message'
        Assert-True (-not ($ctx.Calls -match '^git (fetch|checkout)')) 'no fetch or checkout'
        Assert-True ($ctx.Calls -notcontains 'RUN-UPDATE') 'update.ps1 not run'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'online update order: fetch, verify, detached checkout, update.ps1, then record' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $r = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx -Overrides @{
                Refs = @{ 'refs/tags/v2' = $script:ShaB; $script:ShaA = $script:ShaA }
                Checks = @{ $script:ShaB = 'green' }
                Migrations = @{ $script:ShaA = @('0001.py'); $script:ShaB = @('0001.py', '0002.py') }
            }
            $run = { $ctx.Calls += 'RUN-UPDATE'; $ctx.HeadAtUpdate = $ctx.Head; 0 }
            $res = Invoke-MepOnlineUpdate -Root $root -Version 'v2' -Yes -RunUpdate $run
            return [pscustomobject]@{ ctx = $ctx; res = $res; hist = (Get-MepVersionHistory -Path (Get-MepVersionHistoryPath -Root $root)) }
        }
        $calls = @($r.ctx.Calls)
        $iFetch = Get-CallIndex $calls 'git fetch*'
        $iCheckout = Get-CallIndex $calls 'git checkout --detach*'
        $iUpdate = Get-CallIndex $calls 'RUN-UPDATE'
        Assert-True ($iFetch -ge 0 -and $iFetch -lt $iCheckout -and $iCheckout -lt $iUpdate) "order fetch($iFetch) < checkout($iCheckout) < update($iUpdate)"
        Assert-Equal $script:ShaB $r.ctx.HeadAtUpdate 'update.ps1 ran with the target commit checked out'
        Assert-Equal 'Updated' $r.res.Outcome 'outcome'
        Assert-Equal $script:ShaB $r.hist.current.sha 'current recorded'
        Assert-Equal $script:ShaA $r.hist.previous.sha 'previous recorded'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'a failing update.ps1 records no new version and reports failure' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $r = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx -Overrides @{ Refs = @{ 'refs/tags/v2' = $script:ShaB }; Checks = @{ $script:ShaB = 'green' } }
            $ctx.Migrations = @{ $script:ShaA = @('0001.py'); $script:ShaB = @('0001.py') }
            $run = { 1 }
            try { Invoke-MepOnlineUpdate -Root $root -Version 'v2' -Yes -RunUpdate $run | Out-Null } catch { $ctx.Err = $_.Exception.Message }
            return [pscustomobject]@{ err = $ctx.Err; exists = (Test-Path -LiteralPath (Get-MepVersionHistoryPath -Root $root)) }
        }
        Assert-True ("$($r.err)" -match 'did not complete') 'failure surfaced'
        Assert-True (-not $r.exists) 'no version history written for a failed update'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'non-green target is refused without -Force and never checked out' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $ctx = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx -Overrides @{ Refs = @{ 'refs/tags/v2' = $script:ShaB }; Checks = @{ $script:ShaB = 'red' } }
            try { Invoke-MepOnlineUpdate -Root $root -Version 'v2' -Yes -RunUpdate { 0 } | Out-Null } catch { $ctx.Err = $_.Exception.Message }
            return $ctx
        }
        Assert-True ("$($ctx.Err)" -match 'checks green') 'refused'
        Assert-True (-not ($ctx.Calls -match '^git checkout')) 'no checkout'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'a foreign origin remote is refused' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $msg = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx -Overrides @{ Origin = 'https://example.com/evil/repo.git' }
            try { Invoke-MepOnlineUpdate -Root $root -Version 'v2' -Yes -RunUpdate { 0 } | Out-Null } catch { return $_.Exception.Message }
        }
        Assert-True ("$msg" -match 'not https://github.com/manmenex') 'foreign origin refused'
    }
    finally { Remove-TempDir $tmp }
}

# ===========================================================================
Write-Host ''
Write-Host 'Rollback and migration boundary' -ForegroundColor Cyan

function Invoke-RollbackScenario {
    param(
        [string[]]$MigrationsHead, [string[]]$MigrationsPrev,
        [switch]$ConfirmBoundary, [switch]$WithBackup, [string]$Root
    )
    if ($WithBackup) {
        $b = Join-Path (Join-Path (Join-Path $Root 'deployment') 'local-staging') 'backups'
        New-Item -ItemType Directory -Path $b -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $b 'mep-postgres-localstaging-20260101T000000Z.dump') -Value 'x'
        Set-Content -LiteralPath (Join-Path $b 'mep-postgres-localstaging-20260101T000000Z.manifest.json') -Value '{}'
    }
    return Invoke-Isolated {
        . $script:GitMockBlock
        $ctx = New-Ctx -Overrides @{
            Head = $script:ShaB
            Refs = @{ $script:ShaA = $script:ShaA }
            Migrations = @{ $script:ShaB = $MigrationsHead; $script:ShaA = $MigrationsPrev }
        }
        $hp = Get-MepVersionHistoryPath -Root $Root
        Set-MepVersionRecord -Path $hp -Sha $script:ShaA -Ref 'v1' -Source git
        Set-MepVersionRecord -Path $hp -Sha $script:ShaB -Ref 'v2' -Source git -PreviousSha $script:ShaA
        $run = { $ctx.Calls += 'RUN-UPDATE'; 0 }
        try {
            $ctx.Res = Invoke-MepOnlineUpdate -Root $Root -Rollback -ConfirmMigrationRollback:$ConfirmBoundary -Yes -RunUpdate $run
        }
        catch { $ctx.Err = $_.Exception.Message }
        $ctx.Hist = Get-MepVersionHistory -Path $hp
        return $ctx
    }
}

Test-Case 'rollback across a migration boundary is refused and changes nothing' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $ctx = Invoke-RollbackScenario -MigrationsHead @('0001.py', '0002.py') -MigrationsPrev @('0001.py') -Root $root
        Assert-True ("$($ctx.Err)" -match 'migration boundary') "refused (got '$($ctx.Err)')"
        Assert-True (-not ($ctx.Calls -match '^git checkout')) 'no checkout'
        Assert-True ($ctx.Calls -notcontains 'RUN-UPDATE') 'update.ps1 not run'
        Assert-Equal $script:ShaB $ctx.Hist.current.sha 'history unchanged'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'confirmed boundary rollback still needs a backup' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $ctx = Invoke-RollbackScenario -MigrationsHead @('0001.py', '0002.py') -MigrationsPrev @('0001.py') -ConfirmBoundary -Root $root
        Assert-True ("$($ctx.Err)" -match 'verified backup') "needs a backup (got '$($ctx.Err)')"
        Assert-True (-not ($ctx.Calls -match '^git checkout')) 'no checkout'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'confirmed boundary rollback with a backup switches code only, never runs update.ps1' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $ctx = Invoke-RollbackScenario -MigrationsHead @('0001.py', '0002.py') -MigrationsPrev @('0001.py') -ConfirmBoundary -WithBackup -Root $root
        Assert-Equal 'CodeOnlyRollback' $ctx.Res.Outcome 'code-only outcome'
        Assert-Equal $script:ShaA $ctx.Head 'source folder at the older commit'
        Assert-True ($ctx.Calls -notcontains 'RUN-UPDATE') 'update.ps1 not run against the newer database'
        Assert-Equal $script:ShaB $ctx.Hist.current.sha 'recorded version not advanced (database/containers unchanged)'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'rollback without a migration boundary checks out previous and runs update.ps1' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $ctx = Invoke-RollbackScenario -MigrationsHead @('0001.py') -MigrationsPrev @('0001.py') -Root $root
        Assert-Equal 'RolledBack' $ctx.Res.Outcome 'rolled back'
        Assert-Equal $script:ShaA $ctx.Head 'checked out previous'
        Assert-True ($ctx.Calls -contains 'RUN-UPDATE') 'update.ps1 (mandatory backup) ran'
        Assert-Equal $script:ShaA $ctx.Hist.current.sha 'current is now the old version'
        Assert-Equal $script:ShaB $ctx.Hist.previous.sha 'previous is the version rolled back from'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'rollback after a failed update returns to the last good version, not further back' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $ctx = Invoke-Isolated {
            . $script:GitMockBlock
            # History says B is good (previous A) but HEAD is C: a failed update to C.
            $ctx = New-Ctx -Overrides @{
                Head = $script:ShaC
                Refs = @{ $script:ShaB = $script:ShaB }
                Migrations = @{ $script:ShaC = @('0001.py'); $script:ShaB = @('0001.py') }
            }
            $hp = Get-MepVersionHistoryPath -Root $root
            Set-MepVersionRecord -Path $hp -Sha $script:ShaA -Ref 'v1' -Source git
            Set-MepVersionRecord -Path $hp -Sha $script:ShaB -Ref 'v2' -Source git -PreviousSha $script:ShaA
            Invoke-MepOnlineUpdate -Root $root -Rollback -Yes -RunUpdate { 0 } | Out-Null
            return $ctx
        }
        Assert-Equal $script:ShaB $ctx.Head 'back to the recorded current (last good)'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'rollback with no recorded previous version fails clearly' {
    $tmp = New-TempDir
    try {
        $root = New-FakeInstall $tmp
        $msg = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx
            try { Invoke-MepOnlineUpdate -Root $root -Rollback -Yes -RunUpdate { 0 } | Out-Null } catch { return $_.Exception.Message }
        }
        Assert-True ("$msg" -match 'nothing to roll back') "message (got '$msg')"
    }
    finally { Remove-TempDir $tmp }
}

# ===========================================================================
Write-Host ''
Write-Host 'Offline ZIP' -ForegroundColor Cyan

Test-Case 'ZIP commit SHA is read from the archive comment and compared with -Version' {
    $tmp = New-TempDir
    try {
        $zip = Join-Path $tmp 'src.zip'
        New-TestZip -Path $zip -Entries (Get-SourceEntries -Root 'medical-equipment-pool-main') -Comment $script:ShaB
        $r = Invoke-Isolated {
            $info = Test-MepSourceZip -ZipPath $zip
            $ok = Test-MepSourceZip -ZipPath $zip -ExpectedSha $script:ShaB.Substring(0, 9)
            $bad = ''
            try { Test-MepSourceZip -ZipPath $zip -ExpectedSha $script:ShaA | Out-Null } catch { $bad = $_.Exception.Message }
            return [pscustomobject]@{ info = $info; ok = $ok; bad = $bad }
        }
        Assert-Equal $script:ShaB $r.info.Sha 'sha from comment'
        Assert-True $r.ok.Verified 'prefix match verified'
        Assert-True ($r.bad -match 'Refusing') 'mismatch refused'
        Assert-Equal 64 $r.info.Sha256.Length 'sha256 recorded'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'ZIP sha falls back to the folder name; an unverifiable ZIP cannot satisfy -Version' {
    $tmp = New-TempDir
    try {
        $named = Join-Path $tmp 'named.zip'
        New-TestZip -Path $named -Entries (Get-SourceEntries -Root "medical-equipment-pool-$($script:ShaC)")
        $anon = Join-Path $tmp 'anon.zip'
        New-TestZip -Path $anon -Entries (Get-SourceEntries -Root 'medical-equipment-pool-main')
        $r = Invoke-Isolated {
            $n = Test-MepSourceZip -ZipPath $named
            $msg = ''
            try { Test-MepSourceZip -ZipPath $anon -ExpectedSha $script:ShaC | Out-Null } catch { $msg = $_.Exception.Message }
            $plain = Test-MepSourceZip -ZipPath $anon
            return [pscustomobject]@{ n = $n; msg = $msg; plain = $plain }
        }
        Assert-Equal $script:ShaC $r.n.Sha 'sha from folder name'
        Assert-True ($r.msg -match 'no embedded commit SHA') 'cannot verify -Version against a ZIP without a SHA'
        Assert-Equal $null $r.plain.Sha 'unverified ZIP has no sha'
        Assert-True (-not $r.plain.Verified) 'not verified'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'non-project, multi-root and corrupt ZIPs are rejected' {
    $tmp = New-TempDir
    try {
        $a = Join-Path $tmp 'a.zip'; New-TestZip -Path $a -Entries @{ 'r/readme.txt' = 'x' }
        $b = Join-Path $tmp 'b.zip'; New-TestZip -Path $b -Entries @{ 'one/x.txt' = 'x'; 'two/y.txt' = 'y' }
        $c = Join-Path $tmp 'c.zip'; Set-Content -LiteralPath $c -Value 'not a zip'
        $e = Invoke-Isolated {
            $m = @()
            foreach ($z in @($a, $b, $c, (Join-Path $tmp 'missing.zip'))) {
                try { Test-MepSourceZip -ZipPath $z | Out-Null; $m += 'accepted' } catch { $m += $_.Exception.Message }
            }
            return $m
        }
        Assert-True ($e[0] -match 'not this project') 'wrong project'
        Assert-True ($e[1] -match 'exactly one top-level') 'two roots'
        Assert-True ($e[2] -match 'not a valid ZIP') 'corrupt'
        Assert-True ($e[3] -match 'not found') 'missing'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'extraction refuses entries that escape the target folder (zip-slip)' {
    $tmp = New-TempDir
    try {
        $z = Join-Path $tmp 'slip.zip'
        New-TestZip -Path $z -Entries @{ '../evil.txt' = 'x' }
        $msg = Invoke-Isolated {
            try { Expand-MepSourceZip -ZipPath $z -Destination (Join-Path $tmp 'out') -Root 'r' | Out-Null } catch { return $_.Exception.Message }
        }
        Assert-True ("$msg" -match 'outside') "refused (got '$msg')"
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $tmp 'evil.txt'))) 'nothing written outside'
    }
    finally { Remove-TempDir $tmp }
}

function New-InstalledTree {
    param([string]$Base)
    $root = Join-Path $Base 'app'
    $dep = Join-Path (Join-Path $root 'deployment') 'local-staging'
    New-Item -ItemType Directory -Path (Join-Path $dep 'backups') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dep 'secrets') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $root '.git') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path (Join-Path (Join-Path $root 'backend') 'alembic') 'versions') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $dep '.env') -Value 'SECRET=keep-me'
    Set-Content -LiteralPath (Join-Path $dep 'backups/b1.dump') -Value 'dump'
    Set-Content -LiteralPath (Join-Path $dep 'secrets/drive-oauth.json') -Value 'tok'
    Set-Content -LiteralPath (Join-Path $dep 'compose.yml') -Value 'old'
    Set-Content -LiteralPath (Join-Path $dep 'old-only.ps1') -Value 'stale'
    Set-Content -LiteralPath (Join-Path $root '.git/HEAD') -Value 'ref'
    Set-Content -LiteralPath (Join-Path $root 'backend/alembic/versions/0000_stale.py') -Value 'stale'
    Set-Content -LiteralPath (Join-Path $root 'backend/alembic/versions/0001_init.py') -Value 'old'
    return $root
}

Test-Case 'ZIP replace swaps the code but preserves .env, backups, secrets; removes stale code' {
    $tmp = New-TempDir
    try {
        $root = New-InstalledTree $tmp
        $zip = Join-Path $tmp 'src.zip'
        New-TestZip -Path $zip -Entries (Get-SourceEntries -Root 'medical-equipment-pool-x') -Comment $script:ShaB
        Invoke-Isolated { Install-MepSourceFromZip -ZipPath $zip -TargetDir $root | Out-Null } | Out-Null
        $dep = Join-Path (Join-Path $root 'deployment') 'local-staging'
        Assert-Equal 'SECRET=keep-me' ((Get-Content -LiteralPath (Join-Path $dep '.env') -Raw).Trim()) '.env preserved'
        Assert-True (Test-Path -LiteralPath (Join-Path $dep 'backups/b1.dump')) 'backup preserved'
        Assert-True (Test-Path -LiteralPath (Join-Path $dep 'secrets/drive-oauth.json')) 'secrets preserved'
        Assert-Equal 'services: {}' ((Get-Content -LiteralPath (Join-Path $dep 'compose.yml') -Raw).Trim()) 'new compose in place'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $dep 'old-only.ps1'))) 'stale script removed'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $root 'backend/alembic/versions/0000_stale.py'))) 'stale migration removed'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $root '.git'))) '.git of the superseded tree removed'
        Assert-Equal 0 @(Get-ChildItem -LiteralPath $tmp -Force -Directory | Where-Object { $_.Name -like '.mep-staging-*' }).Count 'staging folder cleaned up'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'a copy failure mid-replace restores the previous tree and leaves no partial files' {
    $tmp = New-TempDir
    try {
        $root = New-InstalledTree $tmp
        $zip = Join-Path $tmp 'src.zip'
        New-TestZip -Path $zip -Entries (Get-SourceEntries -Root 'medical-equipment-pool-x' -Migrations @('0001_init.py', '0002_new.py')) -Comment $script:ShaB
        $msg = Invoke-Isolated {
            $script:copies = 0
            function Copy-MepUnit {
                param([string]$Source, [string]$Destination)
                $script:copies++
                if ($script:copies -ge 2) { throw 'simulated antivirus lock' }
                Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
            }
            try { Install-MepSourceFromZip -ZipPath $zip -TargetDir $root | Out-Null } catch { return $_.Exception.Message }
        }
        Assert-True ("$msg" -match 'previous version was restored') "restored (got '$msg')"
        $dep = Join-Path (Join-Path $root 'deployment') 'local-staging'
        Assert-Equal 'old' ((Get-Content -LiteralPath (Join-Path $dep 'compose.yml') -Raw).Trim()) 'old compose.yml back'
        Assert-True (Test-Path -LiteralPath (Join-Path $dep 'old-only.ps1')) 'old script back'
        Assert-True (Test-Path -LiteralPath (Join-Path $root 'backend/alembic/versions/0000_stale.py')) 'old migration back'
        Assert-True (Test-Path -LiteralPath (Join-Path $root '.git/HEAD')) '.git back'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $root 'backend/alembic/versions/0002_new.py'))) 'no partial new file'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $root 'README.md'))) 'no partial new top-level file'
        Assert-Equal 'SECRET=keep-me' ((Get-Content -LiteralPath (Join-Path $dep '.env') -Raw).Trim()) '.env untouched'
        Assert-True (Test-Path -LiteralPath (Join-Path $dep 'backups/b1.dump')) 'backup untouched'
        Assert-Equal 0 @(Get-ChildItem -LiteralPath $tmp -Force -Directory | Where-Object { $_.Name -like '.mep-old-*' -or $_.Name -like '.mep-staging-*' }).Count 'no leftover folders'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'Ctrl+C (PipelineStoppedException) mid-replace also restores the previous tree' {
    $tmp = New-TempDir
    try {
        $root = New-InstalledTree $tmp
        $zip = Join-Path $tmp 'src.zip'
        New-TestZip -Path $zip -Entries (Get-SourceEntries -Root 'medical-equipment-pool-x' -Migrations @('0001_init.py', '0002_new.py')) -Comment $script:ShaB
        # PipelineStoppedException unwinds past ordinary catch blocks (including
        # this harness's), so the replace runs in its own runspace.
        $code = @'
param($lib, $zip, $root)
Set-StrictMode -Version Latest
. $lib
$script:copies = 0
function Copy-MepUnit {
    param([string]$Source, [string]$Destination)
    $script:copies++
    if ($script:copies -ge 2) { throw [System.Management.Automation.PipelineStoppedException]::new() }
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}
Install-MepSourceFromZip -ZipPath $zip -TargetDir $root | Out-Null
'@
        $ps = [powershell]::Create()
        try {
            [void]$ps.AddScript($code).AddArgument($script:LibPath).AddArgument($zip).AddArgument($root)
            try { [void]$ps.Invoke() } catch { }
            Assert-True ($ps.HadErrors -or $ps.InvocationStateInfo.State -ne 'Completed') 'the injected stop actually interrupted the replace'
        }
        finally { $ps.Dispose() }
        $dep = Join-Path (Join-Path $root 'deployment') 'local-staging'
        Assert-Equal 'old' ((Get-Content -LiteralPath (Join-Path $dep 'compose.yml') -Raw).Trim()) 'old compose.yml back'
        Assert-True (Test-Path -LiteralPath (Join-Path $dep 'old-only.ps1')) 'old script back'
        Assert-True (Test-Path -LiteralPath (Join-Path $root 'backend/alembic/versions/0000_stale.py')) 'old migration back'
        Assert-True (Test-Path -LiteralPath (Join-Path $root '.git/HEAD')) '.git back'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $root 'backend/alembic/versions/0002_new.py'))) 'no partial new file'
        Assert-Equal 'SECRET=keep-me' ((Get-Content -LiteralPath (Join-Path $dep '.env') -Raw).Trim()) '.env untouched'
        Assert-Equal 0 @(Get-ChildItem -LiteralPath $tmp -Force -Directory | Where-Object { $_.Name -like '.mep-old-*' }).Count 'no leftover .mep-old folder'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'insufficient free space refuses before anything is moved' {
    $tmp = New-TempDir
    try {
        $root = New-InstalledTree $tmp
        $zip = Join-Path $tmp 'src.zip'
        New-TestZip -Path $zip -Entries (Get-SourceEntries -Root 'medical-equipment-pool-x') -Comment $script:ShaB
        $msg = Invoke-Isolated {
            function Get-MepFreeBytes { param([string]$Path) 1MB }
            try { Install-MepSourceFromZip -ZipPath $zip -TargetDir $root | Out-Null } catch { return $_.Exception.Message }
        }
        Assert-True ("$msg" -match 'Not enough free disk space') "refused (got '$msg')"
        Assert-True (Test-Path -LiteralPath (Join-Path $root 'backend/alembic/versions/0000_stale.py')) 'tree untouched'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'ZIP replace refuses a non-empty folder that is not this project and deletes nothing' {
    $tmp = New-TempDir
    try {
        $root = Join-Path $tmp 'app'
        New-Item -ItemType Directory -Path $root -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $root 'precious.txt') -Value 'mine'
        $zip = Join-Path $tmp 'src.zip'
        New-TestZip -Path $zip -Entries (Get-SourceEntries -Root 'medical-equipment-pool-x')
        $msg = Invoke-Isolated { try { Install-MepSourceFromZip -ZipPath $zip -TargetDir $root | Out-Null } catch { return $_.Exception.Message } }
        Assert-True ("$msg" -match 'not a Medical Equipment Pool install folder') "refused (got '$msg')"
        Assert-True (Test-Path -LiteralPath (Join-Path $root 'precious.txt')) 'file untouched'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'offline update: verified ZIP replaces code, then update.ps1 runs, then ZIP version recorded' {
    $tmp = New-TempDir
    try {
        $root = New-InstalledTree $tmp
        $zip = Join-Path $tmp 'src.zip'
        New-TestZip -Path $zip -Entries (Get-SourceEntries -Root 'medical-equipment-pool-x' -Migrations @('0000_stale.py', '0001_init.py', '0002_new.py')) -Comment $script:ShaC
        $r = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx -Overrides @{ Head = $script:ShaA }
            # Tree has a .git folder, so the git mock answers status/rev-parse.
            $run = { $ctx.Calls += 'RUN-UPDATE'; $ctx.NewCompose = (Get-Content -LiteralPath (Join-Path (Get-MepDeploymentDir $root) 'compose.yml') -Raw).Trim(); 0 }
            $res = Invoke-MepOnlineUpdate -Root $root -SourceZip $zip -Version $script:ShaC.Substring(0, 12) -Yes -RunUpdate $run
            return [pscustomobject]@{ ctx = $ctx; res = $res; hist = (Get-MepVersionHistory -Path (Get-MepVersionHistoryPath -Root $root)) }
        }
        Assert-Equal 'Updated' $r.res.Outcome 'updated'
        Assert-Equal 'services: {}' $r.ctx.NewCompose 'update.ps1 ran after the code was replaced'
        Assert-Equal $script:ShaC $r.hist.current.sha 'zip sha recorded'
        Assert-Equal 'zip' $r.hist.current.source 'source recorded as zip'
        Assert-Equal $script:ShaA $r.hist.previous.sha 'previous = the git HEAD before the swap'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'offline update with a dirty git tree is refused before the ZIP is applied' {
    $tmp = New-TempDir
    try {
        $root = New-InstalledTree $tmp
        $zip = Join-Path $tmp 'src.zip'
        New-TestZip -Path $zip -Entries (Get-SourceEntries -Root 'medical-equipment-pool-x') -Comment $script:ShaC
        $ctx = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx -Overrides @{ Dirty = $true }
            try { Invoke-MepOnlineUpdate -Root $root -SourceZip $zip -Yes -RunUpdate { 0 } | Out-Null } catch { $ctx.Err = $_.Exception.Message }
            return $ctx
        }
        Assert-True ("$($ctx.Err)" -match 'local changes') 'refused'
        Assert-True (Test-Path -LiteralPath (Join-Path $root 'backend/alembic/versions/0000_stale.py')) 'installed code untouched'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'offline update with an older ZIP (fewer migrations) is refused and changes nothing' {
    $tmp = New-TempDir
    try {
        $root = New-InstalledTree $tmp
        $zip = Join-Path $tmp 'old.zip'
        New-TestZip -Path $zip -Entries (Get-SourceEntries -Root 'medical-equipment-pool-x' -Migrations @('0001_init.py')) -Comment $script:ShaC
        $r = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx
            $run = { $ctx.Calls += 'RUN-UPDATE'; 0 }
            try { Invoke-MepOnlineUpdate -Root $root -SourceZip $zip -Yes -RunUpdate $run | Out-Null } catch { $ctx.Err = $_.Exception.Message }
            return $ctx
        }
        Assert-True ("$($r.Err)" -match 'older code over a newer database') "refused (got '$($r.Err)')"
        Assert-True ($r.Calls -notcontains 'RUN-UPDATE') 'update.ps1 not run'
        Assert-True (Test-Path -LiteralPath (Join-Path $root 'backend/alembic/versions/0000_stale.py')) 'installed code untouched'
    }
    finally { Remove-TempDir $tmp }
}

# ===========================================================================
Write-Host ''
Write-Host 'Preflight and prerequisites' -ForegroundColor Cyan

Test-Case 'preflight facts: Windows 11, admin, pwsh 7, RAM and disk are each enforced' {
    Invoke-Isolated {
        function New-Facts($o = @{}) {
            $f = @{ IsWindows = $true; OsBuild = 22631; IsAdmin = $true; PwshMajor = 7; RamBytes = 8GB; FreeDiskBytes = 100GB }
            foreach ($k in $o.Keys) { $f[$k] = $o[$k] }
            [pscustomobject]$f
        }
        Assert-Equal 0 (Test-MepPreflightFacts (New-Facts)).Errors.Count 'good host passes'
        Assert-Equal 0 (Test-MepPreflightFacts (New-Facts @{ RamBytes = 7.8GB })).Errors.Count 'an 8 GB PC reporting 7.8 GB passes'
        Assert-True (@((Test-MepPreflightFacts (New-Facts @{ OsBuild = 19045 })).Errors -match 'Windows 11').Count -gt 0) 'Windows 10 refused'
        Assert-True (@((Test-MepPreflightFacts (New-Facts @{ IsAdmin = $false })).Errors -match 'Administrator').Count -gt 0) 'non-admin refused'
        Assert-True (@((Test-MepPreflightFacts (New-Facts @{ PwshMajor = 5 })).Errors -match 'PowerShell 7').Count -gt 0) 'pwsh 5 refused'
        Assert-True (@((Test-MepPreflightFacts (New-Facts @{ RamBytes = 4GB })).Errors -match 'RAM').Count -gt 0) 'low RAM refused'
        Assert-True (@((Test-MepPreflightFacts (New-Facts @{ FreeDiskBytes = 5GB })).Errors -match 'disk').Count -gt 0) 'low disk refused'
        Assert-True (@((Test-MepPreflightFacts (New-Facts @{ IsWindows = $false })).Errors -match 'Windows 11').Count -gt 0) 'non-Windows refused'
    } | Out-Null
}

Test-Case 'Docker missing: declined -> error; accepted -> winget install, WSL, halt for reboot' {
    $r = Invoke-Isolated {
        . $script:GitMockBlock
        $ctx = New-Ctx
        $ctx.Winget = @()
        function Test-MepCommandExists { param([string]$Name) $false }
        function Get-MepDockerDesktopPath { $null }
        function Install-MepWithWinget { param([string]$Id) $ctx.Winget += $Id }
        $ctx.Confirm = $false
        $declined = ''
        try { Invoke-MepEnsureDocker | Out-Null } catch { $declined = $_.Exception.Message }
        $wingetAfterDecline = @($ctx.Winget).Count
        $ctx.Confirm = $true
        $result = Invoke-MepEnsureDocker
        return [pscustomobject]@{ declined = $declined; n = $wingetAfterDecline; result = $result; winget = $ctx.Winget; calls = $ctx.Calls }
    }
    Assert-True ($r.declined -match 'required') 'decline stops with a message'
    Assert-Equal 0 $r.n 'nothing installed without confirmation'
    Assert-Equal 'halt' ($r.result | Select-Object -Last 1) 'tells the operator to reboot and re-run'
    Assert-Equal 'Docker.DockerDesktop' $r.winget[0] 'winget id'
    Assert-True (@($r.calls | Where-Object { $_ -like 'wsl --install*' }).Count -eq 1) 'WSL2 enabled'
}

Test-Case 'Docker engine already running: no install, no prompt' {
    $r = Invoke-Isolated {
        . $script:GitMockBlock
        $ctx = New-Ctx
        $ctx.Winget = @()
        function Test-MepCommandExists { param([string]$Name) $true }
        function Test-MepDockerEngineUp { $true }
        function Install-MepWithWinget { param([string]$Id) $ctx.Winget += $Id }
        $res = Invoke-MepEnsureDocker
        return [pscustomobject]@{ res = $res; winget = @($ctx.Winget).Count; prompts = @($ctx.Prompts).Count }
    }
    Assert-Equal 'done' $r.res 'done'
    Assert-Equal 0 $r.winget 'no winget'
    Assert-Equal 0 $r.prompts 'no prompt'
}

Test-Case 'Git missing: installs via winget Git.Git after confirmation, then asks for a new terminal' {
    $r = Invoke-Isolated {
        . $script:GitMockBlock
        $ctx = New-Ctx
        $ctx.Winget = @()
        function Test-MepCommandExists { param([string]$Name) $false }
        function Install-MepWithWinget { param([string]$Id) $ctx.Winget += $Id }
        $res = Invoke-MepEnsureGit
        return [pscustomobject]@{ res = $res; winget = $ctx.Winget }
    }
    Assert-Equal 'halt' ($r.res | Select-Object -Last 1) 'halt'
    Assert-Equal 'Git.Git' $r.winget[0] 'winget id'
}

Test-Case 'clone refuses a non-empty folder that is not a git clone' {
    $tmp = New-TempDir
    try {
        $dir = Join-Path $tmp 'app'
        New-Item -ItemType Directory -Path $dir | Out-Null
        Set-Content -LiteralPath (Join-Path $dir 'x.txt') -Value 'x'
        $ctx = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx
            try { Initialize-MepSourceClone -InstallDir $dir } catch { $ctx.Err = $_.Exception.Message }
            return $ctx
        }
        Assert-True ("$($ctx.Err)" -match 'not a git clone') 'refused'
        Assert-True (-not ($ctx.Calls -match '^git clone')) 'no clone'
        Assert-True (Test-Path -LiteralPath (Join-Path $dir 'x.txt')) 'untouched'
    }
    finally { Remove-TempDir $tmp }
}

Test-Case 'clone of a missing folder uses the public URL with autocrlf off' {
    $tmp = New-TempDir
    try {
        $dir = Join-Path $tmp 'app'
        $ctx = Invoke-Isolated {
            . $script:GitMockBlock
            $ctx = New-Ctx
            Initialize-MepSourceClone -InstallDir $dir
            return $ctx
        }
        $clone = @($ctx.Calls | Where-Object { $_ -like 'git clone*' })
        Assert-Equal 1 $clone.Count 'one clone'
        Assert-True ($clone[0] -match 'https://github.com/manmenex/medical-equipment-pool.git') 'public URL'
        Assert-True ($clone[0] -match 'core.autocrlf=false') 'LF line endings preserved for Linux containers'
        Assert-True ($clone[0] -notmatch '(?i)token|@github|password') 'no credentials in the URL'
    }
    finally { Remove-TempDir $tmp }
}

# ===========================================================================
Write-Host ''
Write-Host 'Static guardrails' -ForegroundColor Cyan

function Get-ScriptAst {
    param([string]$Path)
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw "Parse errors in ${Path}: $($errors -join '; ')" }
    return $ast
}

Test-Case 'setup-ces-bcm.ps1 uses no PowerShell-7-only syntax and checks the version before loading anything' {
    $path = Join-Path $script:DeploymentRoot 'setup-ces-bcm.ps1'
    $ast = Get-ScriptAst $path
    $seven = $ast.FindAll({
            param($n)
            ($n -is [System.Management.Automation.Language.TernaryExpressionAst]) -or
            ($n -is [System.Management.Automation.Language.PipelineChainAst]) -or
            (($n -is [System.Management.Automation.Language.BinaryExpressionAst]) -and ($n.Operator -in @('QuestionQuestion', 'QuestionQuestionEquals'))) -or
            (($n -is [System.Management.Automation.Language.MemberExpressionAst]) -and $n.NullConditional)
        }, $true)
    Assert-Equal 0 @($seven).Count 'no ternary / pipeline-chain / null-conditional syntax (would break the 5.1 guard message)'
    $text = Get-Content -LiteralPath $path -Raw
    $guard = $text.IndexOf('$PSVersionTable.PSVersion.Major -lt 7')
    $load = $text.IndexOf('. $libPath')
    Assert-True ($guard -ge 0 -and $guard -lt $load) 'version guard precedes the dot-source'
    Assert-True ($text -match 'winget install -e --id Microsoft\.PowerShell') 'prints the exact pwsh 7 install command'
    Assert-True ($text -notmatch '(?m)^\s*#Requires\s+-Version\s+7') '#Requires would hide the friendly message from 5.1'
}

Test-Case 'host scripts never delete volumes/data, never use Invoke-Expression, never handle passwords' {
    foreach ($rel in @('setup-ces-bcm.ps1', 'update-online.ps1', 'lib/HostSetup.ps1')) {
        $code = Get-Content -LiteralPath (Join-Path $script:DeploymentRoot $rel) -Raw
        $code = [regex]::Replace($code, '(?s)<#.*?#>', '')
        $code = [regex]::Replace($code, '(?m)^\s*#.*$', '')
        foreach ($pattern in @('Invoke-Expression', '\biex\b', '(?i)down\s+-v', '(?i)volume\s+(rm|prune)', '(?i)system\s+prune', '(?i)-AsSecureString', '(?i)ConvertTo-SecureString', '(?i)Get-Credential', '(?i)Authorization', '(?i)\bghp_', '(?i)git\s+pull')) {
            Assert-True ($code -notmatch $pattern) "$rel must not contain '$pattern'"
        }
    }
}

Test-Case 'Remove-Item appears only in the ZIP code-replace functions' {
    $ast = Get-ScriptAst $script:LibPath
    $allowed = @('Install-MepSourceTree', 'Install-MepSourceFromZip', 'Invoke-MepZipUpdate')
    $calls = $ast.FindAll({ param($n) ($n -is [System.Management.Automation.Language.CommandAst]) -and ($n.GetCommandName() -eq 'Remove-Item') }, $true)
    Assert-True (@($calls).Count -gt 0) 'expected the replace code to use Remove-Item'
    foreach ($c in $calls) {
        $p = $c.Parent
        while ($p -and -not ($p -is [System.Management.Automation.Language.FunctionDefinitionAst])) { $p = $p.Parent }
        Assert-True ($p -and ($p.Name -in $allowed)) "Remove-Item found outside the allowed functions (in '$(if ($p) { $p.Name } else { 'script scope' })')"
    }
}

Test-Case 'update-online.ps1 always delegates to update.ps1 (no direct docker or compose call)' {
    $code = Get-Content -LiteralPath (Join-Path $script:DeploymentRoot 'update-online.ps1') -Raw
    Assert-True ($code -match 'Join-Path \$PSScriptRoot ''update\.ps1''') 'runs update.ps1 from the same folder'
    Assert-True ($code -notmatch "(?i)'docker'|compose") 'no direct docker use'
    $lib = Get-Content -LiteralPath $script:LibPath -Raw
    Assert-True ($lib -match "Production deployment is the Owner's decision") 'Owner-decision notice present'
}

# ===========================================================================

Write-Host ''
Write-Host "Passed: $script:Passed   Failed: $script:Failed" -ForegroundColor $(if ($script:Failed -eq 0) { 'Green' } else { 'Red' })
if ($script:Failed -gt 0) {
    Write-Host ''
    Write-Host 'Failures:' -ForegroundColor Red
    $script:Failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
exit 0
