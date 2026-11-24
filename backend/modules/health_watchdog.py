"""Laptop Health Watchdog: alerts Boss via Telegram/PWA when RAM, battery, disk, or bridges are in trouble."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from backend.core.config import Settings
from backend.core.event_bus import EventBus
from backend.modules.pc_control import PCControlService
from backend.modules.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


class HealthWatchdogService:
    """Periodically evaluates laptop health and publishes rate-limited `health_alert` events."""

    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        pc_control: PCControlService,
        whatsapp: WhatsAppService,
    ) -> None:
        self.settings = settings
        self.bus = bus
        self.pc_control = pc_control
        self.whatsapp = whatsapp
        self._last_alert: dict[str, float] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        self.last_snapshot: dict[str, Any] = {}

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="health-watchdog-loop")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(20)  # let the laptop settle after boot
        while self._running:
            try:
                await self.check_once()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Health check gagal: %s", exc)
            await asyncio.sleep(self.settings.health_check_interval_seconds)

    def _should_alert(self, key: str) -> bool:
        now = time.monotonic()
        last = self._last_alert.get(key)
        if last is not None and now - last < self.settings.health_alert_cooldown_minutes * 60:
            return False
        self._last_alert[key] = now
        return True

    async def check_once(self) -> list[dict[str, Any]]:
        """Run all health checks once; returns the alerts that were actually published."""
        s = self.settings
        t = await asyncio.to_thread(self.pc_control.get_telemetry)
        issues: list[tuple[str, str, str]] = []

        if t["ram_percent"] >= s.health_ram_alert_percent:
            top = await asyncio.to_thread(self.pc_control.list_top_processes, 3)
            top_txt = ", ".join(f"{p['name']} ({p['memory_mb']:.0f} MB)" for p in top) or "-"
            issues.append(
                (
                    "ram",
                    "RAM Laptop Hampir Penuh",
                    f"RAM {t['ram_percent']}% ({t['ram_used_gb']}/{t['ram_total_gb']} GB). "
                    f"Pemakan terbesar: {top_txt}. Ketik /top lalu /kill <nama.exe> untuk menutup aplikasi berat.",
                )
            )

        battery = t.get("battery_percent")
        if battery is not None and not t.get("battery_plugged", True) and battery <= s.health_battery_alert_percent:
            issues.append(
                (
                    "battery",
                    "Baterai Laptop Lemah",
                    f"Baterai tinggal {battery}% dan charger tidak tercolok. Laptop bisa mati dan akses remote terputus.",
                )
            )

        if t["disk_percent"] >= s.health_disk_alert_percent:
            issues.append(("disk", "Penyimpanan Hampir Penuh", f"Disk sistem terpakai {t['disk_percent']}%."))

        if s.whatsapp_enabled:
            wa = await self.whatsapp.get_status()
            if not wa.get("connected"):
                issues.append(
                    (
                        "whatsapp",
                        "WhatsApp Bridge Terputus",
                        "Bridge WhatsApp tidak terhubung. Jalankan START_ALL.bat atau 5_START_WHATSAPP_BRIDGE.bat.",
                    )
                )

        published: list[dict[str, Any]] = []
        for key, title, message in issues:
            if self._should_alert(key):
                payload = {"key": key, "title": title, "message": message}
                await self.bus.publish("health_alert", payload)
                published.append(payload)

        self.last_snapshot = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "ram_percent": t["ram_percent"],
            "battery_percent": battery,
            "battery_plugged": t.get("battery_plugged"),
            "disk_percent": t["disk_percent"],
            "active_issues": [key for key, _, _ in issues],
        }
        return published
