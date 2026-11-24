@echo off
title OmniPilot Hub - Server Utama & QR Pairing
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_hub.ps1"
echo.
pause
