---
name: omnipilot-remote-setup
description: >-
  Use this skill when setting up, starting, pairing, or troubleshooting OmniPilot Hub
  across Boss's home Windows laptop, mobile phone (Android/iOS), or zero-install
  campus lab PC browser access (Tailscale, Cloudflare Tunnel, RustDesk, Sunshine/Moonlight).
---

# OmniPilot Remote Setup & Operations

Runbook untuk menyiapkan, menjalankan, dan memverifikasi akses jarak jauh OmniPilot Hub antara Laptop Rumah, HP, dan PC Lab Kampus.

## Prasyarat Environment
- Selalu gunakan virtual environment proyek: `.venv\Scripts\python.exe` dan `.venv\Scripts\pip.exe`.
- Jangan pernah menjalankan `pip install` secara global.
- Konfigurasi aktif berada di [`.env`](../../.env) (template di [`.env.example`](../../.env.example)).

## Prosedur Persiapan Laptop (Windows)
1. Jalankan script persiapan otomatis (PowerShell Administrator):
   `.\scripts\setup_laptop.ps1 -RemoteDesktop RustDesk -CampusTunnel Both -DisableSleepOnAC -EnableAutoStart`
2. Pastikan Tailscale sudah login di laptop rumah (`tailscale ip -4`) dan catat IP `100.x.y.z`.
3. Jalankan server utama + cetak QR pairing untuk HP:
   `.\scripts\start_hub.ps1`
4. Untuk akses dari **PC Lab Kampus (Zero-Install, HTTPS Port 443)**, jalankan salah satu tunnel:
   - Cloudflare Tunnel: `.\scripts\start_campus_tunnel.ps1 -Mode CloudflareQuick`
   - Tailscale Funnel: `.\scripts\start_campus_tunnel.ps1 -Mode TailscaleFunnel`

## Referensi Lengkap
- Panduan Laptop, Android, iOS, & PC Lab Kampus: [PREPARE_LAPTOP_DAN_HP.md](../../docs/PREPARE_LAPTOP_DAN_HP.md)

## Validasi
- Jalankan suite pengujian otomatis: `.venv\Scripts\pytest.exe -v`
- Cek endpoint kesehatan server: `GET http://127.0.0.1:8787/api/health` -> harus mengembalikan `{"status": "ok"}`.
