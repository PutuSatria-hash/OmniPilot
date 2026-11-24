@echo off
title OmniPilot Hub - Login Sesi LMS (Sekali Saja)
cd /d "%~dp0"
".venv\Scripts\python.exe" "scripts\lms_login.py"
echo.
pause
