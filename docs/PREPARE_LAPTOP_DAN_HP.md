# Panduan Lengkap Prepare Laptop & HP — OmniPilot Hub

Dokumen ini merangkum seluruh persiapan di **Laptop (Windows)** dan **HP (Android / iOS)** agar workflow automasi jarak jauh, jadwal harian, smart alarm anti-lupa cek HP, remote layar, dan kontrol PC berjalan lancar.

---

## BAGIAN 1: Prepare di Laptop (Windows)

### 1.1 Jalankan Script Persiapan Otomatis
Buka PowerShell (disarankan **Run as Administrator**) di folder proyek ini, lalu jalankan:
```powershell
.\scripts\setup_laptop.ps1 -RemoteDesktop RustDesk -DisableSleepOnAC -EnableAutoStart
```
*(Ganti `-RemoteDesktop RustDesk` menjadi `-RemoteDesktop Sunshine` atau `-RemoteDesktop Both` jika Boss memilih streaming layar 60–120 FPS dengan Moonlight).*

Script ini otomatis:
- Menginstal **Tailscale** (Mesh VPN privat terenkripsi tanpa port forwarding).
- Menginstal **RustDesk** / **Sunshine** untuk kontrol layar & mouse/keyboard penuh.
- Menyiapkan browser Chromium Playwright untuk otomasi LMS.
- Membuka Windows Firewall port `8787` khusus jaringan Privat/Tailscale.
- Mematikan auto-sleep saat laptop colok listrik dan mendaftarkan auto-start saat login Windows.

### 1.2 Login Tailscale & Ambil IP Privat Laptop
1. Buka aplikasi **Tailscale** di tray Windows lalu login (Google / GitHub / Microsoft).
2. Catat IP Tailscale laptop Boss (format `100.x.y.z`, misalnya `100.88.12.5`).
3. Jika memakai **RustDesk**, buka RustDesk, catat **ID PC** dan set **Permanent Password** yang kuat, lalu masukkan ID tersebut ke `RUSTDESK_PC_ID` di file `.env`.

### 1.3 Lengkapi File `.env`
Buka file `.env` di folder proyek dan isi integrasi yang Boss aktifkan:
- `GEMINI_API_KEY`: Buat di https://aistudio.google.com/app/api-keys agar prompt bahasa natural aktif.
- `TELEGRAM_BOT_TOKEN` & `TELEGRAM_ALLOWED_USER_ID`:
  1. Chat `@BotFather` di Telegram -> `/newbot` -> salin token.
  2. Chat `@userinfobot` di Telegram -> salin angka ID akun Boss agar bot terkunci hanya untuk Boss.
- `GOOGLE_CALENDAR_ICS_URL` (Cara tercepat sinkron jadwal Google Calendar):
  1. Buka Google Calendar di web -> *Settings* -> pilih kalender utama -> *Integrate calendar* -> salin **Secret address in iCal format**.
- `LMS_BASE_URL`: URL halaman dashboard LMS Boss, lalu jalankan sekali:
  ```powershell
  .\.venv\Scripts\python.exe .\scripts\lms_login.py
  ```
  Login sekali secara normal (SSO/2FA aman) agar sesi tersimpan.
- **Gmail**: Gunakan **Plugin Resmi Gmail di Antigravity** (paling cepat) ATAU unduh `google_credentials.json` (OAuth Desktop App) ke folder `data/` lalu jalankan `.\.venv\Scripts\python.exe .\scripts\google_oauth_setup.py`.
- **WhatsApp (Opsional - Mode Aman)**:
  ```powershell
  cd whatsapp-bridge
  npm install
  npm start
  ```
  Scan QR di terminal menggunakan WhatsApp HP (*Perangkat Tertaut*), lalu set `WHATSAPP_ENABLED=true` di `.env`. Semua balasan WA tetap wajib melewati tombol **Approve** dari Boss.

### 1.4 Jalankan OmniPilot Hub
```powershell
.\scripts\start_hub.ps1
```
Terminal akan menampilkan URL Tailscale dan **QR Code** yang bisa langsung di-scan kamera HP untuk login otomatis ke Web Command Center PWA.

---

## BAGIAN 2: Prepare di HP (Android)

### 2.1 Aplikasi yang Perlu Diinstal di Android
1. **Tailscale** (Play Store) — login akun yang sama dengan laptop, lalu nyalakan toggle VPN.
2. **RustDesk** (atau **Moonlight** jika pakai Sunshine) — untuk kontrol layar, mouse, dan keyboard laptop penuh dari HP.
3. **Telegram** — jika memakai perintah chat instan & tombol Approve/Matikan Alarm langsung di chat.
4. **ntfy** + **MacroDroid** (untuk **Smart Alarm Opsi A — Gratis & Full Control Android**), ATAU **Pushover** (untuk **Smart Alarm Opsi B — Paling Praktis**).

### 2.2 Install Web Command Center ke Layar Utama (PWA)
1. Pastikan **Tailscale** di HP aktif.
2. Scan QR Code dari terminal `start_hub.ps1` (atau buka `http://<IP_TAILSCALE_LAPTOP>:8787`).
3. Di Chrome Android, tekan menu titik tiga -> **Add to Home screen / Install app**.

### 2.3 Setup Smart Alarm "Deteksi Tidak Cek HP -> Alarm Keras Bypass Silent" (Android)

#### A. Macro 1 — Sensor "Boss Sudah Cek HP" (Auto Heartbeat)
Agar PC tahu otomatis setiap kali Boss membuka layar HP (sehingga alarm tidak salah bunyi):
1. Buka **MacroDroid** -> **Add Macro** -> beri nama `OmniPilot Phone Check-In`.
2. **Trigger**: `Device Events` -> `Screen Unlocked` (bisa juga tambah `Screen On`).
3. **Action**: `Web Interactions` -> `HTTP Request`:
   - Method: `POST`
   - URL: `http://<IP_TAILSCALE_LAPTOP>:8787/api/phone/heartbeat`
   - Header: `Authorization: Bearer <API_AUTH_TOKEN_DARI_ENV>`
   - Content-Type: `application/json`
   - Body: `{"event_type": "screen_unlock", "device_name": "android", "auto_ack_alarms": true}`
4. **Constraint (Opsional)**: Hanya jalan jika koneksi jaringan aktif (menghemat baterai).

#### B. Macro 2 — Pemicu Alarm Darurat Bypass Silent / DND
1. **Via ntfy + MacroDroid (Gratis & Andal)**:
   - Install aplikasi **ntfy**, subscribe ke topic rahasia yang sama dengan `NTFY_TOPIC` di `.env`.
   - Di Android *Settings -> Apps -> ntfy -> Notifications -> Max priority* -> aktifkan **Override Do Not Disturb** dan pilih nada alarm paling keras.
   - Tambahkan Macro di **MacroDroid** (`OmniPilot Critical Alarm`):
     - **Trigger**: `Device Events` -> `Notification` -> `Notification Received` -> Pilih app `ntfy` -> Text contains `ALARM DARURAT` *(atau gunakan Trigger `Webhook (Url)` bawaan MacroDroid lalu salin URL-nya ke `MACRODROID_WEBHOOK_URL` di `.env`)*.
     - **Actions**:
       1. `Volume` -> `Volume Change` -> set **Alarm = 100%** & **Media = 100%**.
       2. `Volume` -> `Priority Mode / Do Not Disturb` -> `Allow All`.
       3. `Media` -> `Play/Stop Sound` -> pilih audio alarm keras (stream: **Alarm**).
       4. `Screen` -> `Screen On` (nyalakan layar HP).
       5. *(Opsional)* `Device Actions` -> `Speak Text` -> `"Boss, ada jadwal penting dan belum ada tanda cek HP!"`.

---

## BAGIAN 3: Prepare di HP (iPhone / iOS)

1. Install **Tailscale**, **RustDesk** (atau **Moonlight**), **Telegram**, dan **Pushover**.
2. Buka Safari -> akses `http://<IP_TAILSCALE_LAPTOP>:8787` -> tekan **Share** -> **Add to Home Screen** (PWA).
3. Untuk **Smart Alarm Bypass Silent & Focus Mode di iOS**:
   - Buka **Pushover** -> *Settings* -> aktifkan **Critical Alerts** (izin resmi Apple untuk menembus tombol mute & mode tidur/DND!).
   - Masukkan `PUSHOVER_APP_TOKEN` dan `PUSHOVER_USER_KEY` ke `.env` laptop.
   - Saat timer pengecekan HP habis tanpa ACK, PC akan mengirim **Pushover Priority 2** yang otomatis membunyikan sirine berulang setiap 30 detik sampai Boss menekan tombol **Acknowledge**.
4. *(Opsional Apple Shortcuts)*: Buat Personal Automation saat membuka aplikasi harian (misal WhatsApp/Instagram) -> *Get Contents of URL* (`POST http://<IP_TAILSCALE>:8787/api/phone/heartbeat`) agar status "cek HP" otomatis tercatat.

---

## BAGIAN 4: Kontrol Laptop Rumah dari PC Lab Kampus (TANPA INSTALL di PC Lab!)

Komputer lab kampus umumnya membatasi hak Administrator, memasang Deep Freeze, dan memblokir port selain HTTPS (443). Jangan pernah login akun pribadi permanen atau install VPN di PC Lab! Gunakan alur **Browser-Only Zero-Install** berikut:

### 4.1 Persiapan Sekali di Laptop Rumah (Sebelum Berangkat ke Kampus)
1. Pastikan laptop rumah menyala (colok charger, sleep AC sudah dimatikan via `setup_laptop.ps1`) dan `.\scripts\start_hub.ps1` aktif.
2. Pilih salah satu jalur HTTPS Port 443 agar tembus firewall kampus:
   - **Opsi A — Cloudflare Tunnel (Direkomendasikan, paling fleksibel & bisa ditambah Cloudflare Access OTP Email)**:
     ```powershell
     .\scripts\start_campus_tunnel.ps1 -Mode CloudflareQuick
     ```
     *(Untuk URL permanen dengan domain sendiri + login Cloudflare Access OTP Google/Email, gunakan `cloudflared tunnel login` dan `cloudflared tunnel create` sesuai panduan Cloudflare Zero Trust gratis).*
   - **Opsi B — Tailscale Funnel (1 Perintah jika sudah pakai Tailscale)**:
     ```powershell
     .\scripts\start_campus_tunnel.ps1 -Mode TailscaleFunnel
     ```
     Akan menghasilkan URL permanen `https://<nama-laptop>.<tailnet>.ts.net`.
3. *(Opsional untuk Full Desktop 30–60 FPS di Browser PC Lab)*: Di laptop rumah, buka `https://remotedesktop.google.com/access` -> aktifkan **Chrome Remote Desktop** dan buat PIN rahasia.

### 4.2 Cara Pakai Aman di PC Lab Kampus
1. Buka **Chrome / Edge mode Incognito (Penyamaran)** di PC Lab Kampus.
2. Akses URL HTTPS Tunnel Boss (dari Cloudflare Tunnel atau Tailscale Funnel).
3. Pada layar login OmniPilot Hub:
   - Masukkan `API_AUTH_TOKEN`.
   - **WAJIB centang**: `Mode PC Lab / Umum (jangan simpan token setelah tab ditutup)`.
4. Dari browser PC Lab Kampus, Boss langsung bisa:
   - Membuka tab **PC & Layar** -> melihat layar laptop rumah secara live, **klik kiri / double-klik / klik kanan langsung pada layar**, scroll, mengetik teks, dan menekan shortcut (`Alt+Tab`, `Ctrl+C/V`, `Enter`, `Win`) tanpa install software apapun di PC Lab.
   - Mengirim prompt AI, buka Antigravity/VS Code di laptop rumah, buat dokumen DOCX/PDF, cek Gmail/WA, dan kelola tugas LMS.
   - Jika butuh kendali desktop full-screen lebih mulus untuk coding panjang, buka tab Incognito kedua ke `https://remotedesktop.google.com/access` (atau jalankan **RustDesk Portable** dari flashdisk jika diizinkan).
5. **Saat Selesai Menggunakan PC Lab**:
   - Klik tombol merah **Logout** di pojok kanan atas OmniPilot Hub.
   - Tutup seluruh jendela Incognito agar nol jejak kredensial tertinggal di PC Lab.

---

## BAGIAN 5: Kontrol Laptop Rumah dari PC Pribadi Kedua (PC-to-PC)
1. Install **Tailscale** + **RustDesk** (atau **Moonlight**) di PC pribadi kedua dengan akun Tailscale yang sama.
2. Akses Web Command Center melalui `http://<IP_TAILSCALE_LAPTOP>:8787` dan gunakan RustDesk/Moonlight untuk kontrol penuh 60 FPS.
