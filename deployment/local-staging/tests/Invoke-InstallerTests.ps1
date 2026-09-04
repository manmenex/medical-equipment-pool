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
        [bool]$StopIsIneffective = $false,
        [bool]$BackupChecksumCorrupt = $false,
        [string]$BackupRootOverride = '',
        [string]$ExternalDir = '',
        [ValidateSet('normal', 'no-ok', 'duplicate', 'outside', 'nested', 'traversal')]
        [string]$BackupOutputMode = 'normal',
        [bool]$BackupHostFileMissing = $false,
        [bool]$BackupManifestMissing = $false
    )
    return [pscustomobject]@{
        ExitCodeRules        = $ExitCodeRules
        EnvFileExists        = $EnvFileExists
        InstallCompleted     = $InstallCompleted
        RemovalSilentlyFails = $RemovalSilentlyFails
        # Simulates a `stop` that exits 0 while the container keeps
        # running -- the exact case the stop VERIFICATION exists for.
        StopIsIneffective     = $StopIsIneffective
        # PR24D-L3: simulates an archive whose bytes do not match the
        # checksum the manifest records (a corrupted bind-mount transfer).
        BackupChecksumCorrupt = $BackupChecksumCorrupt
        BackupRootOverride    = $BackupRootOverride
        # A directory OUTSIDE the backup root, owned by the calling test.
        # The mock body runs in a child scope of the runner, not of the
        # test case, so `$using:` is invalid here -- the path travels on
        # the context object instead.
        ExternalDir           = $ExternalDir
        # Fix Round 2: shapes of PR24C success output that must all fail
        # closed rather than resolve to some other archive.
        BackupOutputMode      = $BackupOutputMode
        BackupHostFileMissing = $BackupHostFileMissing
        BackupManifestMissing = $BackupManifestMissing
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
        . (Join-Path $deploymentRoot 'lib/Backup.ps1')

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
            # PR24D-L3: emulate PR24C's backup script producing a real
            # archive + manifest on the bind mount, so the wrapper's own
            # verification runs against real bytes.
            #
            # Fix Round 2 fidelity, two corrections that matter:
            #  * the filename is PR24C's ACTUAL form. pg_backup_lib strips
            #    non-alphanumerics from the environment, so 'local-staging'
            #    becomes 'localstaging' -- the old mock wrote an unreal
            #    'local-staging' name that the real generator never emits.
            #  * the run PRINTS '[backup] OK: <container path>', which is
            #    how the wrapper now identifies the artifact it produced.
            #    Without this line the mock could not exercise the binding
            #    at all.
            if ($exitCode -eq 0 -and ($joined -like '*backup_postgres.py*')) {
                # Distinct, monotonically increasing, and still a VALID
                # PR24C timestamp -- a GUID suffix would not be.
                $script:BackupSequence += 1
                $stamp = [DateTime]::UtcNow.AddSeconds($script:BackupSequence).ToString('yyyyMMddTHHmmssZ')
                $fileName = "mep-postgres-localstaging-$stamp.dump"
                $archivePath = Join-Path $script:TestBackupRoot $fileName
                if ($ctx.BackupHostFileMissing) {
                    # PR24C claims success but the bind mount delivered
                    # nothing to the host.
                    $output = @("[backup] OK: /mep-backups/$fileName")
                }
                else {
                    Set-Content -LiteralPath $archivePath -Value 'PGDMP-test-archive-bytes' -NoNewline
                    $realHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
                    $recorded = if ($ctx.BackupChecksumCorrupt) { ('0' * 64) } else { $realHash }
                    if (-not $ctx.BackupManifestMissing) {
                        $manifest = @{
                            backup_filename  = $fileName
                            created_at       = [DateTime]::UtcNow.ToString('o')
                            environment      = 'local-staging'
                            alembic_revision = 'testrev'
                            checksum_sha256  = $recorded
                        } | ConvertTo-Json
                        Set-Content -LiteralPath "$archivePath.manifest.json" -Value $manifest
                    }
                    $okLines = switch ($ctx.BackupOutputMode) {
                        'no-ok' { , @('[backup] starting: target=postgres/mep environment=local-staging') }
                        'duplicate' {
                            , @("[backup] OK: /mep-backups/$fileName",
                                "[backup] OK: /mep-backups/mep-postgres-localstaging-20990101T000000Z.dump")
                        }
                        'outside' { , @('[backup] OK: /var/lib/postgresql/mep-postgres-localstaging-20260101T000000Z.dump') }
                        'nested' { , @("[backup] OK: /mep-backups/nested/$fileName") }
                        'traversal' { , @('[backup] OK: /mep-backups/../mep-postgres-localstaging-20260101T000000Z.dump') }
                        default { , @("[backup] OK: /mep-backups/$fileName") }
                    }
                    $output = @($okLines) + @("[backup]     size_bytes=24 checksum_sha256=$recorded")
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
        # PR24D-L3: the backup root is a REAL temporary directory. The
        # command mock below writes a real archive + manifest into it when
        # PR24C's backup script "runs", so Invoke-MepBackup's discovery and
        # checksum verification execute against real files rather than
        # being stubbed away -- those checks are the thing under test.
        $script:TestBackupRoot = if ($ctx.BackupRootOverride) { $ctx.BackupRootOverride }
        else { Join-Path ([System.IO.Path]::GetTempPath()) ("mep-test-backups-" + [Guid]::NewGuid().ToString('N')) }
        New-Item -ItemType Directory -Path $script:TestBackupRoot -Force | Out-Null
        function Get-MepBackupRoot { return $script:TestBackupRoot }
        function Get-MepConfiguredValue {
            param([Parameter(Mandatory)] [string]$Name)
            switch ($Name) {
                'POSTGRES_DB' { return 'mep_local_staging_db' }
                'POSTGRES_USER' { return 'mep_user' }
                'POSTGRES_PASSWORD' { return 'test-password-not-a-real-secret' }
                default { return 'x' }
            }
        }

        $script:StoppedServices = @()
        $script:EnvGenerated = $false
        $script:BackupSequence = 0
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
            param([Parameter(Position = 0)][string]$LiteralPath, [switch]$Force, [switch]$Recurse)
            $script:RemovedPaths += $LiteralPath
            # Rehearsal staging directories are real on disk, so delete
            # them for real -- otherwise the suite leaks temp data and the
            # cleanup assertion would be testing a lie.
            if ($LiteralPath -and $LiteralPath -like '*restore-staging-*') {
                Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        function Test-Path {
            [CmdletBinding()]
            param([Parameter(Position = 0)][string]$LiteralPath, [string]$Path)
            $target = if ($LiteralPath) { $LiteralPath } else { $Path }
            # A path we "removed" is gone -- unless this context is
            # simulating a removal that silently failed.
            if ($script:RemovedPaths -contains $target) { return [bool]$ctx.RemovalSilentlyFails }
            # Real files under the test backup root are genuinely on disk:
            # delegate rather than lying, so the backup wrapper's manifest
            # and checksum checks are exercised for real.
            if ($target -and ($target.StartsWith($script:TestBackupRoot) -or
                    $target.StartsWith([System.IO.Path]::GetTempPath()))) {
                return (Microsoft.PowerShell.Management\Test-Path -LiteralPath $target)
            }
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
    $backup = Get-CallIndex -Calls $r.Calls -Pattern 'backup_postgres\.py'
    $stop = Get-CallIndex -Calls $r.Calls -Pattern 'stop backend frontend'
    $pg = Get-CallIndex -Calls $r.Calls -Pattern "up -d --wait .*postgres"
    $migrate = Get-CallIndex -Calls $r.Calls -Pattern 'deploy_migrate\.py'
    Assert-True ($build -ge 0) 'build must run'
    Assert-True ($backup -ge 0) 'PR24D-L3: a mandatory pre-update backup must run'
    Assert-True ($stop -ge 0) 'a healthy update must stop the application writers'
    Assert-True ($pg -ge 0) 'a healthy update must converge PostgreSQL to healthy'
    Assert-True ($migrate -ge 0) 'migration must run'
    Assert-True ($build -lt $backup) 'build before backup'
    # PR24D-L3 ordering: the backup precedes the stop, so a backup failure
    # leaves a healthy deployment untouched and still serving.
    Assert-True ($backup -lt $stop) 'backup before stopping the healthy application'
    Assert-True ($stop -lt $migrate) 'stop before migration'
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
# PR24D-L3: backup / restore rehearsal / update backup gate.
# PowerShell is orchestration only -- these prove the wrappers CALL the
# PR24C engine and fail closed, never that they reimplement it.
# ===========================================================================

Test-Case 'L3 backup: delegates to the PR24C backup script, never its own pg_dump' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepBackup -Reason 'test' | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    Assert-True (@($calls -match 'scripts/backup_postgres\.py').Count -gt 0) 'backup must call PR24C backup_postgres.py'
    Assert-True (-not ($calls -match '(^|\s)pg_dump(\s|$)')) 'the wrapper must never invoke pg_dump itself'
    Assert-True (-not ($calls -match 'pg_restore')) 'the wrapper must never invoke pg_restore itself'
}

Test-Case 'L3 backup: converges PostgreSQL before dumping, and never starts the backend' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepBackup -Reason 'test' | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    $pg = Get-CallIndex -Calls $calls -Pattern "up -d --wait .*postgres"
    $backup = Get-CallIndex -Calls $calls -Pattern 'backup_postgres\.py'
    Assert-True ($pg -ge 0 -and $pg -lt $backup) 'PostgreSQL must be healthy before the dump'
    Assert-True (-not ($calls -match "up -d --wait .*backend frontend")) 'backup must not start the application'
    Assert-True ((@($calls -match 'backup_postgres\.py')[0]) -like '*--no-deps*') 'the backup container must not drag dependencies up'
}

Test-Case 'L3 backup: no credential-bearing URL is ever placed on a command line' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepBackup -Reason 'test' | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    foreach ($c in $calls) {
        Assert-True ($c -notmatch 'postgresql\+?a?s?y?n?c?p?g?://[^ ]*:[^ ]*@') "no credential URL may appear in argv (saw: $c)"
        Assert-True ($c -notmatch 'test-password-not-a-real-secret') "no password may appear in argv (saw: $c)"
    }
}

Test-Case 'L3 backup: applies PR24C retention without overriding the 30-day policy' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepBackup -Reason 'test' | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    $prune = @($calls -match 'prune_backups\.py')
    Assert-True ($prune.Count -gt 0) 'retention must use PR24C prune_backups.py'
    Assert-True ($prune[0] -notlike '*--retention-days*') 'the local wrapper must not override the Owner-approved retention window'
}

Test-Case 'L3 backup: a failed PR24C backup fails closed' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'backup_postgres.py'; ExitCode = 1; Output = @('[backup] FAIL: pg_dump exited 1') }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        try { Invoke-MepBackup -Reason 'test' | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw; Calls = @($script:RecordedCalls | ForEach-Object { $_.Args }) }
    }
    Assert-True $result.Threw 'a failed backup must throw, never report success'
    Assert-True (-not ($result.Calls -match 'prune_backups\.py')) 'retention must not run after a failed backup'
}

Test-Case 'L3 backup: a checksum mismatch fails closed and is never downgraded to a warning' {
    # The archive really is written and really is hashed here; only the
    # manifest's recorded checksum is wrong.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -BackupChecksumCorrupt $true
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false
        $message = ''
        try { Invoke-MepBackup -Reason 'test' | Out-Null } catch { $threw = $true; $message = $_.Exception.Message }
        return [pscustomobject]@{ Threw = $threw; Message = $message }
    }
    Assert-True $result.Threw 'a checksum mismatch must fail the backup'
    Assert-True ($result.Message -like '*checksum*') 'the failure must name the checksum verification'
}

# ===========================================================================
# Fix Round 2 (P1): the artifact created, verified, reported and returned by
# one backup invocation must be the SAME artifact.
# ===========================================================================

Test-Case 'L3 backup: a future-dated PRE-EXISTING archive cannot substitute for the one just created' {
    # THE critical regression. The wrapper used to re-scan the directory
    # and take whichever filename sorted newest, so an archive dated 2099
    # -- a stale copy, a file restored from elsewhere, a clock skew --
    # would be verified and reported as though this run had produced it.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $result = Invoke-WithMocks -Context $ctx -Body {
        $root = Get-MepBackupRoot
        $decoy = Join-Path $root 'mep-postgres-localstaging-20990101T000000Z.dump'
        Set-Content -LiteralPath $decoy -Value 'DECOY-NOT-PRODUCED-BY-THIS-RUN' -NoNewline
        $decoyHash = (Get-FileHash -LiteralPath $decoy -Algorithm SHA256).Hash.ToLowerInvariant()
        (@{ backup_filename = (Split-Path -Leaf $decoy); created_at = '2099-01-01T00:00:00Z'
                environment = 'local-staging'; alembic_revision = 'decoyrev'
                checksum_sha256 = $decoyHash } | ConvertTo-Json) |
            Set-Content -LiteralPath "$decoy.manifest.json"

        $produced = Invoke-MepBackup -Reason 'test'
        return [pscustomobject]@{
            Returned = $produced.Name
            # Proof the decoy really would have won a "latest" contest.
            Latest   = (Get-MepLatestBackup).Name
        }
    }
    Assert-True ($result.Latest -eq 'mep-postgres-localstaging-20990101T000000Z.dump') `
        'the decoy must genuinely be the newest by filename, or this test proves nothing'
    Assert-True ($result.Returned -ne 'mep-postgres-localstaging-20990101T000000Z.dump') `
        'the pre-existing future-dated archive must NOT be returned as this run''s backup'
    Assert-True ($result.Returned -like 'mep-postgres-localstaging-*.dump') `
        'the returned artifact must be the archive this invocation produced'
}

Test-Case 'L3 backup: cannot be steered by Get-MepLatestBackup at all' {
    # Poison the "newest existing backup" lookup outright. If the backup
    # path still consults it after success, the returned artifact changes.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $result = Invoke-WithMocks -Context $ctx -Body {
        $root = Get-MepBackupRoot
        $wrong = Join-Path $root 'mep-postgres-localstaging-20200101T000000Z.dump'
        Set-Content -LiteralPath $wrong -Value 'WRONG-ARTIFACT' -NoNewline
        $wrongHash = (Get-FileHash -LiteralPath $wrong -Algorithm SHA256).Hash.ToLowerInvariant()
        (@{ backup_filename = (Split-Path -Leaf $wrong); created_at = '2020-01-01T00:00:00Z'
                environment = 'local-staging'; alembic_revision = 'wrongrev'
                checksum_sha256 = $wrongHash } | ConvertTo-Json) |
            Set-Content -LiteralPath "$wrong.manifest.json"
        function Get-MepLatestBackup { return (Get-Item -LiteralPath $wrong) }

        $produced = Invoke-MepBackup -Reason 'test'
        return $produced.Name
    }
    Assert-True ($result -ne 'mep-postgres-localstaging-20200101T000000Z.dump') `
        'Invoke-MepBackup must not derive its artifact from Get-MepLatestBackup'
}

Test-Case 'L3 backup: success output with no [backup] OK line fails closed' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -BackupOutputMode 'no-ok'
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false; $message = ''
        try { Invoke-MepBackup -Reason 'test' | Out-Null } catch { $threw = $true; $message = $_.Exception.Message }
        return [pscustomobject]@{ Threw = $threw; Message = $message }
    }
    Assert-True $result.Threw 'an unidentifiable artifact must fail the backup'
    Assert-True ($result.Message -like '*cannot be identified*') 'the failure must say the artifact could not be identified'
    Assert-True ($result.Message -notlike '*checksum verification*') 'it must fail before pretending to verify something'
}

Test-Case 'L3 backup: two conflicting [backup] OK lines fail closed' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -BackupOutputMode 'duplicate'
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false; $message = ''
        try { Invoke-MepBackup -Reason 'test' | Out-Null } catch { $threw = $true; $message = $_.Exception.Message }
        return [pscustomobject]@{ Threw = $threw; Message = $message }
    }
    Assert-True $result.Threw 'an ambiguous artifact must fail the backup'
    Assert-True ($result.Message -like '*more than one*') 'the failure must name the ambiguity'
}

Test-Case 'L3 backup: a reported path outside the mounted root fails closed' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -BackupOutputMode 'outside'
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false; $message = ''
        try { Invoke-MepBackup -Reason 'test' | Out-Null } catch { $threw = $true; $message = $_.Exception.Message }
        return [pscustomobject]@{ Threw = $threw; Message = $message }
    }
    Assert-True $result.Threw 'a path this wrapper did not mount must not be mapped onto the host'
    Assert-True ($result.Message -like '*outside the mounted backup directory*') 'the failure must say why'
}

Test-Case 'L3 backup: a nested or traversing reported path fails closed' {
    foreach ($mode in @('nested', 'traversal')) {
        $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -BackupOutputMode $mode
        $result = Invoke-WithMocks -Context $ctx -Body {
            $threw = $false; $message = ''
            try { Invoke-MepBackup -Reason 'test' | Out-Null } catch { $threw = $true; $message = $_.Exception.Message }
            return [pscustomobject]@{ Threw = $threw; Message = $message }
        }
        Assert-True $result.Threw "a '$mode' path must fail closed"
        Assert-True ($result.Message -like '*not a single file directly inside*') "the '$mode' failure must name the path shape"
    }
}

Test-Case 'L3 backup: a reported artifact missing on the host fails closed' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -BackupHostFileMissing $true
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false; $message = ''
        try { Invoke-MepBackup -Reason 'test' | Out-Null } catch { $threw = $true; $message = $_.Exception.Message }
        return [pscustomobject]@{ Threw = $threw; Message = $message }
    }
    Assert-True $result.Threw 'a bind mount that did not deliver the file must fail the backup'
    Assert-True ($result.Message -like '*is not present*') 'the failure must name the missing host file'
}

Test-Case 'L3 backup: the produced artifact having no manifest fails closed' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -BackupManifestMissing $true
    $result = Invoke-WithMocks -Context $ctx -Body {
        $threw = $false; $message = ''
        try { Invoke-MepBackup -Reason 'test' | Out-Null } catch { $threw = $true; $message = $_.Exception.Message }
        return [pscustomobject]@{ Threw = $threw; Message = $message }
    }
    Assert-True $result.Threw 'a manifest-less archive must fail the backup'
    Assert-True ($result.Message -like '*manifest*') 'the failure must name the missing manifest'
}

Test-Case 'L3 update gate: a pre-existing backup cannot satisfy the current update' {
    # The gate must be satisfied by the archive THIS update produced.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -BackupOutputMode 'no-ok'
    $result = Invoke-WithMocks -Context $ctx -Body {
        $root = Get-MepBackupRoot
        $old = Join-Path $root 'mep-postgres-localstaging-20990101T000000Z.dump'
        Set-Content -LiteralPath $old -Value 'PRE-EXISTING' -NoNewline
        $oldHash = (Get-FileHash -LiteralPath $old -Algorithm SHA256).Hash.ToLowerInvariant()
        (@{ backup_filename = (Split-Path -Leaf $old); created_at = '2099-01-01T00:00:00Z'
                environment = 'local-staging'; alembic_revision = 'oldrev'
                checksum_sha256 = $oldHash } | ConvertTo-Json) |
            Set-Content -LiteralPath "$old.manifest.json"

        $script:RecordedCalls = @()
        $threw = $false
        try { Invoke-MepUpdate | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw; Calls = @($script:RecordedCalls | ForEach-Object { $_.Args }) }
    }
    Assert-True $result.Threw 'an update whose own backup cannot be identified must stop'
    Assert-True (-not ($result.Calls -match 'alembic upgrade head')) 'no migration may run without this run''s own verified backup'
}

Test-Case 'L3 restore: rehearses into a disposable target, never the live database' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepBackup -Reason 'seed' | Out-Null
        $script:RecordedCalls = @()
        Invoke-MepRestoreRehearsal | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    Assert-True (@($calls -match 'restore_postgres\.py').Count -gt 0) 'restore must call PR24C restore_postgres.py'
    Assert-True (@($calls -match 'CREATE DATABASE mep_local_restore_rehearsal_').Count -gt 0) 'a disposable target must be created'
    Assert-True (-not ($calls -match 'CREATE DATABASE mep_local_staging_db')) 'the live database must never be the target'
    Assert-True (-not ($calls -match 'DROP DATABASE IF EXISTS mep_local_staging_db')) 'the live database must never be dropped'
    Assert-True (@($calls -match 'DROP DATABASE IF EXISTS mep_local_restore_rehearsal_').Count -gt 0) 'the disposable target must be cleaned up'
}

Test-Case 'L3 restore: an EXTERNAL archive sharing a basename with an internal one is not confused for it' {
    # Fix Round 1 (P1). Only the backup root is mounted at /mep-backups, so
    # passing just the file NAME meant an external archive could silently
    # resolve to a DIFFERENT, same-named archive inside the backup root and
    # report a rehearsal PASS for an artifact the operator never selected.
    $externalDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mep-ext-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $externalDir -Force | Out-Null
    try {
        $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExternalDir $externalDir
        $result = Invoke-WithMocks -Context $ctx -Body {
            # An internal backup exists first...
            $internal = Invoke-MepBackup -Reason 'seed'
            # ...and an EXTERNAL file deliberately shares its basename
            # while holding different bytes.
            $externalArchive = Join-Path $ctx.ExternalDir $internal.Name
            Set-Content -LiteralPath $externalArchive -Value 'EXTERNAL-ARCHIVE-DIFFERENT-BYTES' -NoNewline
            $externalHash = (Get-FileHash -LiteralPath $externalArchive -Algorithm SHA256).Hash.ToLowerInvariant()
            (@{ backup_filename = $internal.Name; created_at = [DateTime]::UtcNow.ToString('o')
                    environment = 'local-staging'; alembic_revision = 'extrev'
                    checksum_sha256 = $externalHash } | ConvertTo-Json) |
                Set-Content -LiteralPath "$externalArchive.manifest.json"

            $script:RecordedCalls = @()
            Invoke-MepRestoreRehearsal -BackupFile $externalArchive | Out-Null
            $restoreCall = @($script:RecordedCalls | ForEach-Object { $_.Args } | Where-Object { $_ -match 'restore_postgres\.py' })[0]
            return [pscustomobject]@{
                InternalName = $internal.Name
                RestoreCall  = $restoreCall
                Removed      = @($script:RemovedPaths)
            }
        }
        $flag = '--backup-file /mep-backups/' + $result.InternalName
        Assert-True ($result.RestoreCall -notlike "*$flag*") `
            'an external archive must NOT be addressed as if it were the same-named archive inside the backup root'
        Assert-True ($result.RestoreCall -like '*/mep-backups/.restore-staging-*') `
            'an external archive must be staged under a collision-safe path bound to that exact artifact'
        Assert-True (@($result.Removed | Where-Object { $_ -like '*restore-staging-*' }).Count -gt 0) `
            'the staging directory must be cleaned up'
    }
    finally {
        Remove-Item -LiteralPath $externalDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Test-Case 'L3 restore: an archive already inside the backup root is used in place, without staging' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $result = Invoke-WithMocks -Context $ctx -Body {
        $internal = Invoke-MepBackup -Reason 'seed'
        $script:RecordedCalls = @()
        Invoke-MepRestoreRehearsal -BackupFile $internal.FullName | Out-Null
        $restoreCall = @($script:RecordedCalls | ForEach-Object { $_.Args } | Where-Object { $_ -match 'restore_postgres\.py' })[0]
        return [pscustomobject]@{ Name = $internal.Name; RestoreCall = $restoreCall }
    }
    Assert-True ($result.RestoreCall -like "*--backup-file /mep-backups/$($result.Name)*") `
        'an archive already in the backup root is addressed directly'
    Assert-True ($result.RestoreCall -notlike '*restore-staging*') 'no needless copy is made'
}

Test-Case 'L3 restore: an archive without a manifest fails closed before any database work' {
    $externalDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mep-ext-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $externalDir -Force | Out-Null
    try {
        $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExternalDir $externalDir
        $result = Invoke-WithMocks -Context $ctx -Body {
            $orphan = Join-Path $ctx.ExternalDir 'mep-postgres-local-staging-20260101T000000Z.dump'
            Set-Content -LiteralPath $orphan -Value 'no-manifest' -NoNewline
            $script:RecordedCalls = @()
            $threw = $false
            $message = ''
            try { Invoke-MepRestoreRehearsal -BackupFile $orphan | Out-Null } catch { $threw = $true; $message = $_.Exception.Message }
            return [pscustomobject]@{ Threw = $threw; Message = $message; Calls = @($script:RecordedCalls | ForEach-Object { $_.Args }) }
        }
        Assert-True $result.Threw 'an archive with no manifest cannot be verified and must fail'
        # The message matters: without the explicit precondition the run
        # would still fail, but as an incidental copy error rather than as
        # a stated refusal -- so assert the refusal itself.
        Assert-True ($result.Message -like '*no manifest*') 'the failure must state the missing manifest, not surface an incidental copy error'
        Assert-True (-not ($result.Calls -match 'CREATE DATABASE')) 'no rehearsal database may be created first'
        Assert-True (-not ($result.Calls -match 'restore_postgres\.py')) 'no restore may be attempted'
    }
    finally {
        Remove-Item -LiteralPath $externalDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Test-Case 'L3 restore: an archive INSIDE the backup root without a manifest also fails closed' {
    # The in-root branch does no copying, so nothing incidental would stop
    # it: only the explicit manifest precondition keeps an unverifiable
    # artifact from reaching a real rehearsal.
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $result = Invoke-WithMocks -Context $ctx -Body {
        $orphan = Join-Path (Get-MepBackupRoot) 'mep-postgres-local-staging-20260101T000000Z.dump'
        Set-Content -LiteralPath $orphan -Value 'no-manifest' -NoNewline
        $script:RecordedCalls = @()
        $threw = $false
        $message = ''
        try { Invoke-MepRestoreRehearsal -BackupFile $orphan | Out-Null } catch { $threw = $true; $message = $_.Exception.Message }
        return [pscustomobject]@{ Threw = $threw; Message = $message; Calls = @($script:RecordedCalls | ForEach-Object { $_.Args }) }
    }
    Assert-True $result.Threw 'an in-root archive with no manifest must also fail'
    Assert-True ($result.Message -like '*no manifest*') 'the failure must state the missing manifest'
    Assert-True (-not ($result.Calls -match 'CREATE DATABASE')) 'no rehearsal database may be created'
    Assert-True (-not ($result.Calls -match 'restore_postgres\.py')) 'no restore may be attempted'
}

Test-Case 'L3 restore: never bypasses a PR24C guard and never targets production' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepBackup -Reason 'seed' | Out-Null
        $script:RecordedCalls = @()
        Invoke-MepRestoreRehearsal | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    $restore = @($calls -match 'restore_postgres\.py')[0]
    Assert-True ($restore -notlike '*--force-non-empty-target*') 'the empty-target guard must not be bypassed'
    Assert-True ($restore -like '*--target-environment local-staging-rehearsal*') 'the rehearsal target must not be labelled production'
    Assert-True ($restore -notlike '*production*') 'no production target may be requested'
    Assert-True ($restore -notlike '*--source-database-url*') 'the same-source guard uses the manifest, not an optional flag'
}

Test-Case 'L3 restore: never destroys volumes or the whole project' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepBackup -Reason 'seed' | Out-Null
        $script:RecordedCalls = @()
        Invoke-MepRestoreRehearsal | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    foreach ($c in $calls) {
        Assert-True ($c -notmatch '(^|\s)down(\s|$)') "rehearsal must never run compose down (saw: $c)"
        Assert-True ($c -notmatch '--volumes') "rehearsal must never remove volumes (saw: $c)"
        Assert-True ($c -notmatch 'volume rm') "rehearsal must never remove a docker volume (saw: $c)"
    }
}

Test-Case 'L3 restore: a failed PR24C restore fails closed' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'restore_postgres.py'; ExitCode = 1; Output = @('[restore] FAIL: checksum mismatch') }
    )
    $result = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepBackup -Reason 'seed' | Out-Null
        $threw = $false
        try { Invoke-MepRestoreRehearsal | Out-Null } catch { $threw = $true }
        return [pscustomobject]@{ Threw = $threw; Calls = @($script:RecordedCalls | ForEach-Object { $_.Args }) }
    }
    Assert-True $result.Threw 'a failed restore rehearsal must fail, never PASS'
    Assert-True (@($result.Calls -match 'DROP DATABASE IF EXISTS mep_local_restore_rehearsal_').Count -gt 0) `
        'the disposable target is still cleaned up after a failure'
}

Test-Case 'L3 update gate: backup failure blocks stop, migration, start and metadata' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'backup_postgres.py'; ExitCode = 1; Output = @('[backup] FAIL') },
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                (New-ContainerJson -Service 'postgres'),
                (New-ContainerJson -Service 'backend'),
                (New-ContainerJson -Service 'frontend')) }
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
    Assert-True $result.Threw 'a failed pre-update backup must fail the update'
    Assert-True (-not ($result.Calls -match 'stop backend frontend')) 'the healthy application must NOT be stopped after a failed backup'
    Assert-True (-not ($result.Calls -match 'deploy_migrate\.py')) 'no migration may run without a verified backup'
    Assert-True (-not $result.MetadataWritten) 'no metadata may be written'
}

Test-Case 'L3 update gate: stopped deployment still backs up before migrating, without starting the backend' {
    $ctx = New-MockContext -EnvFileExists $true -InstallCompleted $true -ExitCodeRules @(
        @{ Match = 'ps --all --filter'; ExitCode = 0; Output = @(
                (New-ContainerJson -Service 'postgres' -State 'exited'),
                (New-ContainerJson -Service 'backend' -State 'exited'),
                (New-ContainerJson -Service 'frontend' -State 'exited')) }
    )
    $calls = Invoke-WithMocks -Context $ctx -Body {
        Invoke-MepUpdate | Out-Null
        return @($script:RecordedCalls | ForEach-Object { $_.Args })
    }
    $pg = Get-CallIndex -Calls $calls -Pattern "up -d --wait .*postgres"
    $backup = Get-CallIndex -Calls $calls -Pattern 'backup_postgres\.py'
    $migrate = Get-CallIndex -Calls $calls -Pattern 'deploy_migrate\.py'
    $startApp = Get-CallIndex -Calls $calls -Pattern "up -d --wait .*backend frontend"
    Assert-True ($pg -ge 0 -and $pg -lt $backup) 'PostgreSQL is made available before the backup'
    Assert-True ($backup -lt $migrate) 'the backup precedes the migration'
    Assert-True ($startApp -gt $backup) 'the backend is not started merely to take the backup'
}

Test-Case 'L3 update gate: -AcknowledgeUpdateRisk bypass no longer exists' {
    $updateScript = Get-Content -LiteralPath (Join-Path $script:DeploymentRootForTests 'update.ps1') -Raw
    Assert-True ($updateScript -notmatch '\[switch\]\$AcknowledgeUpdateRisk') `
        'the risk-acknowledgement bypass must be gone now that a backup is mandatory'
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
