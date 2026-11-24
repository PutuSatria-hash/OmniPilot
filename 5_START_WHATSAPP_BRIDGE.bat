@echo off
title OmniPilot Hub - WhatsApp Safe Bridge (Human-in-the-Loop)
cd /d "%~dp0whatsapp-bridge"

if not exist "node_modules\express" (
    echo Menginstal library WhatsApp Bridge untuk pertama kali...
    call npm.cmd install
    if errorlevel 1 (
        echo.
        echo GAGAL menjalankan npm install. Pastikan koneksi internet aktif lalu coba lagi.
        pause
        exit /b 1
    )
)

echo.
echo Menjalankan WhatsApp Safe Bridge di http://127.0.0.1:3005 ...
echo Scan QR Code yang muncul dari WhatsApp HP (Menu - Perangkat Tertaut).
echo Semua balasan WA tetap wajib melewati tombol Approve Boss (anti-ban).
echo.
node index.js
echo.
pause
