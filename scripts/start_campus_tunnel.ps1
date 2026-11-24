<#
.SYNOPSIS
    Membuka Link Publik HTTPS (Port 443) agar Laptop Rumah bisa diakses dari internet mana saja
    (PC Lab Kampus, HP, atau jaringan berbeda) tanpa install VPN.
.EXAMPLE
    .\scripts\start_campus_tunnel.ps1 -Mode CloudflareQuick
    .\scripts\start_campus_tunnel.ps1 -Mode TailscaleFunnel
#>

param(
    [ValidateSet("CloudflareQuick", "TailscaleFunnel")]
    [string]$Mode = "CloudflareQuick",
    [int]$Port = 8787
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

function Resolve-ToolPath {
    param([string]$CommandName, [string[]]$FallbackPaths)
    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in $FallbackPaths) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

$TailscaleBin = Resolve-ToolPath -CommandName "tailscale" -FallbackPaths @(
    "C:\Program Files\Tailscale\tailscale.exe"
)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  OmniPilot Hub - Public Internet HTTPS Tunnel ($Mode)         " -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan

if ($Mode -eq "TailscaleFunnel") {
    if (-not $TailscaleBin) {
        Write-Host "Tailscale belum terpasang. Jalankan 1_SETUP_LAPTOP_ADMIN.bat terlebih dahulu." -ForegroundColor Red
        exit 1
    }
    Write-Host "Mengaktifkan Tailscale Funnel Publik Permanen (HTTPS Port 443)..." -ForegroundColor Yellow
    Write-Host "Pastikan fitur Funnel sudah diaktifkan di Tailscale Admin Console -> DNS & Access Controls." -ForegroundColor Gray
    & $TailscaleBin funnel $Port
} else {
    if (Test-Path $VenvPython) {
        & $VenvPython -u (Join-Path $ProjectRoot "scripts\run_public_tunnel.py")
    } else {
        Write-Host ".venv tidak ditemukan di $ProjectRoot" -ForegroundColor Red
        exit 1
    }
}
