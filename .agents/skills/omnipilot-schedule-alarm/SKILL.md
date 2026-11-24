---
name: omnipilot-schedule-alarm
description: >-
  Use this skill when managing Boss's daily schedule, Google Calendar ICS synchronization,
  morning briefings, phone check-in heartbeats, or configuring and testing the 3-stage
  Smart Escalation Alarm (ntfy + MacroDroid or Pushover Priority 2).
---

# OmniPilot Schedule & Smart Escalation Alarm

Runbook untuk mengelola jadwal harian Boss dan sistem **Dead-Man's Switch Alarm** yang menyalakan alarm darurat bypass silent jika tidak ada tanda Boss mengecek HP dalam batas timer.

## Alur Eskalasi Alarm 3 Tahap
1. **Stage 1 (`ARMED`)**: Pengingat awal dikirim ke PWA, Telegram (dengan tombol 1-tap ACK), dan `ntfy` prioritas normal.
2. **Stage 2 (`WARNING`)**: Di 50% durasi timer tanpa heartbeat HP/ACK, kirim peringatan prioritas tinggi.
3. **Stage 3 (`CRITICAL`)**: Saat deadline terlewati tanpa tanda cek HP, tembak seluruh kanal darurat:
   - `ntfy` (`Priority: max`) + `MACRODROID_WEBHOOK_URL` (Opsi A Android: volume 100%, matikan DND, alarm keras).
   - `Pushover` (`priority=2`, `retry=30`, `expire=1800` — Opsi B Android & iOS Critical Alerts).
   - Sirine cadangan speaker laptop Windows (`PC_FALLBACK_SIREN_ENABLED=true`) dan Web Audio PWA.

## Endpoint Utama
- Jadwal hari ini + briefing: `GET /api/schedules/today`
- Tambah jadwal: `POST /api/schedules`
- Aktifkan timer alarm: `POST /api/alarms/arm`
- Matikan alarm (ACK): `POST /api/alarms/{id}/ack` atau `POST /api/alarms/ack-all`
- Sensor HP (Screen Unlock MacroDroid / Shortcuts): `POST /api/phone/heartbeat`

## Pengujian & Validasi
1. Uji tembak seluruh kanal alarm secara langsung:
   `.\.venv\Scripts\python.exe .\scripts\test_alarm_demo.py`
2. Verifikasi logika eskalasi otomatis:
   `.venv\Scripts\pytest.exe -v -k test_smart_alarm`
3. Panduan setup MacroDroid & Pushover ada di [PREPARE_LAPTOP_DAN_HP.md](../../docs/PREPARE_LAPTOP_DAN_HP.md).
