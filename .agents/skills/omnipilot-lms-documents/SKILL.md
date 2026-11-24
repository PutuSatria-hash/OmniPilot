---
name: omnipilot-lms-documents
description: >-
  Use this skill when generating formatted academic or work documents (DOCX, PDF, Markdown),
  logging into Boss's campus LMS via persistent Playwright browser profiles, checking LMS
  deadlines, or staging assignment uploads safely through the Approval Gate.
---

# OmniPilot Document Generator & LMS Automation

Runbook untuk membuat dokumen tugas/laporan otomatis dan mengelola alur pengumpulan tugas LMS dengan aman.

## Pembuatan Dokumen
- Modul: [documents.py](../../backend/modules/documents.py)
- Output tersimpan di folder `outputs/documents/` dan dapat diunduh langsung dari HP/PC Lab lewat `GET /api/documents/download/{filename}`.
- Format yang didukung: `docx`, `pdf`, dan `md`.
- Untuk dokumen kolaboratif Google Docs, utamakan plugin resmi **Google Docs** bila aktif.

## Otomasi LMS (Playwright Persistent Profile)
1. **Login Sekali (Aman untuk SSO/2FA)**:
   - Pastikan `LMS_BASE_URL` sudah diisi di `.env`.
   - Jalankan `.\.venv\Scripts\python.exe .\scripts\lms_login.py` agar Boss login manual satu kali; cookie sesi otomatis tersimpan di `data/browser_profile/`.
   - Jangan pernah menyimpan password LMS mentah di kode atau file log.
2. **Inspeksi Dashboard & Deadline**:
   - Panggil `POST /api/lms/inspect` (atau `/lms` di chat) untuk mengambil daftar tugas dan tangkapan layar ke `outputs/screenshots/lms_latest.png`.
3. **Upload Tugas (Wajib Approval Gate)**:
   - Panggil `POST /api/lms/submit` -> sistem **wajib** memasukkan aksi ke `ApprovalGate` dan menunggu Boss menekan **Approve** sebelum menyisipkan file dan menyimpan bukti `outputs/screenshots/lms_submit_proof.png`.

## Validasi
- Pastikan browser Chromium Playwright terpasang: `.\.venv\Scripts\python.exe -m playwright install chromium`
- Uji pembuatan dokumen: `.venv\Scripts\pytest.exe -v -k test_approval_gate_and_document_generation`
