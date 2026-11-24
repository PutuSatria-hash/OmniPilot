@echo off
title OmniPilot Hub - LINK PUBLIK INTERNET (Cloudflare HTTPS)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_campus_tunnel.ps1" -Mode CloudflareQuick
echo.
pause
