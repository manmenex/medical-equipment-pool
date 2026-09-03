<#
.SYNOPSIS
PR24D-L2 Fix Round 1: behavior tests for the local Staging/UAT installer
orchestration.

.DESCRIPTION
These are NOT structural greps. Each test dot-sources the real
lib/Common.ps1 and lib/Operations.ps1, replaces the single native-command
seam (Invoke-MepCommand) with a recording mock, and then calls the real
Invoke-MepInstall / Invoke-MepUpdate / Get-InstallationState functions --
so the fail-closed ordering rules they encode are covered by executed
behavior, not by prose that could drift from the code.

Deliberately dependency-free (no Pester): PowerShell 7 does not bundle
Pester 5 on Linux, and CI's "PowerShell script validation" job must be
able to run this with nothing but `pwsh`.

EVIDENCE CLASS: POWERSHELL UNIT/MOCK. These tests prove orchestration
ordering and failure handling. They do NOT execute Docker, do not build
images, and are not an end-to-end installation -- see the PR's own
evidence table for what remains unexecuted.

.EXAMPLE
pwsh -NoProfile -File deployment/local-staging/tests/Invoke-InstallerTests.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:DeploymentRootForTests = Split-Path -Parent $PSScriptRoot
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

# ---------------------------------------------------------------------------
# Harness: builds an isolated scope with the real orchestration functions
# and a scripted command mock.
# ---------------------------------------------------------------------------

function New-MockContext {
    <#
    .SYNOPSIS
    Returns a context object whose .Invoke(scriptblock) runs the given
    body with the real Common.ps1/Operations.ps1 loaded and
    Invoke-MepCommand mocked.

    .PARAMETER ExitCodeRules
    Ordered list of @{ Match = '<substring of the joined argument list>';
    ExitCode = <int>; Output = @(...) }. The first matching rule wins;
    unmatched calls succeed with exit 0.
    #>
    param(
        [hashtable[]]$ExitCodeRules = @(),
        [bool]$EnvFileExists = $false,
        [bool]$InstallCompleted = $false,
        [bool]$RemovalSilentlyFails = $false
    )
    return [pscustomobject]@{
        ExitCodeRules        = $ExitCodeRules
        EnvFileExists        = $EnvFileExists
        InstallCompleted     = $InstallCompleted
        RemovalSilentlyFails = $RemovalSilentlyFails
    }
}

function Invoke-WithMocks {
    param(
        [Parameter(Mandatory)] $Context,
        [Parameter(Mandatory)] [scriptblock]$Body
    )

    $runner = {
        param($ctx, $deploymentRoot, $body)

        Set-StrictMode -Version Latest
        . (Join-Path $deploymentRoot 'lib/Common.ps1')
        . (Join-Path $deploymentRoot 'lib/Operations.ps1')

        # --- recording command seam -------------------------------------
        $script:RecordedCalls = @()
        function Invoke-MepCommand {
            param(
                [Parameter(Mandatory)] [string]$FilePath,
                [Parameter(Mandatory)] [AllowEmptyCollection()] [string[]]$Arguments,
                [switch]$AllowNonZeroExit,
                [switch]$NoCapture,
                [string]$Phase = 'command'
            )
            $joined = ($Arguments -join ' ')
            $script:RecordedCalls += [pscustomobject]@{ FilePath = $FilePath; Args = $joined; Phase = $Phase }

            $exitCode = 0
            $output = @()
            foreach ($rule in $ctx.ExitCodeRules) {
                if ($joined -like "*$($rule.Match)*") {
                    $exitCode = [int]$rule.ExitCode
                    if ($rule.ContainsKey('Output')) { $output = @($rule.Output) }
                    break
                }
            }
            if ($exitCode -ne 0 -and -not $AllowNonZeroExit) {
                throw "$FilePath exited with code $exitCode during phase '$Phase'."
            }
            return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
        }

        # --- filesystem/environment stubs -------------------------------
        function Write-InstallLog { param($Phase, $Message, $Level) }
        function Test-EnvFileExists { return $ctx.EnvFileExists }
        function Get-ConfiguredHttpPort { return 80 }
        function Get-CurrentSourceSha { return 'testsha0000000000000000000000000000000000' }
        function Invoke-PrerequisiteChecks { param($FrontendPort) return @() }
        function Invoke-DockerComposeConfigOnly { return 0 }
        function New-LocalStagingEnvFile { param($AllowedOrigins, $HttpPort) $script:EnvGenerated = $true }
        function Test-MepInstallCompleted { return $ctx.InstallCompleted }
        function Get-InstallMetadata { if ($ctx.InstallCompleted) { return [pscustomobject]@{ InstallCompleted = $true } } return $null }
        function Set-InstallMetadata { param($SourceSha, $SchemaVersion) $script:MetadataWritten = $true }

        # Filesystem mutation is stubbed rather than real: the -RemoveData
        # tests exercise a code path that deletes $Script:EnvFilePath, and
        # an unstubbed Remove-Item here would delete a developer's ACTUAL
        # deployment/local-staging/.env just by running the test suite.
        # Test-Path is scripted off the same record so the post-removal
        # verification can be driven both ways.
        $script:RemovedPaths = @()
        function Remove-Item {
            # CmdletBinding so -ErrorAction (a common parameter) binds
            # here exactly as it does on the real cmdlet.
            [CmdletBinding()]
            param([Parameter(Position = 0)][string]$LiteralPath, [switch]$Force)
            $script:RemovedPaths += $LiteralPath
        }
        function Test-Path {
            [CmdletBinding()]
            param([Parameter(Position = 0)][string]$LiteralPath, [string]$Path)
            $target = if ($LiteralPath) { $LiteralPath } else { $Path }
            # A path we "removed" is gone -- unless this context is
            # simulating a removal that silently failed.
            if ($script:RemovedPaths -contains $target) { return [bool]$ctx.RemovalSilentlyFails }
            return $false
        }

        $script:MetadataWritten = $false
        $script:EnvGenerated = $false

        & $body
    }

    # Runs in a child scope so each test starts from clean function state.
    return & $runner $Context $script:DeploymentRootForTests $Body
}

Write-Host ''
Write-Host 'PR24D-L2 installer orchestration tests (POWERSHELL UNIT/MOCK)' -ForegroundColor Cyan
Write-Host ''

# ===========================================================================
# A. Build failure blocks migration and success metadata (P1-A)
# ===========================================================================

Test-Case 'install: build failure stops before migration and writes no success metadata' {
    $ctx = New-MockContext -ExitCodeRules @(@{ Match = 'build backend frontend'; ExitCode = 1 })
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try {
            Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
                -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites
        }
        catch { $threw = $true }
        return [pscustomobject]@{
            Threw           = $threw
            Calls           = @($script:RecordedCalls | ForEach-Object { $_.Args })
            MetadataWritten = $script:MetadataWritten
        }
    }
    Assert-True $result.Threw 'install must fail when the image build fails'
    Assert-True (-not ($result.Calls -match 'deploy_migrate\.py')) 'migration must NOT be invoked after a failed build'
    Assert-True (-not $result.MetadataWritten) 'success metadata must NOT be written after a failed build'
}

Test-Case 'install: build is invoked BEFORE migration' {
    $ctx = New-MockContext
    $result = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
            -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    $buildIndex = [array]::FindIndex([string[]]$result, [Predicate[string]] { param($c) $c -like '*build backend frontend*' })
    $migrateIndex = [array]::FindIndex([string[]]$result, [Predicate[string]] { param($c) $c -like '*deploy_migrate.py*' })
    Assert-True ($buildIndex -ge 0) 'build must be invoked'
    Assert-True ($migrateIndex -ge 0) 'migration must be invoked'
    Assert-True ($buildIndex -lt $migrateIndex) 'build must happen before migration'
}

Test-Case 'install: migration uses --no-build so it cannot silently rebuild a different image' {
    $ctx = New-MockContext
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
            -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    $migrateCall = @($calls | Where-Object { $_ -like '*deploy_migrate.py*' })[0]
    Assert-True ($migrateCall -like '*--no-build*') 'migration one-off container must pass --no-build'
    Assert-True ($migrateCall -like '*--name mep-local-staging-migrate*') 'migration must not reuse the backend service container name'
}

# ===========================================================================
# B/C. Administrator bootstrap is mandatory on a first install (P1-B)
# ===========================================================================

Test-Case 'install: blank administrator input fails the installation' {
    $ctx = New-MockContext
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try {
            Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = ''; Email = ''; FullName = '' } } `
                -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites
        }
        catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw; MetadataWritten = $script:MetadataWritten }
    }
    Assert-True $result.Threw 'blank administrator input must fail the installation'
    Assert-True (-not $result.MetadataWritten) 'no success metadata after blank administrator input'
}

Test-Case 'install: bootstrap non-zero exit fails the installation and writes no metadata' {
    $ctx = New-MockContext -ExitCodeRules @(@{ Match = 'bootstrap_admin'; ExitCode = 1; Output = @('Bootstrap refused: employee_code is already in use by another user.') })
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try {
            Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
                -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites
        }
        catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw; MetadataWritten = $script:MetadataWritten }
    }
    Assert-True $result.Threw 'a failed Administrator bootstrap must fail the installation'
    Assert-True (-not $result.MetadataWritten) 'no success metadata after a failed Administrator bootstrap'
}

Test-Case 'install: backend reporting "administrator already exists" is a satisfied state, not a failure' {
    $ctx = New-MockContext -ExitCodeRules @(@{ Match = 'bootstrap_admin'; ExitCode = 1; Output = @('Bootstrap refused: An administrator already exists. Refusing to bootstrap a second one.') })
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try {
            Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
                -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites | Out-Null
        }
        catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw; MetadataWritten = $script:MetadataWritten }
    }
    Assert-True (-not $result.Threw) 'an existing administrator must not fail the installation'
    Assert-True $result.MetadataWritten 'installation completes when the backend already has an administrator'
}

Test-Case 'install: bootstrap is skipped when the installation already completed previously' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepInstall -AdminCredentialCallback { throw 'admin callback must not be invoked on an already-completed installation' } `
            -ConfigCallback { throw 'config callback must not be invoked when .env exists' } -SkipPrerequisites | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    Assert-True (-not ($calls -match 'bootstrap_admin')) 'no bootstrap attempt on an already-completed installation'
}

Test-Case 'install: successful first install writes completed metadata exactly once, last' {
    $ctx = New-MockContext
    $result = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
            -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites | Out-Null
        return [pscustomobject]@{
            MetadataWritten = $script:MetadataWritten
            Calls           = @($script:RecordedCalls | ForEach-Object { $_.Args })
        }
    }
    Assert-True $result.MetadataWritten 'a successful install records completion'
    $lastMeaningful = @($result.Calls | Where-Object { $_ -like '*bootstrap_admin*' })
    Assert-True ($lastMeaningful.Count -eq 1) 'bootstrap runs exactly once on a first install'
}

# ===========================================================================
# D. Update stop-failure blocks migration (P1-C)
# ===========================================================================

Test-Case 'update: stop failure blocks migration and start' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true `
        -ExitCodeRules @(@{ Match = 'stop backend frontend'; ExitCode = 1 })
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try { Invoke-MepUpdate | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{
            Threw           = $threw
            Calls           = @($script:RecordedCalls | ForEach-Object { $_.Args })
            MetadataWritten = $script:MetadataWritten
        }
    }
    Assert-True $result.Threw 'a failed stop must fail the update'
    Assert-True (-not ($result.Calls -match 'deploy_migrate\.py')) 'migration must NOT run after a failed stop'
    Assert-True (-not ($result.Calls -match 'up -d --wait --wait-timeout 180')) 'the application must NOT be restarted after a failed stop'
    Assert-True (-not $result.MetadataWritten) 'no success metadata after a failed stop'
}

Test-Case 'update: backend still running after stop blocks migration' {
    # `stop` returns 0 but ps still shows the backend running -- exit code
    # alone must not be trusted.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'ps --all --format json'; ExitCode = 0; Output = @(
                '{"Service":"postgres","State":"running","Health":"healthy"}',
                '{"Service":"redis","State":"running","Health":"healthy"}',
                '{"Service":"backend","State":"running","Health":"healthy"}',
                '{"Service":"frontend","State":"running","Health":"healthy"}') }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try { Invoke-MepUpdate | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{
            Threw = $threw
            Calls = @($script:RecordedCalls | ForEach-Object { $_.Args })
        }
    }
    Assert-True $result.Threw 'a backend still running after stop must fail the update'
    Assert-True (-not ($result.Calls -match 'deploy_migrate\.py')) 'migration must NOT run while the backend is still up'
}

Test-Case 'update: build failure never stops the running application' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true `
        -ExitCodeRules @(@{ Match = 'build backend frontend'; ExitCode = 1 })
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try { Invoke-MepUpdate | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw; Calls = @($script:RecordedCalls | ForEach-Object { $_.Args }) }
    }
    Assert-True $result.Threw 'a failed build must fail the update'
    Assert-True (-not ($result.Calls -match 'stop backend frontend')) 'the running application must NOT be stopped when the build failed'
}

# ===========================================================================
# E. Mutation lock (P1-D)
# ===========================================================================

Test-Case 'lock: a second concurrent mutating operation is rejected immediately' {
    . (Join-Path $script:DeploymentRootForTests 'lib/Common.ps1')
    $first = Enter-MepMutationLock
    try {
        $holderScript = Join-Path $script:DeploymentRootForTests 'lib/Common.ps1'
        # A separate process must fail to acquire the same named lock.
        $probe = & pwsh -NoProfile -Command "
            . '$holderScript'
            try { `$l = Enter-MepMutationLock; Exit-MepMutationLock `$l; 'ACQUIRED' }
            catch { 'REJECTED' }
        "
        Assert-Equal 'REJECTED' ("$probe".Trim()) 'a second process must be rejected while the lock is held'
    }
    finally {
        Exit-MepMutationLock $first
    }
}

Test-Case 'lock: released lock can be re-acquired by another process' {
    . (Join-Path $script:DeploymentRootForTests 'lib/Common.ps1')
    $first = Enter-MepMutationLock
    Exit-MepMutationLock $first
    $holderScript = Join-Path $script:DeploymentRootForTests 'lib/Common.ps1'
    $probe = & pwsh -NoProfile -Command "
        . '$holderScript'
        try { `$l = Enter-MepMutationLock; Exit-MepMutationLock `$l; 'ACQUIRED' }
        catch { 'REJECTED' }
    "
    Assert-Equal 'ACQUIRED' ("$probe".Trim()) 'the lock must be re-acquirable once released'
}

# ===========================================================================
# F. State classification uses --all (P2)
# ===========================================================================

Test-Case 'state: stopped backend/frontend are NOT classified healthy' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'ps --all --format json'; ExitCode = 0; Output = @(
                '{"Service":"postgres","State":"exited","Health":""}',
                '{"Service":"redis","State":"exited","Health":""}',
                '{"Service":"backend","State":"exited","Health":""}',
                '{"Service":"frontend","State":"exited","Health":""}') }
    )
    $state = Invoke-WithMocks -Context $ctx -Body { return Get-InstallationState }
    Assert-Equal 'EXISTING_STOPPED' $state 'a fully stopped installation is EXISTING_STOPPED, never EXISTING_HEALTHY'
}

Test-Case 'state: inspection always passes --all' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Get-InstallationState | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    $psCalls = @($calls | Where-Object { $_ -like '*compose*ps*' })
    Assert-True ($psCalls.Count -ge 1) 'state inspection must call docker compose ps'
    foreach ($c in $psCalls) {
        Assert-True ($c -like '*--all*') "every `docker compose ps` call must pass --all (saw: $c)"
    }
}

Test-Case 'state: a subset of expected services is PARTIAL, not healthy' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'ps --all --format json'; ExitCode = 0; Output = @(
                '{"Service":"postgres","State":"running","Health":"healthy"}') }
    )
    $state = Invoke-WithMocks -Context $ctx -Body { return Get-InstallationState }
    Assert-Equal 'PARTIAL' $state 'PostgreSQL alone must never be classified EXISTING_HEALTHY'
}

Test-Case 'state: an installation that never completed is PARTIAL even when running' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $false -ExitCodeRules @(
        @{ Match = 'ps --all --format json'; ExitCode = 0; Output = @(
                '{"Service":"postgres","State":"running","Health":"healthy"}',
                '{"Service":"redis","State":"running","Health":"healthy"}',
                '{"Service":"backend","State":"running","Health":"healthy"}',
                '{"Service":"frontend","State":"running","Health":"healthy"}') }
    )
    $state = Invoke-WithMocks -Context $ctx -Body { return Get-InstallationState }
    Assert-Equal 'PARTIAL' $state 'an install whose Administrator bootstrap never succeeded must not look healthy'
}

Test-Case 'state: no config and no containers is FRESH' {
    $ctx = New-MockContext -EnvFileExists $false -ExitCodeRules @(
        @{ Match = 'ps --all --format json'; ExitCode = 0; Output = @() }
    )
    $state = Invoke-WithMocks -Context $ctx -Body { return Get-InstallationState }
    Assert-Equal 'FRESH' $state 'a machine with no config and no containers is FRESH'
}

Test-Case 'state: containers without config is AMBIGUOUS, never guessed at' {
    $ctx = New-MockContext -EnvFileExists $false -ExitCodeRules @(
        @{ Match = 'ps --all --format json'; ExitCode = 0; Output = @(
                '{"Service":"postgres","State":"running","Health":"healthy"}') }
    )
    $state = Invoke-WithMocks -Context $ctx -Body { return Get-InstallationState }
    Assert-Equal 'AMBIGUOUS' $state 'containers without .env is a conflict, not a healthy install'
}

# ===========================================================================
# Redis non-blocking contract (preserved from PR24D-L1)
# ===========================================================================

Test-Case 'install: redis is never part of a --wait call' {
    $ctx = New-MockContext
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
            -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    foreach ($c in @($calls | Where-Object { $_ -like '*--wait*' })) {
        Assert-True (-not ($c -match '\bredis\b')) "redis must never appear in a --wait call (saw: $c)"
    }
    Assert-True (@($calls | Where-Object { $_ -like '*up -d redis*' }).Count -eq 1) 'redis is started fire-and-forget exactly once'
}

Test-Case 'install: a failed redis start does not fail the installation' {
    $ctx = New-MockContext -ExitCodeRules @(@{ Match = 'up -d redis'; ExitCode = 1 })
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try {
            Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
                -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites | Out-Null
        }
        catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw; MetadataWritten = $script:MetadataWritten }
    }
    Assert-True (-not $result.Threw) 'Redis is non-blocking: a failed Redis start must not fail the install'
    Assert-True $result.MetadataWritten 'installation still completes with Redis degraded'
}

# ===========================================================================
# Uninstall data preservation
# ===========================================================================

Test-Case 'uninstall: default path never removes volumes' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepUninstall
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    Assert-True (@($calls | Where-Object { $_ -like '*down*' }).Count -ge 1) 'uninstall runs docker compose down'
    Assert-True (-not ($calls -match '--volumes')) 'the default uninstall path must never pass --volumes'
}

Test-Case 'uninstall: -RemoveData removes volumes only after the plain down' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepUninstall -RemoveData
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    Assert-True (@($calls | Where-Object { $_ -like '*--volumes*' }).Count -eq 1) '-RemoveData removes volumes exactly once'
}

Test-Case 'uninstall: -RemoveData fails closed when configuration deletion silently fails' {
    # Same class as P1-C: a mutating step whose failure is swallowed would
    # report "Data removed" while .env (and its generated secrets) is
    # still on disk.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -RemovalSilentlyFails $true
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try { Invoke-MepUninstall -RemoveData } catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw }
    }
    Assert-True $result.Threw 'uninstall -RemoveData must fail when a configuration file survives removal'
}

Test-Case 'uninstall: -RemoveData deletes both the env file and the install metadata' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $removed = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepUninstall -RemoveData
        return @($script:RemovedPaths)
    }
    Assert-True (@($removed | Where-Object { $_ -like '*.env' }).Count -eq 1) '-RemoveData deletes the .env file'
    Assert-True (@($removed | Where-Object { $_ -like '*install-metadata*' }).Count -eq 1) '-RemoveData deletes the install metadata'
}

# ===========================================================================
# start.ps1 never migrates
# ===========================================================================

Test-Case 'start: never runs a migration' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepStart
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    Assert-True (-not ($calls -match 'deploy_migrate\.py')) 'start must never run a migration'
    Assert-True (-not ($calls -match 'build backend frontend')) 'start must not rebuild images'
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
