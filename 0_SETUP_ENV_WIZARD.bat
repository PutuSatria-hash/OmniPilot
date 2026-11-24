@echo off
title OmniPilot Hub - Interactive Setup Wizard (.env)
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\setup_wizard.py"
) else (
    python "scripts\setup_wizard.py"
)
echo.
pause
