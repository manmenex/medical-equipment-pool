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
        [bool]$RemovalSilentlyFails = $false,
        [bool]$StopIsIneffective = $false
    )
    return [pscustomobject]@{
        ExitCodeRules        = $ExitCodeRules
        EnvFileExists        = $EnvFileExists
        InstallCompleted     = $InstallCompleted
        RemovalSilentlyFails = $RemovalSilentlyFails
        # Simulates a `stop` that exits 0 while the container keeps
        # running -- the exact case the stop VERIFICATION exists for.
        StopIsIneffective    = $StopIsIneffective
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

            # --- real-CLI precondition fidelity (Fix Round 2, §20) ------
            # Without these, the mock would happily "succeed" at commands
            # the actual Docker CLI rejects, which is exactly how the
            # `--no-build` and missing-.env defects survived Fix Round 1.
            # Each rule below reproduces output observed from the real
            # Docker Compose CLI v5.1.1 in this sandbox.
            if ($FilePath -eq 'docker' -and $Arguments -contains 'compose') {
                # `docker compose run` has no --no-build flag.
                if ($Arguments -contains '--no-build') {
                    $msg = 'unknown flag: --no-build'
                    if (-not $AllowNonZeroExit) { throw $msg }
                    return [pscustomobject]@{ ExitCode = 16; Output = @($msg) }
                }
                # Every compose subcommand must render compose.yml, which
                # needs the env file. A missing one fails two ways.
                if (-not (Test-EnvFileExists) -and $Arguments -notcontains 'version') {
                    $msg = if ($Arguments -contains '--env-file') {
                        'couldn''t find env file: /repo/deployment/local-staging/.env'
                    }
                    else {
                        'error while interpolating services.postgres.environment.POSTGRES_DB: required variable POSTGRES_DB is missing a value'
                    }
                    if (-not $AllowNonZeroExit) { throw $msg }
                    return [pscustomobject]@{ ExitCode = 1; Output = @($msg) }
                }
            }

            $exitCode = 0
            $output = @()
            foreach ($rule in $ctx.ExitCodeRules) {
                if ($joined -like "*$($rule.Match)*") {
                    $exitCode = [int]$rule.ExitCode
                    if ($rule.ContainsKey('Output')) { $output = @($rule.Output) }
                    break
                }
            }

            # --- container state reflects the commands already issued ----
            # Fix Round 4 fidelity: a static `ps` fixture would keep
            # reporting the backend as running after a successful `stop`,
            # so the post-stop verification could never pass and the
            # healthy update path could not be tested at all. Track which
            # services this run has stopped/started and rewrite the state
            # query's output accordingly, the way a real daemon would.
            if ($exitCode -eq 0 -and $Arguments -contains 'compose') {
                if ($Arguments -contains 'stop' -and -not $ctx.StopIsIneffective) {
                    foreach ($svc in @('postgres', 'redis', 'backend', 'frontend')) {
                        if ($Arguments -contains $svc) { $script:StoppedServices += $svc }
                    }
                    # A bare `stop` with no service names stops everything.
                    if (-not (@('postgres', 'redis', 'backend', 'frontend') | Where-Object { $Arguments -contains $_ })) {
                        $script:StoppedServices += @('postgres', 'redis', 'backend', 'frontend')
                    }
                }
                if ($Arguments -contains 'up') {
                    foreach ($svc in @('postgres', 'redis', 'backend', 'frontend')) {
                        if ($Arguments -contains $svc) {
                            $script:StoppedServices = @($script:StoppedServices | Where-Object { $_ -ne $svc })
                        }
                    }
                }
            }
            if ($Arguments -contains 'ps' -and @($script:StoppedServices).Count -gt 0) {
                $output = @($output | ForEach-Object {
                        $line = "$_"
                        foreach ($svc in $script:StoppedServices) {
                            if ($line -match "com\.docker\.compose\.service=$svc\b") {
                                $line = $line -replace '"State":"running"', '"State":"exited"'
                                $line = $line -replace '"Status":"Up [^"]*"', '"Status":"Exited (0) 1 second ago"'
                            }
                        }
                        $line
                    })
            }

            if ($exitCode -ne 0 -and -not $AllowNonZeroExit) {
                throw "$FilePath exited with code $exitCode during phase '$Phase'."
            }
            return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
        }

        # --- filesystem/environment stubs -------------------------------
        $script:StoppedServices = @()
        $script:EnvGenerated = $false
        function Write-InstallLog { param($Phase, $Message, $Level) }
        # Dynamic on purpose: a real install CREATES .env partway through,
        # after which Compose commands legitimately start working.
        function Test-EnvFileExists { return ($ctx.EnvFileExists -or $script:EnvGenerated) }
        function Get-ConfiguredHttpPort { return 80 }
        function Get-CurrentSourceSha { return 'testsha0000000000000000000000000000000000' }
        function Invoke-PrerequisiteChecks { param($FrontendPort) return @() }
        function Invoke-DockerComposeConfigOnly { return 0 }
        function New-LocalStagingEnvFile { param($AllowedOrigins, $HttpPort) $script:EnvGenerated = $true }
        function Test-MepInstallCompleted { return $ctx.InstallCompleted }
        function Get-InstallMetadata { if ($ctx.InstallCompleted) { return [pscustomobject]@{ InstallCompleted = $true } } return $null }
        function Set-InstallMetadata {
            param($SourceSha, $SchemaVersion, [switch]$RequireExistingCompletion)
            # Mirrors the real guard: update passes -RequireExistingCompletion
            # and must never be able to flip InstallCompleted to true.
            if ($RequireExistingCompletion -and -not $ctx.InstallCompleted) {
                throw 'Refusing to record completion metadata: this installation was never completed.'
            }
            $script:MetadataWritten = $true
        }

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

Test-Case 'install: migration passes no unsupported build flag' {
    # Fix Round 2, P1-A. An earlier revision passed `--no-build`, which
    # `docker compose run` does not accept -- the real CLI answers
    # "unknown flag: --no-build", so migration could never have run.
    # `--build` is equally forbidden: it would add a second implicit build
    # and weaken the explicit build-once sequence.
    $ctx = New-MockContext
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
            -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    $migrateCall = @($calls | Where-Object { $_ -like '*deploy_migrate.py*' })[0]
    Assert-True ($migrateCall -notlike '*--no-build*') 'migration must NOT pass --no-build (unsupported by docker compose run)'
    Assert-True ($migrateCall -notlike '*--build*') 'migration must NOT pass --build (would add a second implicit build)'
    Assert-True ($migrateCall -like '*--no-deps*') 'migration must still run without starting dependencies'
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
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -StopIsIneffective $true -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=postgres","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=redis","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=backend","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=frontend","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}') }
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
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=postgres","State":"exited","Status":"Exited (0) 5 minutes ago","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=redis","State":"exited","Status":"Exited (0) 5 minutes ago","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=backend","State":"exited","Status":"Exited (0) 5 minutes ago","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=frontend","State":"exited","Status":"Exited (0) 5 minutes ago","Ports":""}') }
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
    $psCalls = @($calls | Where-Object { $_ -like 'ps *' })
    Assert-True ($psCalls.Count -ge 1) 'state inspection must query container state'
    foreach ($c in $psCalls) {
        Assert-True ($c -like '*--all*') "every container-state query must pass --all (saw: $c)"
    }
}

Test-Case 'state: a subset of expected services is PARTIAL, not healthy' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=postgres","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}') }
    )
    $state = Invoke-WithMocks -Context $ctx -Body { return Get-InstallationState }
    Assert-Equal 'PARTIAL' $state 'PostgreSQL alone must never be classified EXISTING_HEALTHY'
}

Test-Case 'state: an installation that never completed is PARTIAL even when running' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $false -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=postgres","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=redis","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=backend","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=frontend","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}') }
    )
    $state = Invoke-WithMocks -Context $ctx -Body { return Get-InstallationState }
    Assert-Equal 'PARTIAL' $state 'an install whose Administrator bootstrap never succeeded must not look healthy'
}

Test-Case 'state: no config and no containers is FRESH' {
    $ctx = New-MockContext -EnvFileExists $false -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @() }
    )
    $state = Invoke-WithMocks -Context $ctx -Body { return Get-InstallationState }
    Assert-Equal 'FRESH' $state 'a machine with no config and no containers is FRESH'
}

Test-Case 'state: containers without config is AMBIGUOUS, never guessed at' {
    $ctx = New-MockContext -EnvFileExists $false -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=postgres","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}') }
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
# Fix Round 3: Redis is NON-BLOCKING. It must never demote the deployment
# state, while remaining part of fresh/orphan discovery.
# ===========================================================================

function New-ContainerJson {
    <#
    .SYNOPSIS
    Builds one `docker ps --format json` line for a service, so the Redis
    matrix below reads as a state table rather than a wall of JSON.
    #>
    param(
        [Parameter(Mandatory)] [string]$Service,
        [ValidateSet('running', 'exited')] [string]$State = 'running',
        [ValidateSet('healthy', 'unhealthy', 'none')] [string]$Health = 'healthy'
    )
    $status = if ($State -ne 'running') { 'Exited (0) 5 minutes ago' }
    elseif ($Health -eq 'none') { 'Up 5 minutes' }
    else { "Up 5 minutes ($Health)" }
    return ('{"Labels":"com.docker.compose.project=mep-local-staging,' +
        "com.docker.compose.service=$Service" + '","State":"' + $State +
        '","Status":"' + $status + '","Ports":""}')
}

function Get-StateFor {
    param([string[]]$Containers, [bool]$EnvFileExists = $true, [bool]$InstallCompleted = $true)
    $ctx = New-MockContext -EnvFileExists $EnvFileExists -InstallCompleted $InstallCompleted -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = $Containers }
    )
    return Invoke-WithMocks -Context $ctx -Body { return Get-InstallationState }
}

$requiredRunning = @(
    (New-ContainerJson -Service 'postgres'),
    (New-ContainerJson -Service 'backend'),
    (New-ContainerJson -Service 'frontend')
)
$requiredStopped = @(
    (New-ContainerJson -Service 'postgres' -State 'exited'),
    (New-ContainerJson -Service 'backend' -State 'exited'),
    (New-ContainerJson -Service 'frontend' -State 'exited')
)

Test-Case 'A. completed + required running + Redis running -> EXISTING_HEALTHY' {
    $state = Get-StateFor -Containers ($requiredRunning + @(New-ContainerJson -Service 'redis'))
    Assert-Equal 'EXISTING_HEALTHY' $state 'the fully healthy case must be EXISTING_HEALTHY'
}

Test-Case 'B. completed + required running + Redis ABSENT -> EXISTING_HEALTHY' {
    # The reported defect: Redis was counted as a required member of the
    # complete service set, so its absence produced PARTIAL and blocked
    # update eligibility after a legitimate Redis failure.
    $state = Get-StateFor -Containers $requiredRunning
    Assert-Equal 'EXISTING_HEALTHY' $state 'a missing Redis must not demote a healthy deployment to PARTIAL'
}

Test-Case 'C. completed + required running + Redis STOPPED -> EXISTING_HEALTHY' {
    $state = Get-StateFor -Containers ($requiredRunning + @(New-ContainerJson -Service 'redis' -State 'exited'))
    Assert-Equal 'EXISTING_HEALTHY' $state 'a stopped Redis is degraded, not a partial installation'
}

Test-Case 'D. completed + required running + Redis UNHEALTHY -> EXISTING_HEALTHY' {
    $state = Get-StateFor -Containers ($requiredRunning + @(New-ContainerJson -Service 'redis' -Health 'unhealthy'))
    Assert-Equal 'EXISTING_HEALTHY' $state 'an unhealthy Redis must not block update eligibility'
}

Test-Case 'E. completed + backend ABSENT -> PARTIAL' {
    # Do not overcorrect: only Redis is optional.
    $state = Get-StateFor -Containers @(
        (New-ContainerJson -Service 'postgres'),
        (New-ContainerJson -Service 'frontend'),
        (New-ContainerJson -Service 'redis')
    )
    Assert-Equal 'PARTIAL' $state 'a missing backend is a genuinely incomplete deployment'
}

Test-Case 'F. completed + postgres ABSENT -> PARTIAL' {
    $state = Get-StateFor -Containers @(
        (New-ContainerJson -Service 'backend'),
        (New-ContainerJson -Service 'frontend'),
        (New-ContainerJson -Service 'redis')
    )
    Assert-Equal 'PARTIAL' $state 'PostgreSQL is blocking and required'
}

Test-Case 'G. completed + required all stopped + Redis absent -> EXISTING_STOPPED' {
    $state = Get-StateFor -Containers $requiredStopped
    Assert-Equal 'EXISTING_STOPPED' $state 'an intentionally stopped application is EXISTING_STOPPED'
}

Test-Case 'H. completed + required all stopped + Redis STILL RUNNING -> EXISTING_STOPPED' {
    # An optional service must not dominate the primary application state:
    # a leftover Redis container cannot turn a deliberately stopped
    # application into PARTIAL.
    $state = Get-StateFor -Containers ($requiredStopped + @(New-ContainerJson -Service 'redis'))
    Assert-Equal 'EXISTING_STOPPED' $state 'a leftover Redis must not mask a stopped application'
}

Test-Case 'I. no .env + ONLY an orphan Redis container -> AMBIGUOUS' {
    # Redis is optional for health but still counts for discovery: an
    # orphan Redis proves this machine is not clean.
    $state = Get-StateFor -Containers @(New-ContainerJson -Service 'redis') -EnvFileExists $false
    Assert-Equal 'AMBIGUOUS' $state 'an orphan Redis without .env is a conflict, not FRESH'
}

Test-Case 'J. incomplete metadata + required running -> PARTIAL regardless of Redis' {
    # The Administrator/completion invariant outranks Redis policy.
    $state = Get-StateFor -Containers ($requiredRunning + @(New-ContainerJson -Service 'redis')) -InstallCompleted $false
    Assert-Equal 'PARTIAL' $state 'Redis health must never weaken the completion invariant'
}

Test-Case 'service model: required + optional exactly partition the known set' {
    $result = Invoke-WithMocks -Context (New-MockContext) -Body {
        return [pscustomobject]@{
            Required = @($Script:RequiredServices)
            Optional = @($Script:OptionalServices)
            Known    = @($Script:KnownServices)
        }
    }
    Assert-True ($result.Optional -contains 'redis') 'redis must be classified optional'
    foreach ($svc in @('postgres', 'backend', 'frontend')) {
        Assert-True ($result.Required -contains $svc) "$svc must be classified required"
        Assert-True (-not ($result.Optional -contains $svc)) "$svc must not be optional"
    }
    Assert-Equal (($result.Required + $result.Optional | Sort-Object) -join ',') `
        (($result.Known | Sort-Object) -join ',') `
        'KnownServices must be exactly RequiredServices + OptionalServices'
}

Test-Case 'update: a completed deployment with Redis absent passes the state gate' {
    # The operational consequence of the fix: a legitimate Redis failure
    # must not lock the operator out of updating.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                (New-ContainerJson -Service 'postgres' -State 'exited'),
                (New-ContainerJson -Service 'backend' -State 'exited'),
                (New-ContainerJson -Service 'frontend' -State 'exited')) }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepUpdate | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    Assert-True (@($result -match 'deploy_migrate\.py').Count -gt 0) 'update must proceed with Redis absent'
}

Test-Case 'update: incomplete install is still rejected even with Redis healthy' {
    # Administrator invariant remains stronger than Redis status.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $false -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = ($requiredRunning + @(New-ContainerJson -Service 'redis')) }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try { Invoke-MepUpdate | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw; Calls = @($script:RecordedCalls | ForEach-Object { $_.Args }) }
    }
    Assert-True $result.Threw 'a healthy Redis must not let an incomplete install be updated'
    Assert-True (-not ($result.Calls -match 'deploy_migrate\.py')) 'no migration may run'
}

# ===========================================================================
# Fix Round 4: update must converge PostgreSQL to healthy before every
# migration, and must not issue a misleading stop against an already
# stopped deployment.
# ===========================================================================

function Get-UpdateCallOrder {
    <#
    .SYNOPSIS
    Runs Invoke-MepUpdate against a scripted container state and returns
    the ordered native-command argument list plus whether metadata was
    written, so ordering can be asserted on real orchestration calls
    rather than on source order.
    #>
    param(
        [Parameter(Mandatory)] [string[]]$Containers,
        [hashtable[]]$ExtraRules = @()
    )
    $rules = @(@{ Match = 'ps --all --filter'; ExitCode = 0; Output = $Containers }) + $ExtraRules
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules $rules
    return Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try { Invoke-MepUpdate | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{
            Threw           = $threw
            Calls           = @($script:RecordedCalls | ForEach-Object { $_.Args })
            MetadataWritten = $script:MetadataWritten
        }
    }
}

function Get-CallIndex {
    param([string[]]$Calls, [Parameter(Mandatory)] [string]$Pattern)
    return [array]::FindIndex([string[]]$Calls, [Predicate[string]] { param($c) $c -match $Pattern })
}

$healthyContainers = @(
    (New-ContainerJson -Service 'postgres'),
    (New-ContainerJson -Service 'redis'),
    (New-ContainerJson -Service 'backend'),
    (New-ContainerJson -Service 'frontend')
)
$stoppedContainers = @(
    (New-ContainerJson -Service 'postgres' -State 'exited'),
    (New-ContainerJson -Service 'redis' -State 'exited'),
    (New-ContainerJson -Service 'backend' -State 'exited'),
    (New-ContainerJson -Service 'frontend' -State 'exited')
)

Test-Case '1. EXISTING_HEALTHY update: build -> stop -> postgres -> migrate -> start -> metadata' {
    $r = Get-UpdateCallOrder -Containers $healthyContainers
    Assert-True (-not $r.Threw) 'a healthy update must succeed'
    $build = Get-CallIndex -Calls $r.Calls -Pattern 'build backend frontend'
    $stop = Get-CallIndex -Calls $r.Calls -Pattern 'stop backend frontend'
    $pg = Get-CallIndex -Calls $r.Calls -Pattern "up -d --wait .*postgres"
    $migrate = Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py'
    $start = Get-CallIndex -Calls $r.Calls -Pattern 'backend frontend' # start-app
    Assert-True ($build -ge 0) 'build must run'
    Assert-True ($stop -ge 0) 'a healthy update must stop the application writers'
    Assert-True ($pg -ge 0) 'a healthy update must still converge PostgreSQL to healthy'
    Assert-True ($migrate -ge 0) 'migration must run'
    Assert-True ($build -lt $stop) 'build before stop'
    Assert-True ($stop -lt $pg) 'stop before the PostgreSQL health gate'
    Assert-True ($pg -lt $migrate) 'PostgreSQL must be healthy BEFORE migration'
    Assert-True $r.MetadataWritten 'metadata is written on success'
}

Test-Case '2. EXISTING_STOPPED update: PostgreSQL is started BEFORE migration' {
    # The reported defect: update accepted EXISTING_STOPPED but never
    # started PostgreSQL, and the migration runs with --no-deps, so it
    # could never reach the database.
    $r = Get-UpdateCallOrder -Containers $stoppedContainers
    Assert-True (-not $r.Threw) 'a stopped-deployment update must succeed'
    $pg = Get-CallIndex -Calls $r.Calls -Pattern "up -d --wait .*postgres"
    $migrate = Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py'
    Assert-True ($pg -ge 0) 'PostgreSQL must be started for a stopped-deployment update'
    Assert-True ($migrate -ge 0) 'migration must run'
    Assert-True ($pg -lt $migrate) 'PostgreSQL must be healthy BEFORE migration'
    Assert-True $r.MetadataWritten 'metadata is written on success'
}

Test-Case '2b. EXISTING_STOPPED update issues no misleading application stop' {
    $r = Get-UpdateCallOrder -Containers $stoppedContainers
    $stop = Get-CallIndex -Calls $r.Calls -Pattern 'stop backend frontend'
    Assert-True ($stop -lt 0) 'an already-stopped application must not be told to stop again'
}

Test-Case '2c. EXISTING_STOPPED update ends with the application started (documented contract)' {
    $r = Get-UpdateCallOrder -Containers $stoppedContainers
    $migrate = Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py'
    $startApp = Get-CallIndex -Calls $r.Calls -Pattern "up -d --wait .*backend frontend"
    Assert-True ($startApp -ge 0) 'a successful update ends with the application running and ready'
    Assert-True ($migrate -lt $startApp) 'the application starts after the migration'
}

Test-Case '3. EXISTING_STOPPED + PostgreSQL start failure -> no migration, no metadata' {
    $r = Get-UpdateCallOrder -Containers $stoppedContainers -ExtraRules @(
        @{ Match = 'up -d --wait --wait-timeout 120 postgres'; ExitCode = 1 }
    )
    Assert-True $r.Threw 'a failed PostgreSQL start must fail the update'
    Assert-True ((Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py') -lt 0) 'no migration may run without a healthy database'
    Assert-True (-not $r.MetadataWritten) 'no metadata may be written'
}

Test-Case '4. EXISTING_HEALTHY + stop failure -> no PostgreSQL gate, no migration' {
    $r = Get-UpdateCallOrder -Containers $healthyContainers -ExtraRules @(
        @{ Match = 'stop backend frontend'; ExitCode = 1 }
    )
    Assert-True $r.Threw 'a failed stop must fail the update'
    Assert-True ((Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py') -lt 0) 'no migration after a failed stop'
    Assert-True (-not $r.MetadataWritten) 'no metadata may be written'
}

Test-Case '5. EXISTING_HEALTHY + PostgreSQL health failure after stop -> no migration, no metadata' {
    $r = Get-UpdateCallOrder -Containers $healthyContainers -ExtraRules @(
        @{ Match = 'up -d --wait --wait-timeout 120 postgres'; ExitCode = 1 }
    )
    Assert-True $r.Threw 'a PostgreSQL health failure must fail the update'
    Assert-True ((Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py') -lt 0) 'no migration without a healthy database'
    Assert-True (-not $r.MetadataWritten) 'no metadata may be written'
}

Test-Case '6a. Redis absent does not affect the healthy update path' {
    $r = Get-UpdateCallOrder -Containers @(
        (New-ContainerJson -Service 'postgres'),
        (New-ContainerJson -Service 'backend'),
        (New-ContainerJson -Service 'frontend')
    )
    Assert-True (-not $r.Threw) 'Redis absence must not break a healthy update'
    Assert-True ((Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py') -ge 0) 'migration still runs'
    Assert-True $r.MetadataWritten 'update still completes'
}

Test-Case '6b. Redis absent does not affect the stopped update path' {
    $r = Get-UpdateCallOrder -Containers @(
        (New-ContainerJson -Service 'postgres' -State 'exited'),
        (New-ContainerJson -Service 'backend' -State 'exited'),
        (New-ContainerJson -Service 'frontend' -State 'exited')
    )
    Assert-True (-not $r.Threw) 'Redis absence must not break a stopped-deployment update'
    $pg = Get-CallIndex -Calls $r.Calls -Pattern "up -d --wait .*postgres"
    $migrate = Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py'
    Assert-True ($pg -ge 0 -and $pg -lt $migrate) 'PostgreSQL still gates the migration'
    Assert-True $r.MetadataWritten 'update still completes'
}

Test-Case 'update: no path can reach migration without the PostgreSQL health gate' {
    # Asserted on real orchestration calls, for both entry states.
    foreach ($containers in @($healthyContainers, $stoppedContainers)) {
        $r = Get-UpdateCallOrder -Containers $containers
        $pg = Get-CallIndex -Calls $r.Calls -Pattern "up -d --wait .*postgres"
        $migrate = Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py'
        Assert-True ($migrate -ge 0) 'migration runs'
        Assert-True ($pg -ge 0 -and $pg -lt $migrate) 'the PostgreSQL health gate always precedes migration'
    }
}

Test-Case 'update: PostgreSQL is never stopped during a healthy update' {
    $r = Get-UpdateCallOrder -Containers $healthyContainers
    foreach ($c in $r.Calls) {
        if ($c -match '\bstop ') {
            Assert-True ($c -notmatch 'postgres') "the update must not stop PostgreSQL (saw: $c)"
        }
    }
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
# Fix Round 2: fresh install must not require .env; update must not
# launder an incomplete installation into a completed one.
# ===========================================================================

Test-Case 'state: fresh checkout with no .env and no containers is FRESH, not AMBIGUOUS' {
    # P1-B. The harness now fails ANY `docker compose` call while .env is
    # absent, exactly as the real CLI does, so this passes only because
    # state inspection genuinely avoids Compose.
    $ctx = New-MockContext -EnvFileExists $false -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @() }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        $state = Get-InstallationState
        return [pscustomobject]@{
            State = $state
            Calls = @($script:RecordedCalls | ForEach-Object { $_.Args })
        }
    }
    Assert-Equal 'FRESH' $result.State 'a fresh machine must classify as FRESH'
    Assert-True (-not ($result.Calls -match '(^| )compose( |$)')) 'state inspection must not invoke docker compose at all'
}

Test-Case 'state: inspection is scoped to the deterministic compose project label' {
    $ctx = New-MockContext -EnvFileExists $false
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Get-InstallationState | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    $inspect = @($calls | Where-Object { $_ -like '*ps --all --filter*' })[0]
    Assert-True ($inspect -like '*label=com.docker.compose.project=mep-local-staging*') `
        'state inspection must be scoped to this project label, never all containers'
}

Test-Case 'install: a genuinely fresh machine reaches config generation and completes' {
    # The end-to-end consequence of P1-B: before the fix, install aborted
    # at AMBIGUOUS and .env was never created.
    $ctx = New-MockContext -EnvFileExists $false -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @() }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
            -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites | Out-Null
        return [pscustomobject]@{
            EnvGenerated    = $script:EnvGenerated
            MetadataWritten = $script:MetadataWritten
        }
    }
    Assert-True $result.EnvGenerated 'a fresh install must generate .env'
    Assert-True $result.MetadataWritten 'a fresh install that satisfies every invariant must record completion'
}

Test-Case 'update: refuses an installation that never completed' {
    # P1-C. .env exists (so this is not simply "no installation"), but the
    # Administrator invariant was never satisfied.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $false -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=postgres","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=backend","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}') }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try { Invoke-MepUpdate | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{
            Threw           = $threw
            Calls           = @($script:RecordedCalls | ForEach-Object { $_.Args })
            MetadataWritten = $script:MetadataWritten
        }
    }
    Assert-True $result.Threw 'update must refuse an installation that never completed'
    Assert-True (-not ($result.Calls -match 'build backend frontend')) 'update must not build before the precondition passes'
    Assert-True (-not ($result.Calls -match '(^| )stop( |$)')) 'update must not stop anything before the precondition passes'
    Assert-True (-not ($result.Calls -match 'deploy_migrate\.py')) 'update must not migrate an incomplete installation'
    Assert-True (-not $result.MetadataWritten) 'update must never write completion metadata for an incomplete installation'
}

Test-Case 'update: bootstrap-failed install cannot be completed by running update afterwards' {
    # The exact laundering path the review named:
    # PARTIAL -> update -> COMPLETED must not exist.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $false -ExitCodeRules @(
        @{ Match = 'bootstrap_admin'; ExitCode = 1; Output = @('boom') },
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=postgres","State":"running","Status":"Up 5 minutes (healthy)","Ports":""}') }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        $installThrew = $false
        try {
            Invoke-MepInstall -AdminCredentialCallback { @{ EmployeeCode = 'A1'; Email = 'a@b.c'; FullName = 'A B' } } `
                -ConfigCallback { @{ AllowedOrigins = 'http://192.0.2.1'; HttpPort = 80 } } -SkipPrerequisites | Out-Null
        }
        catch { $installThrew = $true }
        $updateThrew = $false
        try { Invoke-MepUpdate | Out-Null } catch { $updateThrew = $true }
        return [pscustomobject]@{
            InstallThrew    = $installThrew
            UpdateThrew     = $updateThrew
            MetadataWritten = $script:MetadataWritten
        }
    }
    Assert-True $result.InstallThrew 'a failed Administrator bootstrap must fail the install'
    Assert-True $result.UpdateThrew 'update must reject the resulting incomplete installation'
    Assert-True (-not $result.MetadataWritten) 'no completion metadata may exist after this sequence'
}

Test-Case 'update: completion precondition holds even if state classification says healthy' {
    # Defense in depth, isolated. Today Get-InstallationState already
    # returns PARTIAL whenever completion metadata is absent, so the state
    # check alone would catch the laundering path -- which means a test
    # driven only through state cannot tell whether the explicit
    # completion precondition still exists. This forces the inconsistent
    # pair (classifier says healthy, completion says never finished) so
    # the precondition itself is pinned.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $false
    $result = Invoke-WithMocks -Context $ctx -Body {
        function Get-InstallationState { return 'EXISTING_HEALTHY' }
        $threw = $false
        try { Invoke-MepUpdate | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{
            Threw           = $threw
            Calls           = @($script:RecordedCalls | ForEach-Object { $_.Args })
            MetadataWritten = $script:MetadataWritten
        }
    }
    Assert-True $result.Threw 'update must check completion itself, not rely solely on state classification'
    Assert-True (-not ($result.Calls -match 'deploy_migrate\.py')) 'no migration may run without a completed installation'
    Assert-True (-not $result.MetadataWritten) 'no completion metadata may be written'
}

Test-Case 'update: proceeds normally from a completed, healthy installation' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=postgres","State":"exited","Status":"Exited (0) 5 minutes ago","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=redis","State":"exited","Status":"Exited (0) 5 minutes ago","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=backend","State":"exited","Status":"Exited (0) 5 minutes ago","Ports":""}',
                '{"Labels":"com.docker.compose.project=mep-local-staging,com.docker.compose.service=frontend","State":"exited","Status":"Exited (0) 5 minutes ago","Ports":""}') }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepUpdate | Out-Null
        return [pscustomobject]@{
            Calls           = @($script:RecordedCalls | ForEach-Object { $_.Args })
            MetadataWritten = $script:MetadataWritten
        }
    }
    Assert-True (@($result.Calls -match 'deploy_migrate\.py').Count -gt 0) 'a legitimate update still migrates'
    Assert-True $result.MetadataWritten 'a legitimate update still records its new source sha'
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
