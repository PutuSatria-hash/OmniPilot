"""Quick local verification script to test Push/Alarm channels (ntfy, MacroDroid, Pushover, PC Siren)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.config import get_settings
from backend.core.database import Database
from backend.core.event_bus import EventBus
from backend.modules.pc_control import PCControlService
from backend.modules.scheduler_alarm import SchedulerAlarmService


async def main() -> None:
    settings = get_settings()
    db = Database(settings.db_path)
    await db.connect()
    bus = EventBus()
    pc = PCControlService(settings)
    svc = SchedulerAlarmService(settings, db, bus, pc)

    print("Menguji pemicu Smart Escalation Alarm ke semua channel yang dikonfigurasi di .env...")
    alarm = await svc.arm_escalation_alarm(
        title="Tes Alarm Darurat OmniPilot",
        message="Ini adalah tes notifikasi eskalasi dan sirine darurat untuk Boss.",
        timeout_minutes=1,
    )
    print(f"Alarm dibuat (ID: {alarm['id']}). Memicu Stage 3 CRITICAL sekarang...")
    await svc._trigger_critical_alarm_channels(alarm)
    await svc.acknowledge_alarm(alarm["id"], source="demo_script")
    await db.close()
    print("Tes selesai, Boss! Cek HP dan speaker laptop Anda.")


if __name__ == "__main__":
    asyncio.run(main())
