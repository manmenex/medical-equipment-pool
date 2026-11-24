<#
.SYNOPSIS
DEMO-ONLY: expose the app to the internet through Tailscale Funnel, or turn
that off again.

.DESCRIPTION
Owner decision 2026-11-24 (docs/DECISION_LOG.md). Funnel gives a public HTTPS
URL (https://<host>.<tailnet>.ts.net) with no domain. Tailscale terminates TLS
and forwards to the local web frontend port (LOCAL_STAGING_HTTP_PORT from
.env, default 80). The backend sits behind the frontend's nginx /api/ proxy,
so requests are same-origin: no ALLOWED_ORIGINS, cookie or Host change is
needed and this script never edits .env or restarts containers.

There is NO identity gate in front of the app login (Cloudflare Access is
the production target, Roadmap PR25C). Use strong passwords.

    .\enable-online.ps1            # install/login Tailscale if needed, start Funnel
    .\enable-online.ps1 -Status
    .\enable-online.ps1 -Disable

Funnel runs with --bg, so it persists in the tailscaled service across
start/stop/update scripts and reboots.
#>
[CmdletBinding(DefaultParameterSetName = 'Enable')]
param(
    [Parameter(ParameterSetName = 'Disable', Mandatory)] [switch]$Disable,
    [Parameter(ParameterSetName = 'Status', Mandatory)] [switch]$Status
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/Common.ps1')

function Find-TailscaleExe {
    $cmd = Get-Command 'tailscale.exe' -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $default = 'C:\Program Files\Tailscale\tailscale.exe'
    if (Test-Path -LiteralPath $default) { return $default }
    return $null
}

function Invoke-Tailscale {
    param([Parameter(Mandatory)] [string[]]$Arguments, [switch]$NoCapture)
    Invoke-MepCommand -FilePath $Script:TailscaleExe -Arguments $Arguments -AllowNonZeroExit `
        -NoCapture:$NoCapture -Phase 'tailscale'
}

function Get-TailscaleStatusJson {
    $r = Invoke-Tailscale -Arguments @('status', '--json')
    try { return ($r.Output -join "`n") | ConvertFrom-Json } catch { return $null }
}

function Get-FunnelHostName {
    $s = Get-TailscaleStatusJson
    if ($s -and $s.Self -and $s.Self.DNSName) { return ([string]$s.Self.DNSName).TrimEnd('.') }
    return $null
}

function Get-FunnelAdminUrl {
    param([string[]]$Lines)
    $m = [regex]::Match(($Lines -join "`n"), 'https://login\.tailscale\.com/\S+')
    if ($m.Success) { return $m.Value }
    return $null
}

function Test-FunnelActive {
    $r = Invoke-Tailscale -Arguments @('funnel', 'status')
    return ($r.ExitCode -eq 0 -and (($r.Output -join "`n") -match 'Funnel on'))
}

function Show-FunnelStatus {
    $hostName = Get-FunnelHostName
    $r = Invoke-Tailscale -Arguments @('funnel', 'status')
    $r.Output | ForEach-Object { Write-Host $_ }
    if ((Test-FunnelActive) -and $hostName) {
        Write-Host "สถานะ: เปิดใช้งานจากอินเทอร์เน็ตอยู่ -> https://$hostName" -ForegroundColor Green
    }
    else {
        Write-Host 'สถานะ: ยังไม่เปิดใช้งานจากอินเทอร์เน็ต'
    }
}

Write-Host ''
Write-Host '=== เปิดใช้งานจากนอก รพ. ด้วย Tailscale Funnel (เฉพาะช่วง DEMO) ===' -ForegroundColor Cyan

try {
    $Script:TailscaleExe = Find-TailscaleExe
    if (-not $Script:TailscaleExe) {
        if ($Disable -or $Status) {
            Write-Host 'ไม่พบ Tailscale บนเครื่องนี้ (ยังไม่ได้ติดตั้ง)'
            exit 0
        }
        Write-Host 'ไม่พบ Tailscale บนเครื่องนี้' -ForegroundColor Yellow
        $answer = Read-Host 'ติดตั้งด้วย winget ตอนนี้ (winget install --id Tailscale.Tailscale -e) [y/N]'
        if ($answer -match '^(?i:y|yes)$') {
            Invoke-MepCommand -FilePath 'winget' -Arguments @('install', '--id', 'Tailscale.Tailscale', '-e') -NoCapture -Phase 'tailscale-install' | Out-Null
            $Script:TailscaleExe = Find-TailscaleExe
        }
        if (-not $Script:TailscaleExe) {
            Write-Host 'ดาวน์โหลดและติดตั้งเองได้ที่ https://tailscale.com/download/windows แล้วรันสคริปต์นี้ใหม่' -ForegroundColor Yellow
            exit 1
        }
    }

    if ($Status) { Show-FunnelStatus; exit 0 }

    if ($Disable) {
        $r = Invoke-Tailscale -Arguments @('funnel', '--https=443', 'off')
        if ($r.ExitCode -ne 0) { $r = Invoke-Tailscale -Arguments @('funnel', 'reset') }
        if ($r.ExitCode -ne 0) { throw 'ปิด Funnel ไม่สำเร็จ ลอง "tailscale funnel reset" ด้วยตนเอง' }
        Write-InstallLog -Phase 'online' -Message 'Tailscale Funnel disabled.'
        Write-Host 'ปิดการเข้าถึงจากอินเทอร์เน็ตแล้ว (ระบบยังใช้ใน LAN ได้ตามปกติ)' -ForegroundColor Green
        exit 0
    }

    # Logged in?
    $st = Get-TailscaleStatusJson
    if (-not $st -or $st.BackendState -ne 'Running') {
        Write-Host 'ยังไม่ได้ล็อกอิน Tailscale: กำลังเปิดเบราว์เซอร์ให้ล็อกอิน (ใช้บัญชีที่ Owner กำหนด)' -ForegroundColor Yellow
        Invoke-Tailscale -Arguments @('up') -NoCapture | Out-Null
        $st = Get-TailscaleStatusJson
        if (-not $st -or $st.BackendState -ne 'Running') {
            throw 'Tailscale ยังไม่พร้อม (BackendState ไม่ใช่ Running) กรุณาล็อกอินให้เสร็จแล้วรันใหม่'
        }
    }

    $port = Get-ConfiguredHttpPort
    Write-InstallLog -Phase 'online' -Message "Starting Tailscale Funnel to local port $port."
    $r = Invoke-Tailscale -Arguments @('funnel', '--bg', "$port")
    if ($r.ExitCode -ne 0) {
        $url = Get-FunnelAdminUrl -Lines $r.Output
        if ($url) {
            Write-Host ''
            Write-Host 'Funnel/HTTPS ยังไม่ได้เปิดใช้งานสำหรับ tailnet นี้' -ForegroundColor Yellow
            Write-Host "1) เปิดลิงก์นี้ในเบราว์เซอร์ (ล็อกอินด้วยบัญชีผู้ดูแล Tailscale): $url"
            Write-Host '2) กดปุ่ม Enable (เปิดใช้งาน HTTPS / Funnel)'
            Write-Host '3) กลับมารัน .\enable-online.ps1 อีกครั้ง'
            exit 1
        }
        throw "tailscale funnel ล้มเหลว: $($r.Output -join ' ')"
    }

    $hostName = Get-FunnelHostName
    if (-not $hostName) { throw 'อ่านชื่อโฮสต์ ts.net จาก tailscale status ไม่ได้' }
    Write-InstallLog -Phase 'online' -Message "Funnel enabled at https://$hostName (port $port)."
    Write-Host ''
    Write-Host 'เปิดใช้งานจากอินเทอร์เน็ตแล้ว' -ForegroundColor Green
    Write-Host "ที่อยู่สำหรับเข้าใช้งาน: https://$hostName" -ForegroundColor Green
    Write-Host 'คำเตือน: ไม่มีด่านยืนยันตัวตนก่อนหน้าล็อกอินของระบบ ใช้รหัสผ่านที่คาดเดายาก (12 ตัวอักษรขึ้นไป)' -ForegroundColor Yellow
    Write-Host 'ปิดได้ด้วย .\enable-online.ps1 -Disable'
    exit 0
}
catch {
    Write-InstallLog -Phase 'online' -Level 'ERROR' -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
