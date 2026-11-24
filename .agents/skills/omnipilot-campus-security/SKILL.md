---
name: omnipilot-campus-security
description: >-
  Use this skill when hardening OmniPilot Hub for remote access from untrusted computers
  like campus lab PCs, managing interactive remote mouse/keyboard controls, rotating API
  auth tokens, or performing emergency remote lock/logout procedures.
---

# OmniPilot Campus Lab & Remote Security

Runbook keamanan untuk mengendalikan laptop rumah dari jaringan luar atau komputer umum seperti **PC Lab Kampus**.

## Prinsip Zero-Trace di PC Lab Kampus
1. Selalu instruksikan Boss membuka browser PC Lab dalam mode **Incognito / Private Window**.
2. Saat login ke OmniPilot Web Command Center di PC Lab, wajib centang **Mode PC Lab / Umum** (menyimpan token di `sessionStorage` sementara, bukan `localStorage`).
3. Jangan pernah menginstal Tailscale atau login permanen di PC Lab Kampus; gunakan HTTPS Port 443 via **Cloudflare Tunnel** (disarankan + Cloudflare Access OTP) atau **Tailscale Funnel**.
4. Sebelum meninggalkan PC Lab, wajib klik tombol **Logout** di topbar dan tutup semua jendela Incognito.

## Kontrol Input Remote & Emergency Lock
- Fitur klik/ketik layar interaktif diatur oleh `REMOTE_INPUT_ENABLED=true|false` di `.env`.
- Endpoint proteksi:
  - Mouse: `POST /api/pc/mouse`
  - Keyboard: `POST /api/pc/keyboard`
  - Kunci layar laptop rumah seketika: `POST /api/pc/lock`
- Perintah shell berbahaya (`rm -rf`, `shutdown`, `format`, `reg delete`, dll.) otomatis tertahan di `ApprovalGate`.

## Rotasi Token & Validasi Keamanan
1. Ganti `API_AUTH_TOKEN` di `.env` kapan saja jika merasa token terekspos di komputer umum, lalu restart `start_hub.ps1`.
2. Jalankan tes keamanan: `.venv\Scripts\pytest.exe -v -k "auth_guard or remote_input_security_guard"`
