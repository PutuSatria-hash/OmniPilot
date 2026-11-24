<#
.SYNOPSIS
    Menjalankan OmniPilot Hub & menampilkan QR Code pairing untuk HP Boss.
#>

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Virtual environment .venv tidak ditemukan di $ProjectRoot!" -ForegroundColor Red
    exit 1
}

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "  OmniPilot Hub - Starting Remote Command Center...       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

& $VenvPython (Join-Path $ProjectRoot "scripts\print_pairing_qr.py")
& $VenvPython -m uvicorn backend.main:app --host 0.0.0.0 --port 8787
