<#
.SYNOPSIS
DEMO-ONLY legacy pool sheet shadow sync -- orchestration only
(Governance 2026-10-21, docs/DECISION_LOG.md).

.DESCRIPTION
No sync logic lives here. The engine is
backend/app/services/legacy_sheet_sync (python -m app.services.legacy_sheet_sync),
which runs in the `legacy-sheet-sync` compose profile service. PowerShell only
places/removes the service-account key, flips the .env switch and starts/stops
the service.

SECRETS. The key file is copied to deployment/local-staging/secrets/
legacy-sheet/key.json (gitignored, owner-only ACL) and mounted read-only into
that one container. Its contents are never read into PowerShell output and its
path is never written to the install log. -Disable deletes it.
#>

Set-StrictMode -Version Latest

$Script:LegacySyncDir = Join-Path (Join-Path $Script:DeploymentRoot 'secrets') 'legacy-sheet'
$Script:LegacySyncKeyPath = Join-Path $Script:LegacySyncDir 'key.json'
$Script:LegacySyncService = 'legacy-sheet-sync'
$Script:LegacySyncModule = 'app.services.legacy_sheet_sync'

function Set-MepEnvValue {
    <# Sets or appends NAME=value in the generated .env, preserving other lines. #>
    param([Parameter(Mandatory)] [string]$Name, [Parameter(Mandatory)] [AllowEmptyString()] [string]$Value)
    $lines = @()
    if (Test-Path -LiteralPath $Script:EnvFilePath) { $lines = @(Get-Content -LiteralPath $Script:EnvFilePath) }
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=") { $found = $true; "$Name=$Value" } else { $line }
    }
    if (-not $found) { $out = @($out) + "$Name=$Value" }
    Set-Content -LiteralPath $Script:EnvFilePath -Value $out
}

function Protect-MepLegacySyncDir {
    <# Creates the key directory and restricts it (fails closed). #>
    if (-not (Test-Path -LiteralPath $Script:LegacySyncDir)) {
        New-Item -ItemType Directory -Path $Script:LegacySyncDir -Force | Out-Null
    }
    if ($IsWindows -or $null -eq $IsWindows) {
        $me = "$env:USERDOMAIN\$env:USERNAME"
        Invoke-MepCommand -FilePath 'icacls' -Phase 'legacy-sync-acl' -Arguments @(
            $Script:LegacySyncDir, '/inheritance:r',
            '/grant:r', "${me}:(OI)(CI)F",
            '/grant:r', 'SYSTEM:(OI)(CI)F',
            '/grant:r', 'BUILTIN\Administrators:(OI)(CI)F'
        ) | Out-Null
    }
    else {
        Invoke-MepCommand -FilePath 'chmod' -Arguments @('700', $Script:LegacySyncDir) -Phase 'legacy-sync-acl' | Out-Null
    }
}

function Test-MepServiceAccountKeyFile {
    <# Returns the service account's e-mail (not a secret) or throws. Never prints key material. #>
    param([Parameter(Mandatory)] [string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'The key file was not found.' }
    try { $json = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json } catch { throw 'The key file is not valid JSON.' }
    if ($json.type -ne 'service_account' -or -not $json.client_email -or -not $json.private_key) {
        throw 'The file is not a Google service-account key.'
    }
    return [string]$json.client_email
}

function Invoke-MepLegacySyncRun {
    param([string[]]$ModuleArgs, [switch]$NoCapture)
    return Invoke-DockerCompose -Arguments (@('run', '--rm', '--no-deps', '-T', $Script:LegacySyncService, 'python', '-m', $Script:LegacySyncModule) + $ModuleArgs) `
        -AllowNonZeroExit -Phase 'legacy-sync-run' -NoCapture:$NoCapture
}

function Enable-MepLegacySheetSync {
    param(
        [Parameter(Mandatory)] [string]$KeyFile,
        [Parameter(Mandatory)] [string]$SpreadsheetId,
        [string]$StartDate,
        [string]$EmployeeCode = 'LEGACY-SYNC',
        [int]$IntervalSeconds = 300
    )
    $email = Test-MepServiceAccountKeyFile -Path $KeyFile
    Write-Host "Service account: $email" -ForegroundColor Cyan
    Write-Host "Make sure the Google Sheet is shared with this account as VIEWER only." -ForegroundColor Yellow
    Protect-MepLegacySyncDir
    Copy-Item -LiteralPath $KeyFile -Destination $Script:LegacySyncKeyPath -Force
    if (-not ($IsWindows -or $null -eq $IsWindows)) { Invoke-MepCommand -FilePath 'chmod' -Arguments @('600', $Script:LegacySyncKeyPath) -Phase 'legacy-sync-acl' | Out-Null }
    Set-MepEnvValue -Name 'LEGACY_SHEET_SYNC_SPREADSHEET_ID' -Value $SpreadsheetId
    Set-MepEnvValue -Name 'LEGACY_SHEET_SYNC_INTERVAL_SECONDS' -Value "$IntervalSeconds"
    Set-MepEnvValue -Name 'LEGACY_SHEET_SYNC_START_DATE' -Value $StartDate
    Set-MepEnvValue -Name 'LEGACY_SHEET_SYNC_EMPLOYEE_CODE' -Value $EmployeeCode
    Write-InstallLog -Phase 'legacy-sync' -Message 'Legacy sheet sync: key installed, configuration written (values not logged).'

    Write-Host 'Dry run (reads the sheet, writes nothing)...' -ForegroundColor Cyan
    $dry = Invoke-MepLegacySyncRun -ModuleArgs @('--once', '--dry-run')
    foreach ($line in @($dry.Output)) { Write-Host $line }
    if ($dry.ExitCode -ne 0) {
        throw 'Dry run failed; the sync was NOT enabled. Fix the error above (sheet shared? sync user created?) and rerun.'
    }
    Set-MepEnvValue -Name 'LEGACY_SHEET_SYNC_ENABLED' -Value 'true'
    $up = Invoke-DockerCompose -Arguments @('--profile', $Script:LegacySyncService, 'up', '-d', '--build', $Script:LegacySyncService) -AllowNonZeroExit -Phase 'legacy-sync-up'
    if ($up.ExitCode -ne 0) { throw 'Could not start the legacy-sheet-sync service.' }
    Write-InstallLog -Phase 'legacy-sync' -Message 'Legacy sheet sync ENABLED (demo only).'
    Write-Host 'Legacy sheet sync is ON (DEMO ONLY). Switch it off before go-live: .\enable-legacy-sheet-sync.ps1 -Disable' -ForegroundColor Yellow
}

function Disable-MepLegacySheetSync {
    Set-MepEnvValue -Name 'LEGACY_SHEET_SYNC_ENABLED' -Value 'false'
    Invoke-DockerCompose -Arguments @('--profile', $Script:LegacySyncService, 'rm', '-sf', $Script:LegacySyncService) -AllowNonZeroExit -Phase 'legacy-sync-down' | Out-Null
    if (Test-Path -LiteralPath $Script:LegacySyncDir) {
        Remove-Item -LiteralPath $Script:LegacySyncDir -Recurse -Force
    }
    Write-InstallLog -Phase 'legacy-sync' -Message 'Legacy sheet sync DISABLED; key removed from this host.'
    Write-Host 'Legacy sheet sync is OFF and the key file was removed from this host.' -ForegroundColor Green
    Write-Host 'Also remove the service account from the Google Sheet sharing list.' -ForegroundColor Yellow
}

function Show-MepLegacySheetSyncStatus {
    $envMap = Read-EnvFile
    $enabled = $envMap.ContainsKey('LEGACY_SHEET_SYNC_ENABLED') -and $envMap['LEGACY_SHEET_SYNC_ENABLED'] -eq 'true'
    Write-Host ("Enabled in .env : {0}" -f $(if ($enabled) { 'YES (demo only)' } else { 'no' }))
    Write-Host ("Key file present: {0}" -f $(if (Test-Path -LiteralPath $Script:LegacySyncKeyPath) { 'yes' } else { 'no' }))
    $ps = Invoke-DockerCompose -Arguments @('--profile', $Script:LegacySyncService, 'ps', $Script:LegacySyncService) -AllowNonZeroExit -Phase 'legacy-sync-ps'
    foreach ($line in @($ps.Output)) { Write-Host $line }
    $logs = Invoke-DockerCompose -Arguments @('--profile', $Script:LegacySyncService, 'logs', '--tail', '200', $Script:LegacySyncService) -AllowNonZeroExit -Phase 'legacy-sync-logs'
    $lines = @($logs.Output) | Where-Object { $_ -match 'legacy_sheet_sync' } | Select-Object -Last 8
    foreach ($line in $lines) { Write-Host $line }
}
