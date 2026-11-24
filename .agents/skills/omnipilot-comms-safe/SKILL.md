---
name: omnipilot-comms-safe
description: >-
  Use this skill when integrating, summarizing, drafting, or replying to messages in Gmail
  or WhatsApp via OmniPilot Hub while enforcing Human-in-the-Loop approvals and anti-ban
  safeguards for personal WhatsApp numbers.
---

# OmniPilot Safe Communications (Gmail & WhatsApp)

Runbook untuk mengelola baca, rangkum, draft, dan balas pesan di Gmail serta WhatsApp dengan keamanan akun sebagai prioritas utama.

## Aturan Wajib (Anti-Salah Kirim & Anti-Banned)
1. **Human-in-the-Loop Wajib**: Tidak ada pengiriman email Gmail atau balasan WhatsApp yang boleh dieksekusi otomatis tanpa melewati `ApprovalGate` (`POST /api/approvals/{id}/approve`).
2. **Proteksi WhatsApp Pribadi**:
   - Bridge Node.js di [whatsapp-bridge/index.js](../../whatsapp-bridge/index.js) hanya mendengarkan `127.0.0.1:3005`.
   - Dilarang mengubah bridge menjadi auto-reply instan tanpa jeda; pertahankan simulasi mengetik natural (2.5–5.5 detik) dan cooldown minimal 10 detik antar pesan keluar.
   - Rekomendasikan nomor cadangan untuk uji coba awal jika Boss ingin menghindari risiko ToS pada nomor utama.

## Setup Cepat
- **Gmail**:
  - Jalur utama: gunakan Plugin Resmi **Gmail** di Antigravity.
  - Jalur lokal OAuth2: simpan `data/google_credentials.json`, lalu jalankan `.\.venv\Scripts\python.exe .\scripts\google_oauth_setup.py`.
- **WhatsApp Bridge (Opt-In)**:
  1. `cd whatsapp-bridge && npm install && npm start`
  2. Scan QR di terminal dari WhatsApp HP (*Perangkat Tertaut*).
  3. Set `WHATSAPP_ENABLED=true` di `.env`.

## Validasi
- Cek status bridge: `GET /api/whatsapp/status`
- Cek sintaks bridge: `node --check whatsapp-bridge\index.js`
