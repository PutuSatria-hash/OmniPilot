@echo off
title OmniPilot Hub - Master Launcher (Server + Link Publik + Auto Telegram)
cd /d "%~dp0"
".venv\Scripts\python.exe" -u "scripts\run_public_tunnel.py"
echo.
pause
