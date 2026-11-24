# OmniPilot Hub — Workspace Rules

Aturan kerja wajib bagi agent di dalam proyek **SetUp Automation (OmniPilot Hub)**:

1. **Python Environment**: Selalu gunakan `.venv\Scripts\python.exe`, `.venv\Scripts\pip.exe`, dan `.venv\Scripts\pytest.exe`. Dilarang menjalankan `pip install` secara global.
2. **Approval Gate Wajib**: Semua aksi berdampak eksternal (mengirim Gmail, membalas WhatsApp, mengunggah/submit tugas LMS, dan perintah PowerShell destruktif) wajib melalui `ApprovalGate` dan tidak boleh dieksekusi diam-diam.
3. **Keamanan Rahasia & PC Lab**: Jangan pernah mencetak isi token/API key dari `.env` ke log publik atau commit `.env` maupun folder `data/` ke Git. Untuk akses dari komputer umum/PC Lab Kampus, selalu arahkan pada mode Incognito + Mode PC Lab (`sessionStorage`) + Logout setelah selesai.
4. **Verifikasi Perubahan**: Setiap perubahan pada `backend/`, `frontend/`, atau `scripts/` wajib diverifikasi dengan `.venv\Scripts\pytest.exe -v`, `node --check`, dan validasi sintaks PowerShell sebelum dinyatakan selesai.
5. **Skill Proyek Tersedia**: Aktifkan skill yang relevan di `.agents/skills/` (`omnipilot-remote-setup`, `omnipilot-schedule-alarm`, `omnipilot-lms-documents`, `omnipilot-comms-safe`, `omnipilot-campus-security`) saat mengerjakan tugas terkait.
