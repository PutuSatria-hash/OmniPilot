<#
.SYNOPSIS
    OmniPilot Hub - Script Persiapan Otomatis Laptop Windows (Fresh Clone Ready).
.DESCRIPTION
    Menyiapkan Python .venv + dependensi, membuat .env awal dengan token aman,
    menginstal Tailscale, Cloudflare Tunnel, RustDesk/Sunshine, Playwright Chromium,
    mengonfigurasi Windows Firewall port 8787, anti-sleep AC, dan auto-start.
#>

param(
    [ValidateSet("RustDesk", "Sunshine", "Both", "Skip")]
    [string]$RemoteDesktop = "RustDesk",
    [ValidateSet("Cloudflared", "TailscaleFunnel", "Both", "Skip")]
    [string]$CampusTunnel = "Both",
    [switch]$EnableAutoStart,
    [switch]$DisableSleepOnAC
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# Refresh PATH so newly installed tools are detected cleanly
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  OmniPilot Hub - Prepare Laptop Windows (Auto Setup)     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Folder Proyek: $ProjectRoot" -ForegroundColor Gray

# 1. Python Virtual Environment & Dependencies (Fresh Clone Ready)
Write-Host "`n[1/7] Menyiapkan Python Virtual Environment (.venv) & Library..." -ForegroundColor Yellow
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$VenvPip = Join-Path $ProjectRoot ".venv\Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "Python belum terpasang! Install Python 3.11+ dari https://www.python.org/downloads/ lalu centang 'Add python.exe to PATH'." -ForegroundColor Red
        exit 1
    }
    Write-Host "Membuat virtual environment .venv..."
    python -m venv .venv
}

if (Test-Path $VenvPip) {
    Write-Host "Menginstal library Python dari requirements.txt..."
    & $VenvPip install -r (Join-Path $ProjectRoot "requirements.txt")
}

# Bootstrap .env otomatis dengan token acak aman jika belum ada
if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
    & $VenvPython (Join-Path $ProjectRoot "scripts\setup_wizard.py") --bootstrap
}

# 2. Install Tailscale (Private Mesh VPN & Tailscale Funnel)
Write-Host "`n[2/7] Memeriksa Tailscale..." -ForegroundColor Yellow
if (-not (Get-Command tailscale -ErrorAction SilentlyContinue) -and -not (Test-Path "C:\Program Files\Tailscale\tailscale.exe")) {
    Write-Host "Menginstal Tailscale via winget..."
    winget install --id Tailscale.Tailscale --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "Tailscale sudah terpasang." -ForegroundColor Green
}

# 3. Install Cloudflare Tunnel (untuk akses publik HTTPS tanpa install VPN di PC Lab)
Write-Host "`n[3/7] Memeriksa Cloudflare Tunnel ($CampusTunnel)..." -ForegroundColor Yellow
if ($CampusTunnel -in @("Cloudflared", "Both")) {
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue) -and -not (Test-Path "C:\Program Files (x86)\cloudflared\cloudflared.exe") -and -not (Test-Path "C:\Program Files\cloudflared\cloudflared.exe")) {
        winget install --id Cloudflare.cloudflared --accept-source-agreements --accept-package-agreements
    } else {
        Write-Host "cloudflared sudah terpasang." -ForegroundColor Green
    }
}

# 4. Install Remote Desktop (RustDesk / Sunshine)
Write-Host "`n[4/7] Memeriksa Remote Desktop ($RemoteDesktop)..." -ForegroundColor Yellow
if ($RemoteDesktop -in @("RustDesk", "Both")) {
    if (-not (Test-Path "C:\Program Files\RustDesk\rustdesk.exe")) {
        winget install --id RustDesk.RustDesk -e --accept-source-agreements --accept-package-agreements
    } else {
        Write-Host "RustDesk sudah terpasang." -ForegroundColor Green
    }
}
if ($RemoteDesktop -in @("Sunshine", "Both")) {
    winget install --id LizardByte.Sunshine --accept-source-agreements --accept-package-agreements
}

# 5. Install Playwright Chromium (untuk otomasi LMS)
Write-Host "`n[5/7] Menyiapkan Chromium Playwright untuk LMS..." -ForegroundColor Yellow
if (Test-Path $VenvPython) {
    & $VenvPython -m playwright install chromium
}

# 6. Firewall & Anti-Sleep (Opsional butuh Run as Administrator)
Write-Host "`n[6/7] Konfigurasi Firewall Port 8787 (Jaringan Tailscale & LAN)..." -ForegroundColor Yellow
$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($IsAdmin) {
    $RuleName = "OmniPilot Hub Port 8787"
    $ExistingRule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if ($ExistingRule) {
        Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    }
    New-NetFirewallRule `
        -DisplayName $RuleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 8787 `
        -RemoteAddress @("100.64.0.0/10", "LocalSubnet") `
        -Profile Any `
        -Action Allow | Out-Null
    Write-Host "Firewall rule '$RuleName' berhasil disetel (khusus Tailscale & LAN lokal)." -ForegroundColor Green

    if ($DisableSleepOnAC) {
        powercfg /change standby-timeout-ac 0
        Write-Host "Auto-sleep saat colok charger (AC) dimatikan agar akses remote selalu online." -ForegroundColor Green
    }
} else {
    Write-Host "Lewati konfigurasi Firewall/Power Plan (jalankan 1_SETUP_LAPTOP_ADMIN.bat sebagai Administrator jika ingin otomatis)." -ForegroundColor DarkYellow
}

# 7. Auto-Start saat Login Windows
Write-Host "`n[7/7] Auto-Start Startup Task..." -ForegroundColor Yellow
if ($EnableAutoStart) {
    $StartupFolder = [Environment]::GetFolderPath("Startup")
    $BatPath = Join-Path $StartupFolder "Start-OmniPilotHub.bat"
    $StartScript = Join-Path $ProjectRoot "scripts\start_hub.ps1"
    $BatContent = "@echo off`r`npowershell -WindowStyle Minimized -ExecutionPolicy Bypass -File `"$StartScript`""
    Set-Content -Path $BatPath -Value $BatContent -Encoding ASCII
    Write-Host "Auto-start berhasil ditambahkan ke: $BatPath" -ForegroundColor Green
} else {
    Write-Host "Lewati auto-start (gunakan flag -EnableAutoStart untuk mengaktifkan)." -ForegroundColor Gray
}

Write-Host "`nPersiapan Laptop selesai!" -ForegroundColor Cyan
Write-Host "Langkah berikutnya:"
Write-Host "  1. Double-click 0_SETUP_ENV_WIZARD.bat untuk mengisi API key & Telegram secara interaktif."
Write-Host "  2. Double-click START_ALL.bat (Server + Link Publik HTTPS + Auto Telegram)."
