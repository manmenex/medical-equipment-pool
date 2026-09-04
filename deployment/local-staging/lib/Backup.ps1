<#
.SYNOPSIS
PR24D-L3: local Staging/UAT backup and restore-rehearsal orchestration.

.DESCRIPTION
THIS FILE CONTAINS NO BACKUP ENGINE. PowerShell here is an orchestration
layer only: every backup, restore, verification and retention decision is
made by the existing PR24C tooling, invoked unchanged --

    backend/scripts/backup_postgres.py   pg_dump --format=custom, manifest,
                                         SHA-256 checksum, Alembic revision
    backend/scripts/restore_postgres.py  checksum -> manifest identity ->
                                         production-target guard ->
                                         same-source guard -> empty-target
                                         guard -> pg_restore -> Alembic
                                         verification -> row counts
    backend/scripts/prune_backups.py     30-day retention, newest always kept

There is deliberately no pg_dump/pg_restore invocation, no manifest
format, no checksum implementation and no retention logic in this file.
If any of those appear here in future, the duplication is the bug.

CREDENTIAL TRANSPORT: no credential-bearing URL is ever placed on a
command line. The backup runs inside the backend service container, which
already carries DATABASE_URL in its own environment, so PR24C's
--database-url default ($DATABASE_URL) resolves inside the container with
nothing passed by us. The restore rehearsal target URL is handed over as
$RESTORE_TARGET_DATABASE_URL through `docker compose run -e VAR` (the
name-only form, which copies the value from this process's environment
rather than placing it in argv), and that environment entry is removed
again in a finally block.

NETWORK: PostgreSQL is never published to the host or the LAN for backup.
Everything runs inside the Compose network, preserving PR24D-L1's
network architecture exactly.
#>

Set-StrictMode -Version Latest

function Get-MepBackupRoot {
    <#
    .SYNOPSIS
    Returns the local backup root, creating it if absent.
    #>
    if (-not (Test-Path -LiteralPath $Script:BackupRoot)) {
        New-Item -ItemType Directory -Path $Script:BackupRoot -Force | Out-Null
    }
    return (Resolve-Path -LiteralPath $Script:BackupRoot).Path
}

function Get-MepLatestBackup {
    <#
    .SYNOPSIS
    Returns the newest backup archive that has a manifest beside it, or
    $null. Selection is by PR24C's own filename timestamp, not by
    filesystem mtime, so a copied/restored file cannot masquerade as
    newer than it is.
    #>
    $root = Get-MepBackupRoot
    $candidates = @(Get-ChildItem -LiteralPath $root -Filter 'mep-postgres-*.dump' -File -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath "$($_.FullName).manifest.json" } |
            Sort-Object -Property Name -Descending)
    if ($candidates.Count -eq 0) { return $null }
    return $candidates[0]
}

function Test-MepPathIsDirectlyInside {
    <#
    .SYNOPSIS
    True when $Path is a file sitting DIRECTLY in $Directory. Compares
    fully-resolved paths so a relative path, a trailing separator or a
    different casing cannot make an outside file look like an inside one.
    #>
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Directory
    )
    $parent = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($Path))
    $target = [System.IO.Path]::GetFullPath($Directory).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $parent = "$parent".TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $comparison = if ($IsWindows -or $null -eq $IsWindows) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
    return [string]::Equals($parent, $target, $comparison)
}

function Invoke-MepBackup {
    <#
    .SYNOPSIS
    Creates one verified local backup through PR24C's engine, then prunes
    to the 30-day retention window. Returns the archive FileInfo.

    .DESCRIPTION
    The caller MUST already hold the deployment mutation lock. This
    function never acquires it: update.ps1 owns the lock for the whole
    update, and backup.ps1 owns it for a standalone backup. Acquiring it
    again here would be a recursive acquisition on a mutex whose
    re-entrancy we have not proven, so the lock stays strictly at the
    entry-script boundary (PR24D-L3 §22).

    Fails closed on: PostgreSQL unavailable, PR24C backup command
    failure, missing archive, missing manifest, or checksum mismatch. No
    integrity failure is ever downgraded to a warning.

    .PARAMETER Reason
    Free-text label for the installer log only (e.g. 'manual',
    'pre-update'). Never a secret, never part of a filename.
    #>
    param(
        [string]$Reason = 'manual'
    )

    # PostgreSQL availability is a hard precondition, exactly as it is for
    # migration: pg_dump cannot dump a database it cannot reach. This
    # reuses the same health-gated step the installer already owns.
    Start-MepPostgres

    $backupRoot = Get-MepBackupRoot
    Write-Host 'Creating database backup...'
    Write-InstallLog -Phase 'backup' -Message "Backup started (reason=$Reason, root=$backupRoot)."

    $startedAt = [DateTime]::UtcNow
    # --no-deps: PostgreSQL was just converged above; this must not drag
    # the application up as a side effect. DATABASE_URL is NOT passed --
    # it is already present inside the backend container's environment,
    # so no credential crosses the command line.
    $result = Invoke-DockerCompose -Arguments @(
        'run', '--rm', '--no-deps',
        '--name', 'mep-local-staging-backup',
        '-v', "${backupRoot}:/mep-backups",
        'backend',
        'python', 'scripts/backup_postgres.py',
        '--environment', $Script:BackupEnvironmentLabel,
        '--output-dir', '/mep-backups'
    ) -AllowNonZeroExit -Phase 'backup'
    $elapsed = [DateTime]::UtcNow - $startedAt

    foreach ($line in @($result.Output)) { Write-Host $line }
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure "Database backup FAILED (exit code $($result.ExitCode)). Nothing downstream of this step has run.`nACTION: Resolve the error above and retry. Do not proceed with an update until a backup succeeds.")
    }

    # PR24C writes the manifest only after a successful dump, so a missing
    # archive or manifest here means the evidence is incomplete -- treated
    # as a hard failure, never as "probably fine".
    $archive = Get-MepLatestBackup
    if ($null -eq $archive) {
        throw (New-MepFailure "Backup reported success but no backup archive with a manifest was found in $backupRoot. Refusing to treat this as a successful backup.")
    }
    $manifestPath = "$($archive.FullName).manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw (New-MepFailure "Backup archive $($archive.Name) has no manifest beside it. Refusing to treat this as a successful backup.")
    }

    # Independent checksum verification: PR24C records the SHA-256 in the
    # manifest, and we re-hash the archive on the host. This catches a
    # truncated or corrupted transfer between the container and the host
    # bind mount, which the in-container run could not have seen.
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $actual = (Get-FileHash -LiteralPath $archive.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $expected = "$($manifest.checksum_sha256)".ToLowerInvariant()
    if ($actual -ne $expected) {
        throw (New-MepFailure "Backup checksum verification FAILED for $($archive.Name): the manifest records $expected but the archive on disk hashes to $actual. Refusing to report a successful backup.")
    }

    Write-Host ''
    Write-Host 'Backup completed' -ForegroundColor Green
    Write-Host "  Archive:  $($archive.FullName)"
    Write-Host "  Manifest: $manifestPath"
    Write-Host "  Created:  $($manifest.created_at)"
    Write-Host "  Elapsed:  $([Math]::Round($elapsed.TotalSeconds, 1)) seconds"
    Write-Host '  Checksum verification: PASS' -ForegroundColor Green
    Write-InstallLog -Phase 'backup' -Message "Backup OK (archive=$($archive.Name), elapsed_seconds=$([Math]::Round($elapsed.TotalSeconds,1)), checksum=PASS)."

    Invoke-MepBackupRetention

    return $archive
}

function Invoke-MepBackupRetention {
    <#
    .SYNOPSIS
    Applies the Owner-approved 30-day retention window using PR24C's own
    prune tooling. The retention period is PR24C's DEFAULT_RETENTION_DAYS
    -- this wrapper deliberately does NOT pass --retention-days, so the
    local deployment cannot drift to a different policy.
    #>
    $backupRoot = Get-MepBackupRoot
    $result = Invoke-DockerCompose -Arguments @(
        'run', '--rm', '--no-deps',
        '--name', 'mep-local-staging-prune',
        '-v', "${backupRoot}:/mep-backups",
        'backend',
        'python', 'scripts/prune_backups.py',
        '--backup-dir', '/mep-backups'
    ) -AllowNonZeroExit -Phase 'prune'
    foreach ($line in @($result.Output)) { Write-Host $line }
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure "Backup retention pruning failed (exit code $($result.ExitCode)). The backup itself succeeded and is safe, but retention did not run.`nACTION: Investigate the error above; old backups may still be present.")
    }
    Write-InstallLog -Phase 'prune' -Message 'Backup retention pruning completed.'
}

function New-MepRehearsalDatabaseName {
    <#
    .SYNOPSIS
    A deterministic, timestamped, disposable database name that can never
    collide with the live local Staging/UAT database.
    #>
    return "$($Script:RehearsalDatabasePrefix)$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
}

function Invoke-MepPsql {
    <#
    .SYNOPSIS
    Runs one SQL statement against the local PostgreSQL server's
    maintenance database, inside the Compose network.

    .DESCRIPTION
    Used only to CREATE and DROP the disposable rehearsal database.
    Credentials never appear on a command line: psql reads PGPASSWORD and
    PGUSER from the postgres container's own environment, which Compose
    populated from .env.
    #>
    param(
        [Parameter(Mandatory)] [string]$Sql,
        [switch]$AllowNonZeroExit
    )
    return Invoke-DockerCompose -Arguments @(
        'exec', '-T', 'postgres',
        'sh', '-c',
        "psql -v ON_ERROR_STOP=1 -U `"`$POSTGRES_USER`" -d postgres -c `"$Sql`""
    ) -AllowNonZeroExit:$AllowNonZeroExit -Phase 'psql'
}

function Invoke-MepRestoreRehearsal {
    <#
    .SYNOPSIS
    Restores a backup into a fresh DISPOSABLE database and verifies it,
    entirely through PR24C's restore tooling. Never touches the live
    local Staging/UAT database.

    .DESCRIPTION
    EVIDENCE CLASS: LOCAL REHEARSAL. A PASS here proves the local backup
    is restorable and internally consistent. It does NOT satisfy the
    managed-Staging restore rehearsal required before Production GO --
    that remains PENDING regardless of this result.

    Safety ordering is PR24C's, unchanged and not reordered: checksum ->
    manifest-derived source identity -> production-target guard ->
    same-source guard -> empty-target guard -> pg_restore -> Alembic
    revision verification -> representative row counts. This wrapper adds
    no --force flag, no production override, and no way to skip a guard.

    The caller MUST already hold the deployment mutation lock.

    .PARAMETER BackupFile
    Archive to rehearse. Defaults to the newest backup that has a manifest.
    Any readable path is accepted, including one outside the backup root
    (an archive copied back from another machine), but the artifact that
    reaches PR24C is always the one named here: an external archive is
    staged with its manifest under a collision-safe path inside the mount
    rather than being addressed by name. An archive with no manifest
    beside it is refused, because PR24C derives both the expected checksum
    and the source identity of its same-source guard from that manifest.

    .PARAMETER KeepRehearsalDatabase
    Leaves the disposable database in place for investigation instead of
    dropping it. The drop is otherwise scoped to exactly the database this
    function created -- never a volume, never `down -v`.
    #>
    param(
        [string]$BackupFile,
        [switch]$KeepRehearsalDatabase
    )

    Start-MepPostgres

    $backupRoot = Get-MepBackupRoot
    if ([string]::IsNullOrWhiteSpace($BackupFile)) {
        $archive = Get-MepLatestBackup
        if ($null -eq $archive) {
            throw (New-MepFailure "No backup found in $backupRoot. Run .\backup.ps1 first.")
        }
    }
    else {
        if (-not (Test-Path -LiteralPath $BackupFile)) {
            throw (New-MepFailure "Backup file not found: $BackupFile")
        }
        $archive = Get-Item -LiteralPath $BackupFile
    }

    # Fix Round 1 (P1): bind the container path to the EXACT artifact the
    # operator selected.
    #
    # Only $Script:BackupRoot is mounted at /mep-backups, so passing just
    # the file's NAME was wrong for any archive outside that directory: it
    # would either not exist in the container, or -- far worse -- silently
    # resolve to a DIFFERENT, same-named archive inside the backup root and
    # report a rehearsal PASS for an artifact the operator never chose.
    #
    # An archive already inside the backup root is addressed directly. One
    # from anywhere else (an external drive, a copy kept off-machine) is
    # staged, together with its manifest, into a per-run directory whose
    # GUID name cannot collide with an existing backup. The staged copy is
    # removed in the finally block below.
    $manifestSource = "$($archive.FullName).manifest.json"
    if (-not (Test-Path -LiteralPath $manifestSource)) {
        throw (New-MepFailure "Backup archive $($archive.Name) has no manifest beside it ($manifestSource). PR24C's restore derives source identity and the expected checksum from that manifest, so it cannot be verified without it.")
    }

    $stagingDirectory = $null
    if (Test-MepPathIsDirectlyInside -Path $archive.FullName -Directory $backupRoot) {
        $containerBackupPath = "/mep-backups/$($archive.Name)"
    }
    else {
        $stagingName = ".restore-staging-$([Guid]::NewGuid().ToString('N'))"
        $stagingDirectory = Join-Path $backupRoot $stagingName
        New-Item -ItemType Directory -Path $stagingDirectory -Force | Out-Null
        Copy-Item -LiteralPath $archive.FullName -Destination (Join-Path $stagingDirectory $archive.Name) -Force
        Copy-Item -LiteralPath $manifestSource -Destination (Join-Path $stagingDirectory "$($archive.Name).manifest.json") -Force
        # A subdirectory is invisible to Get-MepLatestBackup (non-recursive)
        # and to PR24C's prune (files directly inside the root only), so
        # staging cannot disturb the real backup set.
        $containerBackupPath = "/mep-backups/$stagingName/$($archive.Name)"
        Write-Host "  Staged external archive for rehearsal: $($archive.FullName)"
        Write-InstallLog -Phase 'restore-rehearsal' -Message "External archive staged under $stagingName for rehearsal."
    }

    $rehearsalDb = New-MepRehearsalDatabaseName
    # Belt and braces: the generated name is timestamped and prefixed, but
    # an explicit check makes the "never the live database" property
    # impossible to lose to a future edit.
    $liveDb = Get-MepConfiguredValue -Name 'POSTGRES_DB'
    if ($rehearsalDb -eq $liveDb) {
        throw (New-MepFailure 'Refusing to rehearse: the generated rehearsal database name equals the live database name.')
    }

    Write-Host ''
    Write-Host 'Restore rehearsal (LOCAL REHEARSAL evidence class)' -ForegroundColor Cyan
    Write-Host "  Backup:            $($archive.Name)"
    Write-Host "  Disposable target: $rehearsalDb"
    Write-Host '  The live local Staging/UAT database is NOT modified.'
    Write-Host ''
    Write-InstallLog -Phase 'restore-rehearsal' -Message "Restore rehearsal started (archive=$($archive.Name), target=$rehearsalDb)."

    $created = $false
    $startedAt = [DateTime]::UtcNow
    try {
        Invoke-MepPsql -Sql "CREATE DATABASE $rehearsalDb" | Out-Null
        $created = $true

        $user = Get-MepConfiguredValue -Name 'POSTGRES_USER'
        $password = Get-MepConfiguredValue -Name 'POSTGRES_PASSWORD'
        # Credential transport: the URL is set in THIS process's
        # environment and passed by NAME only, so its value never appears
        # in argv. It is removed again in the finally block below.
        $env:RESTORE_TARGET_DATABASE_URL = "postgresql+asyncpg://${user}:${password}@postgres:5432/$rehearsalDb"
        try {
            $result = Invoke-DockerCompose -Arguments @(
                'run', '--rm', '--no-deps',
                '--name', 'mep-local-staging-restore-rehearsal',
                '-e', 'RESTORE_TARGET_DATABASE_URL',
                '-v', "${backupRoot}:/mep-backups",
                'backend',
                'python', 'scripts/restore_postgres.py',
                '--backup-file', $containerBackupPath,
                '--target-environment', 'local-staging-rehearsal'
            ) -AllowNonZeroExit -Phase 'restore-rehearsal'
        }
        finally {
            # Assigning $null removes the variable from the environment;
            # the credential's lifetime is exactly this one command.
            $env:RESTORE_TARGET_DATABASE_URL = $null
        }

        $elapsed = [DateTime]::UtcNow - $startedAt
        foreach ($line in @($result.Output)) { Write-Host $line }
        if ($result.ExitCode -ne 0) {
            throw (New-MepFailure "Restore rehearsal FAILED (exit code $($result.ExitCode)). The backup could not be restored and verified. Treat this backup as unusable until investigated.")
        }

        Write-Host ''
        Write-Host 'Restore rehearsal: PASS' -ForegroundColor Green
        Write-Host "  Elapsed: $([Math]::Round($elapsed.TotalSeconds, 1)) seconds"
        Write-Host '  Evidence class: LOCAL REHEARSAL' -ForegroundColor Yellow
        Write-Host '  This does NOT satisfy the managed-Staging restore rehearsal required before Production GO.' -ForegroundColor Yellow
        Write-InstallLog -Phase 'restore-rehearsal' -Message "Restore rehearsal PASS (elapsed_seconds=$([Math]::Round($elapsed.TotalSeconds,1)), evidence_class=LOCAL REHEARSAL)."
        return $result
    }
    finally {
        if ($stagingDirectory -and (Test-Path -LiteralPath $stagingDirectory)) {
            # Scoped to exactly the per-run staging directory this function
            # created -- never the backup root itself, never a volume.
            Remove-Item -LiteralPath $stagingDirectory -Recurse -Force -ErrorAction SilentlyContinue
        }
        if ($created -and -not $KeepRehearsalDatabase) {
            # Scoped precisely to the database this function created. Never
            # a volume removal, never `down -v`, never the live database.
            $drop = Invoke-MepPsql -Sql "DROP DATABASE IF EXISTS $rehearsalDb" -AllowNonZeroExit
            if ($drop.ExitCode -ne 0) {
                Write-Host "WARNING: could not drop the disposable rehearsal database '$rehearsalDb'. Drop it manually." -ForegroundColor Yellow
                Write-InstallLog -Phase 'restore-rehearsal' -Level 'WARN' -Message "Failed to drop rehearsal database $rehearsalDb."
            }
            else {
                Write-InstallLog -Phase 'restore-rehearsal' -Message "Disposable rehearsal database $rehearsalDb dropped."
            }
        }
        elseif ($created) {
            Write-Host "Rehearsal database '$rehearsalDb' was kept for investigation. Drop it when finished." -ForegroundColor Yellow
        }
    }
}
