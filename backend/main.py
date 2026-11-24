"""OmniPilot Hub - Main FastAPI Application (REST API, WebSocket, PWA Host, & Background Daemons)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.core.agent_engine import AgentEngine
from backend.core.approval_gate import ApprovalGate
from backend.core.config import BASE_DIR, Settings, get_settings
from backend.core.database import Database
from backend.core.event_bus import EventBus
from backend.core.security import require_auth, verify_websocket_token
from backend.interfaces.telegram_bot import TelegramRemoteInterface
from backend.modules.documents import DocumentService
from backend.modules.gmail_service import GmailService
from backend.modules.health_watchdog import HealthWatchdogService
from backend.modules.lms_automation import LMSAutomationService
from backend.modules.pc_control import PCControlService
from backend.modules.scheduler_alarm import SchedulerAlarmService
from backend.modules.voice import VoiceTranscriptionService
from backend.modules.whatsapp_service import WhatsAppService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("omnipilot")


# ----------------------------------------------------------------------
# Request Schemas
# ----------------------------------------------------------------------
class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    channel: str = Field(default="web")


class ScheduleCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    event_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(default="")
    description: str = Field(default="")
    category: str = Field(default="general")
    alarm_enabled: bool = Field(default=True)
    alarm_timeout_minutes: int = Field(default=5, ge=1, le=120)


class AlarmArmRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(default="Mohon konfirmasi cek HP sebelum timer habis.")
    timeout_minutes: int = Field(default=5, ge=1, le=120)


class PhoneHeartbeatRequest(BaseModel):
    event_type: str = Field(default="screen_unlock")
    device_name: str = Field(default="phone")
    battery_pct: Optional[int] = Field(default=None, ge=0, le=100)
    auto_ack_alarms: bool = Field(default=True)


class LaunchAppRequest(BaseModel):
    app_name: str = Field(..., min_length=1)
    target_path: Optional[str] = None


class ShellCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=2000)
    cwd: Optional[str] = None


class MouseActionRequest(BaseModel):
    action: str = Field(..., pattern=r"^(move|click|double_click|right_click|scroll)$")
    x_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    y_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    delta: int = Field(default=0, ge=-1200, le=1200)


class KeyboardActionRequest(BaseModel):
    text: Optional[str] = Field(default=None, max_length=500)
    hotkey: Optional[str] = Field(default=None, max_length=60)


class DocumentSection(BaseModel):
    heading: str = ""
    content: str = ""
    bullets: list[str] = Field(default_factory=list)


class DocumentCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    subtitle: str = ""
    author: str = "Boss"
    fmt: str = Field(default="docx", pattern=r"^(docx|pdf|md)$")
    sections: list[DocumentSection] = Field(default_factory=list)


class GmailSendRequest(BaseModel):
    to: str = Field(..., min_length=3)
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)


class WhatsAppReplyRequest(BaseModel):
    chat_id: str = Field(..., min_length=3)
    contact_name: str = Field(..., min_length=1)
    reply_text: str = Field(..., min_length=1)


class LMSSubmitRequest(BaseModel):
    assignment_url: str = Field(..., min_length=5)
    file_path: str = Field(..., min_length=2)
    notes: str = ""


class RejectRequest(BaseModel):
    reason: str = "Dibatalkan oleh Boss"


# ----------------------------------------------------------------------
# Application Container & Factory
# ----------------------------------------------------------------------
class AppContainer:
    """Holds all singleton modular services with explicit dependency injection."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self.bus = EventBus()
        self.approval_gate = ApprovalGate(self.db, self.bus)
        self.pc_control = PCControlService(settings)
        self.scheduler = SchedulerAlarmService(settings, self.db, self.bus, self.pc_control)
        self.documents = DocumentService(settings)
        self.gmail = GmailService(settings)
        self.lms = LMSAutomationService(settings)
        self.whatsapp = WhatsAppService(settings)
        self.voice = VoiceTranscriptionService(settings)
        self.health_watchdog = HealthWatchdogService(
            settings=settings,
            bus=self.bus,
            pc_control=self.pc_control,
            whatsapp=self.whatsapp,
        )
        self.agent = AgentEngine(
            settings=settings,
            db=self.db,
            approval_gate=self.approval_gate,
            scheduler=self.scheduler,
            pc_control=self.pc_control,
            documents=self.documents,
            gmail=self.gmail,
            lms=self.lms,
            whatsapp=self.whatsapp,
        )
        self.telegram = TelegramRemoteInterface(
            settings=settings,
            bus=self.bus,
            agent=self.agent,
            scheduler=self.scheduler,
            approval_gate=self.approval_gate,
            pc_control=self.pc_control,
            voice=self.voice,
        )

        # Register protected executors on Approval Gate
        self.approval_gate.register_executor("send_gmail", self.gmail.execute_send_email)
        self.approval_gate.register_executor("reply_whatsapp", self.whatsapp.execute_reply)
        self.approval_gate.register_executor("submit_lms", self.lms.execute_submit_assignment)
        self.approval_gate.register_executor("pc_shell_command", self._execute_approved_shell)
        self.approval_gate.register_executor("close_process", self._execute_approved_close_process)

    async def _execute_approved_shell(self, payload: dict[str, Any]) -> str:
        res = await self.pc_control.execute_shell_raw(
            command=payload["command"], cwd=payload.get("cwd")
        )
        return f"Exit {res['exit_code']} | {res['stdout'] or res['stderr'] or 'Selesai'}"

    async def _execute_approved_close_process(self, payload: dict[str, Any]) -> str:
        pids = [int(p) for p in payload.get("pids", [])]
        return await asyncio.to_thread(self.pc_control.close_processes, pids)

    async def startup(self, start_daemons: bool = True) -> None:
        await self.db.connect()
        if start_daemons:
            self.scheduler.start()
            self.health_watchdog.start()
            await self.telegram.start()

    async def shutdown(self) -> None:
        await self.telegram.stop()
        await self.health_watchdog.stop()
        await self.scheduler.stop()
        await self.db.close()


def create_app(settings_override: Optional[Settings] = None, start_daemons: bool = True) -> FastAPI:
    settings = settings_override or get_settings()
    container = AppContainer(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await container.startup(start_daemons=start_daemons)
        logger.info("OmniPilot Hub berjalan di http://%s:%s", settings.host, settings.port)
        yield
        await container.shutdown()

    app = FastAPI(
        title="OmniPilot Hub",
        description="Personal AI Automation, Smart Alarm Watchdog & Remote PC Command Center",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.container = container

    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Override settings dependency if custom settings provided (e.g., tests)
    if settings_override is not None:
        app.dependency_overrides[get_settings] = lambda: settings_override

    # ------------------------------------------------------------------
    # Health & System Overview
    # ------------------------------------------------------------------
    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "OmniPilot Hub"}

    @app.get("/api/status", dependencies=[Depends(require_auth)])
    async def system_status() -> dict[str, Any]:
        return {
            "telemetry": container.pc_control.get_telemetry(),
            "phone_presence": await container.scheduler.get_phone_presence_status(),
            "today_schedule": await container.scheduler.get_today_schedule(),
            "active_alarms": await container.db.list_active_alarms(),
            "pending_approvals": await container.db.list_approvals(status="PENDING"),
            "modules": {
                "gemini_ai": container.agent.has_any_ai_provider(),
                "ai_providers": container.agent.get_configured_providers(),
                "last_ai_model": container.agent.last_used_model,
                "telegram_bot": container.telegram.is_configured(),
                "gmail": container.gmail.get_status(),
                "lms": container.lms.get_status(),
                "whatsapp": await container.whatsapp.get_status(),
                "alarm_channels": {
                    "ntfy": bool(settings.ntfy_topic.strip()),
                    "macrodroid": bool(settings.macrodroid_webhook_url.strip()),
                    "pushover": bool(settings.pushover_app_token.strip() and settings.pushover_user_key.strip()),
                    "pc_siren": settings.pc_fallback_siren_enabled,
                },
            },
        }

    # ------------------------------------------------------------------
    # AI Chat & Remote Prompt
    # ------------------------------------------------------------------
    @app.post("/api/chat", dependencies=[Depends(require_auth)])
    async def chat_prompt(req: ChatRequest) -> dict[str, Any]:
        reply = await container.agent.process_prompt(req.prompt, channel=req.channel)
        return {"reply": reply}

    @app.get("/api/chat/history", dependencies=[Depends(require_auth)])
    async def chat_history() -> dict[str, Any]:
        return {"messages": await container.db.list_chat_messages(limit=50)}

    # ------------------------------------------------------------------
    # Schedules & Daily Briefing
    # ------------------------------------------------------------------
    @app.get("/api/schedules/today", dependencies=[Depends(require_auth)])
    async def schedules_today() -> dict[str, Any]:
        data = await container.scheduler.get_today_schedule()
        data["briefing"] = await container.scheduler.format_today_briefing()
        return data

    @app.get("/api/schedules", dependencies=[Depends(require_auth)])
    async def list_schedules(event_date: Optional[str] = None) -> dict[str, Any]:
        return {"events": await container.db.list_schedules(event_date=event_date)}

    @app.post("/api/schedules", dependencies=[Depends(require_auth)])
    async def create_schedule(req: ScheduleCreateRequest) -> dict[str, Any]:
        item = await container.db.add_schedule(
            title=req.title,
            event_date=req.event_date,
            start_time=req.start_time,
            end_time=req.end_time,
            description=req.description,
            category=req.category,
            alarm_enabled=req.alarm_enabled,
            alarm_timeout_minutes=req.alarm_timeout_minutes,
        )
        await container.bus.publish("schedule_updated", item)
        return item

    @app.delete("/api/schedules/{item_id}", dependencies=[Depends(require_auth)])
    async def delete_schedule(item_id: str) -> dict[str, Any]:
        deleted = await container.db.delete_schedule(item_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Jadwal tidak ditemukan.")
        return {"deleted": True, "id": item_id}

    # ------------------------------------------------------------------
    # Smart Escalation Alarms & Phone Check Heartbeat
    # ------------------------------------------------------------------
    @app.get("/api/alarms", dependencies=[Depends(require_auth)])
    async def list_alarms() -> dict[str, Any]:
        return {
            "active": await container.db.list_active_alarms(),
            "recent": await container.db.list_recent_alarms(limit=20),
            "phone_presence": await container.scheduler.get_phone_presence_status(),
        }

    @app.post("/api/alarms/arm", dependencies=[Depends(require_auth)])
    async def arm_alarm(req: AlarmArmRequest) -> dict[str, Any]:
        return await container.scheduler.arm_escalation_alarm(
            title=req.title,
            message=req.message,
            timeout_minutes=req.timeout_minutes,
        )

    @app.post("/api/alarms/{alarm_id}/ack", dependencies=[Depends(require_auth)])
    async def ack_alarm(alarm_id: str) -> dict[str, Any]:
        updated = await container.scheduler.acknowledge_alarm(alarm_id, source="api_ack")
        if not updated:
            raise HTTPException(status_code=404, detail="Alarm tidak ditemukan.")
        return updated

    @app.post("/api/alarms/ack-all", dependencies=[Depends(require_auth)])
    async def ack_all_alarms() -> dict[str, Any]:
        acked = await container.scheduler.acknowledge_all_active_alarms(source="api_ack_all")
        return {"acknowledged_count": len(acked), "alarms": acked}

    @app.post("/api/phone/heartbeat", dependencies=[Depends(require_auth)])
    async def phone_heartbeat(req: PhoneHeartbeatRequest) -> dict[str, Any]:
        return await container.scheduler.register_phone_heartbeat(
            event_type=req.event_type,
            device_name=req.device_name,
            battery_pct=req.battery_pct,
            auto_ack_alarms=req.auto_ack_alarms,
        )

    # ------------------------------------------------------------------
    # Human-in-the-Loop Approval Gate
    # ------------------------------------------------------------------
    @app.get("/api/approvals", dependencies=[Depends(require_auth)])
    async def list_approvals(status: Optional[str] = None) -> dict[str, Any]:
        return {"approvals": await container.db.list_approvals(status=status)}

    @app.post("/api/approvals/{approval_id}/approve", dependencies=[Depends(require_auth)])
    async def approve_action(approval_id: str) -> dict[str, Any]:
        try:
            return await container.approval_gate.approve(approval_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/api/approvals/{approval_id}/reject", dependencies=[Depends(require_auth)])
    async def reject_action(approval_id: str, req: RejectRequest) -> dict[str, Any]:
        try:
            return await container.approval_gate.reject(approval_id, reason=req.reason)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # ------------------------------------------------------------------
    # PC Control & Live Screen Preview
    # ------------------------------------------------------------------
    @app.get("/api/pc/telemetry", dependencies=[Depends(require_auth)])
    async def pc_telemetry() -> dict[str, Any]:
        return container.pc_control.get_telemetry()

    @app.get("/api/pc/screenshot", dependencies=[Depends(require_auth)])
    async def pc_screenshot(quality: int = 65, max_width: int = 1280) -> Response:
        jpeg_bytes = await asyncio.to_thread(
            container.pc_control.capture_screenshot_jpeg,
            max(20, min(95, quality)),
            max(480, min(1920, max_width)),
        )
        return Response(content=jpeg_bytes, media_type="image/jpeg")

    @app.post("/api/pc/launch", dependencies=[Depends(require_auth)])
    async def pc_launch(req: LaunchAppRequest) -> dict[str, Any]:
        try:
            return container.pc_control.launch_app(req.app_name, req.target_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/pc/command", dependencies=[Depends(require_auth)])
    async def pc_command(req: ShellCommandRequest) -> dict[str, Any]:
        return await container.pc_control.run_shell_command(
            command=req.command,
            approval_gate=container.approval_gate,
            cwd=req.cwd,
        )

    @app.post("/api/pc/mouse", dependencies=[Depends(require_auth)])
    async def pc_mouse(req: MouseActionRequest) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                container.pc_control.perform_mouse_action,
                req.action,
                req.x_ratio,
                req.y_ratio,
                req.delta,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/pc/keyboard", dependencies=[Depends(require_auth)])
    async def pc_keyboard(req: KeyboardActionRequest) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                container.pc_control.perform_keyboard_action,
                req.text,
                req.hotkey,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/pc/lock", dependencies=[Depends(require_auth)])
    async def pc_lock() -> dict[str, Any]:
        return await asyncio.to_thread(container.pc_control.lock_workstation)

    # ------------------------------------------------------------------
    # Documents, Gmail, WhatsApp, LMS
    # ------------------------------------------------------------------
    @app.get("/api/documents", dependencies=[Depends(require_auth)])
    async def list_documents() -> dict[str, Any]:
        return {"documents": container.documents.list_documents()}

    @app.post("/api/documents", dependencies=[Depends(require_auth)])
    async def create_document(req: DocumentCreateRequest) -> dict[str, Any]:
        sections = [s.model_dump() for s in req.sections] or [
            {"heading": "Ringkasan", "content": "Dokumen dibuat otomatis oleh OmniPilot Hub."}
        ]
        return container.documents.create_document(
            title=req.title,
            sections=sections,
            fmt=req.fmt,
            author=req.author,
            subtitle=req.subtitle,
        )

    @app.get("/api/documents/download/{filename}", dependencies=[Depends(require_auth)])
    async def download_document(filename: str) -> FileResponse:
        try:
            path = container.documents.resolve_document_path(filename)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return FileResponse(path=str(path), filename=path.name)

    @app.get("/api/gmail/unread", dependencies=[Depends(require_auth)])
    async def gmail_unread() -> dict[str, Any]:
        return await container.gmail.list_unread()

    @app.post("/api/gmail/send", dependencies=[Depends(require_auth)])
    async def gmail_send(req: GmailSendRequest) -> dict[str, Any]:
        return await container.gmail.queue_send_email(
            to=req.to,
            subject=req.subject,
            body=req.body,
            approval_gate=container.approval_gate,
        )

    @app.get("/api/whatsapp/status", dependencies=[Depends(require_auth)])
    async def wa_status() -> dict[str, Any]:
        return await container.whatsapp.get_status()

    @app.get("/api/whatsapp/unread", dependencies=[Depends(require_auth)])
    async def wa_unread() -> dict[str, Any]:
        return await container.whatsapp.get_unread_messages()

    @app.post("/api/whatsapp/reply", dependencies=[Depends(require_auth)])
    async def wa_reply(req: WhatsAppReplyRequest) -> dict[str, Any]:
        return await container.whatsapp.queue_reply(
            chat_id=req.chat_id,
            contact_name=req.contact_name,
            reply_text=req.reply_text,
            approval_gate=container.approval_gate,
        )

    @app.get("/api/lms/status", dependencies=[Depends(require_auth)])
    async def lms_status() -> dict[str, Any]:
        return container.lms.get_status()

    @app.post("/api/lms/inspect", dependencies=[Depends(require_auth)])
    async def lms_inspect(target_url: Optional[str] = None) -> dict[str, Any]:
        return await container.lms.inspect_dashboard(target_url=target_url)

    @app.post("/api/lms/submit", dependencies=[Depends(require_auth)])
    async def lms_submit(req: LMSSubmitRequest) -> dict[str, Any]:
        try:
            return await container.lms.queue_submit_assignment(
                assignment_url=req.assignment_url,
                file_path=req.file_path,
                notes=req.notes,
                approval_gate=container.approval_gate,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # ------------------------------------------------------------------
    # Real-Time WebSocket Stream
    # ------------------------------------------------------------------
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        if not await verify_websocket_token(websocket, settings):
            await websocket.close(code=4401)
            return

        await websocket.accept()
        queue = container.bus.register_ws_queue()
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            container.bus.unregister_ws_queue(queue)

    # ------------------------------------------------------------------
    # Mount Weightless Glassmorphism Mobile-First PWA Frontend
    # ------------------------------------------------------------------
    frontend_dir: Path = BASE_DIR / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run("backend.main:app", host=cfg.host, port=cfg.port, reload=False)
