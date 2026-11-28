<#
.SYNOPSIS
PR25A: off-host backup to Google Drive -- orchestration only.

.DESCRIPTION
THIS FILE CONTAINS NO UPLOAD ENGINE. The OAuth device flow, Drive calls,
pending-upload queue and Drive retention all live in
backend/scripts/drive_backup_lib.py and are exercised by pytest with mocked
HTTP. PowerShell here only runs that tool inside the backend container, with
two bind mounts:

    <backups>   -> /mep-backups         (the same directory backup.ps1 fills)
    <secrets>   -> /mep-drive-secrets   (OAuth client + refresh token)

SECRETS. The refresh token lives in deployment/local-staging/secrets/
drive-oauth.json (gitignored). It is never printed, logged or placed on a
command line: the OAuth client ID/secret typed at setup travel in this
process's environment and are passed to Compose by NAME only (the same
transport the restore rehearsal uses for its target URL), then cleared in a
finally block. The secrets directory gets an owner-only ACL (icacls on
Windows, chmod 700 elsewhere).

FAILURE POLICY. Invoke-MepDriveUpload NEVER throws and never touches a
local backup. A failed or skipped upload is logged as a warning and retried
automatically by the next run (the tool derives its pending queue from what
is on disk). Drive being down must not turn a good local backup into a
failed one -- the local archive is the primary copy.
#>

Set-StrictMode -Version Latest

$Script:DriveSecretsRoot = Join-Path $Script:DeploymentRoot 'secrets'
$Script:DriveSecretsFileName = 'drive-oauth.json'
$Script:DriveContainerBackups = '/mep-backups'
$Script:DriveContainerSecrets = '/mep-drive-secrets'

function Get-MepDriveSecretsRoot {
    return $Script:DriveSecretsRoot
}

function Test-MepDriveConfigured {
    <#
    .SYNOPSIS
    True when the secret file exists. Deliberately checks existence only --
    the file's contents are never read by PowerShell.
    #>
    return (Test-Path -LiteralPath (Join-Path (Get-MepDriveSecretsRoot) $Script:DriveSecretsFileName))
}

function Protect-MepDriveSecretsRoot {
    <#
    .SYNOPSIS
    Creates the secrets directory and restricts it to the current user,
    SYSTEM and Administrators. Fails closed: if permissions cannot be
    restricted, setup stops rather than leaving a token world-readable.
    #>
    $root = Get-MepDriveSecretsRoot
    if (-not (Test-Path -LiteralPath $root)) {
        New-Item -ItemType Directory -Path $root -Force | Out-Null
    }
    if ($IsWindows -or $null -eq $IsWindows) {
        $me = "$env:USERDOMAIN\$env:USERNAME"
        Invoke-MepCommand -FilePath 'icacls' -Phase 'drive-secrets-acl' -Arguments @(
            $root, '/inheritance:r',
            '/grant:r', "${me}:(OI)(CI)F",
            '/grant:r', 'SYSTEM:(OI)(CI)F',
            '/grant:r', 'BUILTIN\Administrators:(OI)(CI)F'
        ) | Out-Null
    }
    else {
        Invoke-MepCommand -FilePath 'chmod' -Arguments @('700', $root) -Phase 'drive-secrets-acl' | Out-Null
    }
}

function Invoke-MepDriveTool {
    <#
    .SYNOPSIS
    Runs backend/scripts/drive_backup.py <Subcommand> in the backend
    container with the backup and secrets directories mounted.

    .PARAMETER EnvNames
    Names (never values) of environment variables to hand to the container
    from this process's environment.
    #>
    param(
        [Parameter(Mandatory)] [string[]]$Subcommand,
        [string[]]$EnvNames = @(),
        [switch]$NoCapture,
        [string]$Phase = 'drive'
    )
    $backupRoot = Get-MepBackupRoot
    $secretsRoot = Get-MepDriveSecretsRoot
    $envArgs = @()
    foreach ($name in $EnvNames) { $envArgs += @('-e', $name) }
    # No --name: a fixed container name left behind by a killed run would
    # wedge every later run ("name already in use"). -T: no TTY under Task
    # Scheduler; the interactive setup passes -NoCapture instead.
    $tty = if ($NoCapture) { @() } else { @('-T') }
    return Invoke-DockerCompose -Arguments (@(
            'run', '--rm', '--no-deps') + $tty + $envArgs + @(
            '-v', "${backupRoot}:$Script:DriveContainerBackups",
            '-v', "${secretsRoot}:$Script:DriveContainerSecrets",
            'backend',
            'python', 'scripts/drive_backup.py',
            '--backup-dir', $Script:DriveContainerBackups,
            '--secrets-file', "$Script:DriveContainerSecrets/$Script:DriveSecretsFileName"
        ) + $Subcommand) -AllowNonZeroExit -NoCapture:$NoCapture -Phase $Phase
}

function Invoke-MepDriveUpload {
    <#
    .SYNOPSIS
    Uploads pending backups to Drive. NEVER throws; returns $true only when
    Drive is fully up to date. The caller's exit code must not depend on it.
    #>
    try {
        if (-not (Test-MepDriveConfigured)) {
            Write-Host 'Drive upload: not configured (run .\drive-backup.ps1 -Setup). This backup exists ONLY on this PC.' -ForegroundColor Yellow
            Write-InstallLog -Phase 'drive-upload' -Level 'WARN' -Message 'Drive upload skipped: not configured.'
            return $false
        }
        $result = Invoke-MepDriveTool -Subcommand @('upload') -Phase 'drive-upload'
        foreach ($line in @($result.Output)) { Write-Host $line }
        if ($result.ExitCode -eq 4) {
            Write-Host 'Drive upload skipped: another upload running. The local backup is safe; the next run uploads it.' -ForegroundColor Yellow
            Write-InstallLog -Phase 'drive-upload' -Level 'WARN' -Message 'Drive upload skipped: another upload running; queued for the next run.'
            return $false
        }
        if ($result.ExitCode -ne 0) {
            Write-Host 'WARNING: Drive upload did not complete. The local backup is safe; the upload is queued and retries on the next run.' -ForegroundColor Yellow
            Write-InstallLog -Phase 'drive-upload' -Level 'WARN' -Message "Drive upload incomplete (exit code $($result.ExitCode)); queued for the next run. Run .\drive-backup.ps1 -Status."
            return $false
        }
        Write-InstallLog -Phase 'drive-upload' -Message 'Drive upload OK.'
        return $true
    }
    catch {
        Write-Host 'WARNING: Drive upload could not run. The local backup is safe; the upload is queued and retries on the next run.' -ForegroundColor Yellow
        Write-InstallLog -Phase 'drive-upload' -Level 'WARN' -Message "Drive upload could not run: $($_.Exception.Message)"
        return $false
    }
}

function Invoke-MepDriveSetup {
    <#
    .SYNOPSIS
    One-time OAuth consent (device flow). Prompts for the OAuth client ID
    and secret only when no secret file exists yet (or -ReplaceCredentials).
    #>
    param(
        [switch]$ReplaceCredentials,
        [string]$ClientId,
        [securestring]$ClientSecret
    )
    Protect-MepDriveSecretsRoot
    $needCredentials = $ReplaceCredentials -or -not (Test-MepDriveConfigured)
    $envNames = @()
    try {
        if ($needCredentials) {
            if ([string]::IsNullOrWhiteSpace($ClientId)) { $ClientId = Read-Host 'OAuth client ID (type "TVs and Limited Input devices")' }
            if ($null -eq $ClientSecret) { $ClientSecret = Read-Host 'OAuth client secret' -AsSecureString }
            $env:MEP_DRIVE_CLIENT_ID = $ClientId.Trim()
            $env:MEP_DRIVE_CLIENT_SECRET = [System.Net.NetworkCredential]::new('', $ClientSecret).Password.Trim()
            $envNames = @('MEP_DRIVE_CLIENT_ID', 'MEP_DRIVE_CLIENT_SECRET')
        }
        # -NoCapture: the verification URL and code must appear LIVE while
        # the tool waits for approval, and nothing it prints is secret.
        $result = Invoke-MepDriveTool -Subcommand @('setup') -EnvNames $envNames -NoCapture -Phase 'drive-setup'
    }
    finally {
        $env:MEP_DRIVE_CLIENT_ID = $null
        $env:MEP_DRIVE_CLIENT_SECRET = $null
    }
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure "Drive setup failed (exit code $($result.ExitCode)). Nothing was saved.`nACTION: Read the message above and rerun .\drive-backup.ps1 -Setup.")
    }
    Protect-MepDriveSecretsRoot
    Write-InstallLog -Phase 'drive-setup' -Message 'Drive backup configured.'
}

function Show-MepDriveStatus {
    <#
    .SYNOPSIS
    Last local backup, last upload, pending count, last error. Returns
    $true when healthy.
    #>
    $result = Invoke-MepDriveTool -Subcommand @('status') -Phase 'drive-status'
    foreach ($line in @($result.Output)) { Write-Host $line }
    return ($result.ExitCode -eq 0)
}

function Show-MepDriveBackups {
    $result = Invoke-MepDriveTool -Subcommand @('list') -Phase 'drive-list'
    foreach ($line in @($result.Output)) { Write-Host $line }
    return ($result.ExitCode -eq 0)
}

function Resolve-MepDownloadedBackup {
    <#
    .SYNOPSIS
    Maps the tool's '[drive] OK: /mep-backups/<file>' line to the host file.
    Fails closed exactly like Resolve-MepProducedBackup: one line, directly
    inside the mount, PR24C's filename form, present on the host WITH its
    manifest.
    #>
    param(
        [Parameter(Mandatory)] [AllowEmptyCollection()] [AllowNull()] $Output,
        [Parameter(Mandatory)] [string]$BackupRoot
    )
    $reported = @()
    foreach ($line in @($Output)) {
        $m = [regex]::Match("$line", '^\s*\[drive\]\s+OK:\s+/mep-backups/(mep-postgres-[a-z0-9]+-\d{8}T\d{6}Z\.dump)\s*$')
        if ($m.Success) { $reported += $m.Groups[1].Value }
    }
    $distinct = @($reported | Select-Object -Unique)
    if ($distinct.Count -ne 1) {
        throw (New-MepFailure "The Drive download did not report exactly one backup file ($($distinct.Count) reported). Refusing to guess which file to restore.")
    }
    $hostPath = Join-Path $BackupRoot $distinct[0]
    if (-not (Test-Path -LiteralPath $hostPath) -or -not (Test-Path -LiteralPath "$hostPath.manifest.json")) {
        throw (New-MepFailure "The Drive download reported $($distinct[0]) but it (or its manifest) is not present in $BackupRoot.")
    }
    return (Get-Item -LiteralPath $hostPath)
}

function Invoke-MepRestoreFromDrive {
    <#
    .SYNOPSIS
    Downloads a backup from Drive into the local backup root (checksum
    verified against its manifest) and hands it to the EXISTING restore
    tooling (Invoke-MepRestoreRehearsal -> PR24C restore_postgres.py).

    .DESCRIPTION
    Adds no restore logic and bypasses no PR24C guard. Like restore.ps1 it
    restores into a disposable verification database, never over the live
    one; promoting a verified copy to live is the runbook's Owner-supervised
    procedure (docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md section 12).
    The caller must already hold the deployment mutation lock.

    .PARAMETER Name
    Exact dump filename from -ListOnly. Default: the newest on Drive.
    #>
    param(
        [string]$Name,
        [switch]$KeepRehearsalDatabase
    )
    if (-not (Test-MepDriveConfigured)) {
        throw (New-MepFailure "Drive is not set up on this PC.`nACTION: Run .\drive-backup.ps1 -Setup first (same OAuth client, consent as the department Google account).")
    }
    if ($Name -and $Name -cnotmatch '^mep-postgres-[a-z0-9]+-\d{8}T\d{6}Z\.dump$') {
        throw (New-MepFailure "'$Name' is not a backup filename (expected mep-postgres-<env>-<UTC timestamp>.dump).")
    }
    $selector = if ($Name) { @('--name', $Name) } else { @('--latest') }
    Write-Host 'Downloading backup from Google Drive...'
    $result = Invoke-MepDriveTool -Subcommand (@('download') + $selector) -Phase 'drive-download'
    foreach ($line in @($result.Output)) { Write-Host $line }
    if ($result.ExitCode -ne 0) {
        throw (New-MepFailure "Drive download FAILED (exit code $($result.ExitCode)). Nothing was restored.")
    }
    $archive = Resolve-MepDownloadedBackup -Output $result.Output -BackupRoot (Get-MepBackupRoot)
    Write-InstallLog -Phase 'drive-download' -Message "Downloaded $($archive.Name) from Drive; handing to the restore tooling."
    return (Invoke-MepRestoreRehearsal -BackupFile $archive.FullName -KeepRehearsalDatabase:$KeepRehearsalDatabase)
}
