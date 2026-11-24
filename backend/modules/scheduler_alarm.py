"""Daily Schedule Manager, Google Calendar ICS Sync, and 3-Stage Escalation Alarm Engine."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

from backend.core.config import Settings
from backend.core.database import Database, utc_now_iso
from backend.core.event_bus import EventBus
from backend.modules.pc_control import PCControlService

logger = logging.getLogger(__name__)


class SchedulerAlarmService:
    """Manages daily schedule briefings, phone-check heartbeats, and dead-man's switch alarms."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        bus: EventBus,
        pc_control: PCControlService,
    ) -> None:
        self.settings = settings
        self.db = db
        self.bus = bus
        self.pc_control = pc_control
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._last_briefing_date: Optional[str] = None

    def _local_now(self) -> datetime:
        try:
            tz = ZoneInfo(self.settings.timezone)
        except Exception:
            tz = timezone(timedelta(hours=8))
        return datetime.now(tz)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop(), name="alarm-watchdog-loop")
        logger.info("SchedulerAlarmService background watchdog started.")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ------------------------------------------------------------------
    # Schedule & Calendar Management
    # ------------------------------------------------------------------
    async def get_today_schedule(self) -> dict[str, Any]:
        """Return today's combined local schedules + Google Calendar ICS events."""
        now = self._local_now()
        today_str = now.strftime("%Y-%m-%d")
        local_events = await self.db.list_schedules(event_date=today_str)
        ics_events = await self._fetch_ics_events_for_date(today_str)

        combined = local_events + ics_events
        combined.sort(key=lambda item: item.get("start_time", "23:59"))
        return {
            "date": today_str,
            "weekday": now.strftime("%A"),
            "timezone": self.settings.timezone,
            "count": len(combined),
            "events": combined,
        }

    async def format_today_briefing(self) -> str:
        """Create a crisp Indonesian daily briefing for Telegram / Web Chat."""
        data = await self.get_today_schedule()
        events = data["events"]
        if not events:
            return (
                f"Jadwal Boss untuk hari ini ({data['date']}):\n"
                "Belum ada agenda tercatat. Boss bisa menambah jadwal lewat dashboard atau perintah chat."
            )

        lines = [f"Jadwal Boss hari ini ({data['date']}) - Total {len(events)} agenda:"]
        for idx, ev in enumerate(events, start=1):
            time_range = ev.get("start_time", "00:00")
            if ev.get("end_time"):
                time_range += f" - {ev['end_time']}"
            alarm_tag = f" [Alarm {ev.get('alarm_timeout_minutes', 5)}m]" if ev.get("alarm_enabled") else ""
            lines.append(f"{idx}. {time_range} | {ev['title']}{alarm_tag}")
            if ev.get("description"):
                lines.append(f"   Catatan: {ev['description']}")
        return "\n".join(lines)

    async def _fetch_ics_events_for_date(self, date_str: str) -> list[dict[str, Any]]:
        """Optionally pull today's events from a private Google Calendar ICS link."""
        ics_url = self.settings.google_calendar_ics_url.strip()
        if not ics_url:
            return []

        events: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(ics_url)
                resp.raise_for_status()
            cal = Calendar.from_ical(resp.content)
            local_tz = self._local_now().tzinfo

            for component in cal.walk("VEVENT"):
                dtstart = component.get("dtstart")
                if not dtstart:
                    continue
                start_val = dtstart.dt
                if isinstance(start_val, datetime):
                    start_local = start_val.astimezone(local_tz) if start_val.tzinfo else start_val
                    ev_date = start_local.strftime("%Y-%m-%d")
                    start_time = start_local.strftime("%H:%M")
                else:
                    ev_date = start_val.strftime("%Y-%m-%d")
                    start_time = "00:00"

                if ev_date != date_str:
                    continue

                dtend = component.get("dtend")
                end_time = ""
                if dtend and isinstance(dtend.dt, datetime):
                    end_local = dtend.dt.astimezone(local_tz) if dtend.dt.tzinfo else dtend.dt
                    end_time = end_local.strftime("%H:%M")

                events.append(
                    {
                        "id": f"gcal_{component.get('uid', len(events))}",
                        "title": str(component.get("summary", "Google Calendar Event")),
                        "description": str(component.get("description", "")),
                        "event_date": ev_date,
                        "start_time": start_time,
                        "end_time": end_time,
                        "category": "google_calendar",
                        "source": "gcal_ics",
                        "alarm_enabled": 1,
                        "alarm_timeout_minutes": self.settings.alarm_default_timeout_minutes,
                    }
                )
        except Exception as exc:
            logger.warning("Gagal sinkronisasi Google Calendar ICS: %s", exc)
        return events

    # ------------------------------------------------------------------
    # Smart Escalation Alarm ("Tidak Cek HP -> Nyalakan Alarm Keras")
    # ------------------------------------------------------------------
    async def arm_escalation_alarm(
        self,
        title: str,
        message: str,
        timeout_minutes: Optional[int] = None,
        schedule_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Arm a 3-stage check-in alarm. Fires critical alarm if Boss doesn't check phone in time."""
        timeout = timeout_minutes or self.settings.alarm_default_timeout_minutes
        deadline = datetime.now(timezone.utc) + timedelta(minutes=timeout)

        alarm = await self.db.create_alarm_watchdog(
            title=title,
            message=message,
            timeout_minutes=timeout,
            deadline_at=deadline.isoformat(),
            schedule_id=schedule_id,
        )

        # Stage 1 notification (friendly ping with countdown)
        await self._dispatch_push_notification(
            title=f"[Pengingat] {title}",
            message=f"{message}\nKonfirmasi cek HP dalam {timeout} menit sebelum alarm darurat berbunyi.",
            priority="default",
            alarm_id=alarm["id"],
        )
        await self.bus.publish("alarm_armed", alarm)
        return alarm

    async def acknowledge_alarm(self, alarm_id: str, source: str = "manual") -> Optional[dict[str, Any]]:
        """Stop an armed/ringing alarm and log phone check activity."""
        await self.db.record_phone_activity(event_type=f"ack_{source}", device_name=source)
        updated = await self.db.update_alarm_state(
            alarm_id=alarm_id,
            status="ACKNOWLEDGED",
            acknowledged_at=utc_now_iso(),
        )
        if updated:
            await self.bus.publish("alarm_acknowledged", updated)
        return updated

    async def acknowledge_all_active_alarms(self, source: str = "phone_check") -> list[dict[str, Any]]:
        """Disarm all active alarms when Boss checks their phone or taps global ACK."""
        active = await self.db.list_active_alarms()
        acked: list[dict[str, Any]] = []
        for alarm in active:
            updated = await self.db.update_alarm_state(
                alarm_id=alarm["id"],
                status="ACKNOWLEDGED",
                acknowledged_at=utc_now_iso(),
            )
            if updated:
                acked.append(updated)
                await self.bus.publish("alarm_acknowledged", updated)
        return acked

    async def register_phone_heartbeat(
        self,
        event_type: str = "screen_unlock",
        device_name: str = "phone",
        battery_pct: Optional[int] = None,
        auto_ack_alarms: bool = True,
    ) -> dict[str, Any]:
        """Record proof that Boss actively checked their phone; optionally disarms waiting timers."""
        record = await self.db.record_phone_activity(
            event_type=event_type,
            device_name=device_name,
            battery_pct=battery_pct,
        )
        disarmed: list[dict[str, Any]] = []
        if auto_ack_alarms:
            # Disarm ARMED/WARNING alarms automatically upon real phone check;
            # CRITICAL alarms require explicit ACK or screen_unlock confirmation
            active = await self.db.list_active_alarms()
            for alarm in active:
                if alarm["status"] in ("ARMED", "WARNING") or event_type == "explicit_ack":
                    updated = await self.db.update_alarm_state(
                        alarm_id=alarm["id"],
                        status="ACKNOWLEDGED",
                        acknowledged_at=utc_now_iso(),
                    )
                    if updated:
                        disarmed.append(updated)
                        await self.bus.publish("alarm_acknowledged", updated)

        payload = {"heartbeat": record, "disarmed_alarms": disarmed}
        await self.bus.publish("phone_heartbeat", payload)
        return payload

    async def get_phone_presence_status(self) -> dict[str, Any]:
        """Return how long ago Boss last checked their phone."""
        latest = await self.db.get_latest_phone_activity()
        if not latest:
            return {
                "seen": False,
                "inactive_minutes": None,
                "is_inactive": True,
                "last_event": None,
            }

        recorded = datetime.fromisoformat(latest["recorded_at"])
        delta_minutes = (datetime.now(timezone.utc) - recorded).total_seconds() / 60.0
        return {
            "seen": True,
            "inactive_minutes": round(delta_minutes, 1),
            "is_inactive": delta_minutes >= self.settings.phone_inactive_threshold_minutes,
            "last_event": latest,
        }

    # ------------------------------------------------------------------
    # Background Watchdog Loop
    # ------------------------------------------------------------------
    async def _watchdog_loop(self) -> None:
        while self._running:
            try:
                await self._check_morning_briefing()
                await self._check_upcoming_schedules()
                await self._evaluate_active_alarms()
            except Exception as exc:
                logger.exception("Watchdog loop error: %s", exc)
            await asyncio.sleep(15)

    async def _check_morning_briefing(self) -> None:
        now = self._local_now()
        today_str = now.strftime("%Y-%m-%d")
        target_hm = self.settings.morning_briefing_time.strip()
        if self._last_briefing_date == today_str:
            return
        if now.strftime("%H:%M") == target_hm:
            self._last_briefing_date = today_str
            briefing = await self.format_today_briefing()
            await self.bus.publish("morning_briefing", {"date": today_str, "text": briefing})
            await self.arm_escalation_alarm(
                title="Morning Briefing Jadwal Hari Ini",
                message=briefing[:300],
                timeout_minutes=self.settings.alarm_default_timeout_minutes,
            )

    async def _check_upcoming_schedules(self) -> None:
        now = self._local_now()
        today_str = now.strftime("%Y-%m-%d")
        schedules = await self.db.list_schedules(event_date=today_str)

        for ev in schedules:
            if not ev.get("alarm_enabled") or ev.get("reminded_today"):
                continue
            try:
                hour, minute = map(int, ev["start_time"].split(":")[:2])
                event_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError:
                continue

            minutes_until = (event_dt - now).total_seconds() / 60.0
            if 0 <= minutes_until <= 10:
                await self.db.mark_schedule_reminded(ev["id"])
                await self.arm_escalation_alarm(
                    title=f"Agenda {ev['start_time']}: {ev['title']}",
                    message=ev.get("description") or f"Jadwal dimulai dalam {int(max(1, minutes_until))} menit.",
                    timeout_minutes=ev.get("alarm_timeout_minutes") or self.settings.alarm_default_timeout_minutes,
                    schedule_id=ev["id"],
                )

    async def _evaluate_active_alarms(self) -> None:
        now_utc = datetime.now(timezone.utc)
        active_alarms = await self.db.list_active_alarms()

        for alarm in active_alarms:
            created_dt = datetime.fromisoformat(alarm["created_at"])
            deadline_dt = datetime.fromisoformat(alarm["deadline_at"])
            total_seconds = max(10.0, (deadline_dt - created_dt).total_seconds())
            elapsed_seconds = (now_utc - created_dt).total_seconds()

            # Stage 2: Halfway Warning
            if alarm["status"] == "ARMED" and elapsed_seconds >= (total_seconds * 0.5) and now_utc < deadline_dt:
                remaining_min = max(1, int((deadline_dt - now_utc).total_seconds() / 60) + 1)
                updated = await self.db.update_alarm_state(alarm["id"], status="WARNING", stage=2)
                await self._dispatch_push_notification(
                    title=f"[PERINGATAN] {alarm['title']}",
                    message=f"Belum ada tanda Boss cek HP. Alarm darurat berbunyi dalam ~{remaining_min} menit!",
                    priority="high",
                    alarm_id=alarm["id"],
                )
                if updated:
                    await self.bus.publish("alarm_warning", updated)

            # Stage 3: CRITICAL ALARM (Timer Expired without Phone Check / ACK)
            elif alarm["status"] in ("ARMED", "WARNING") and now_utc >= deadline_dt:
                updated = await self.db.update_alarm_state(alarm["id"], status="CRITICAL", stage=3)
                await self._trigger_critical_alarm_channels(updated or alarm)
                if updated:
                    await self.bus.publish("alarm_critical", updated)

    async def _trigger_critical_alarm_channels(self, alarm: dict[str, Any]) -> None:
        """Fire loud bypass-silent alarms across all configured phone + PC channels."""
        title = f"ALARM DARURAT: {alarm['title']}"
        body = (
            f"{alarm['message']}\n"
            f"Tidak ada tanda Boss mengecek HP selama {alarm['timeout_minutes']} menit!"
        )

        # 1. ntfy Priority 5 (Max / Urgent)
        await self._dispatch_push_notification(
            title=title,
            message=body,
            priority="max",
            alarm_id=alarm["id"],
        )

        # 2. MacroDroid Direct Webhook (Forces Android Volume 100% + Alarm Sound)
        if self.settings.macrodroid_webhook_url.strip():
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    await client.get(
                        self.settings.macrodroid_webhook_url.strip(),
                        params={"title": alarm["title"], "message": alarm["message"], "alarm_id": alarm["id"]},
                    )
            except Exception as exc:
                logger.warning("MacroDroid webhook gagal: %s", exc)

        # 3. Pushover Emergency Priority 2 (Bypasses Silent & DND on iOS & Android)
        if self.settings.pushover_app_token.strip() and self.settings.pushover_user_key.strip():
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        "https://api.pushover.net/1/messages.json",
                        data={
                            "token": self.settings.pushover_app_token.strip(),
                            "user": self.settings.pushover_user_key.strip(),
                            "title": title,
                            "message": body,
                            "priority": 2,
                            "retry": 30,
                            "expire": 1800,
                            "sound": "siren",
                        },
                    )
            except Exception as exc:
                logger.warning("Pushover Priority 2 gagal: %s", exc)

        # 4. Local Windows PC Backup Siren
        if self.settings.pc_fallback_siren_enabled:
            self.pc_control.play_pc_siren(repeat=4)

    async def _dispatch_push_notification(
        self,
        title: str,
        message: str,
        priority: str,
        alarm_id: str,
    ) -> None:
        topic = self.settings.ntfy_topic.strip()
        if not topic:
            return

        url = f"{self.settings.ntfy_server_url.rstrip('/')}/{topic}"
        headers = {
            "Title": title,
            "Priority": priority,
            "Tags": "rotating_light,alarm_clock" if priority == "max" else "bell,calendar",
        }
        if self.settings.ntfy_token.strip():
            headers["Authorization"] = f"Bearer {self.settings.ntfy_token.strip()}"

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                await client.post(url, content=f"{message}\nID: {alarm_id}".encode("utf-8"), headers=headers)
        except Exception as exc:
            logger.warning("ntfy dispatch gagal: %s", exc)
