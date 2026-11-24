@echo off
title OmniPilot Hub - Setup Laptop Windows (Admin)
cd /d "%~dp0"

:: Cek hak Administrator, otomatis minta UAC jika belum Admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Meminta izin Administrator untuk menjalankan setup laptop...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_laptop.ps1" -RemoteDesktop RustDesk -CampusTunnel Both -DisableSleepOnAC -EnableAutoStart
echo.
pause
