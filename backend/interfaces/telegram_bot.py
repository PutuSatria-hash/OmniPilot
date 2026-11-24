"""Telegram Bot Remote Controller: text & voice commands, alarm ACK, approvals, and laptop health alerts."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from backend.core.agent_engine import AgentEngine
from backend.core.approval_gate import ApprovalGate
from backend.core.config import Settings
from backend.core.event_bus import EventBus
from backend.modules.pc_control import PCControlService
from backend.modules.scheduler_alarm import SchedulerAlarmService
from backend.modules.voice import VoiceTranscriptionService

logger = logging.getLogger(__name__)


class TelegramRemoteInterface:
    """Runs an authenticated Telegram bot polling loop for instant mobile control."""

    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        agent: AgentEngine,
        scheduler: SchedulerAlarmService,
        approval_gate: ApprovalGate,
        pc_control: PCControlService,
        voice: Optional[VoiceTranscriptionService] = None,
    ) -> None:
        self.settings = settings
        self.bus = bus
        self.agent = agent
        self.scheduler = scheduler
        self.approval_gate = approval_gate
        self.pc_control = pc_control
        self.voice = voice or VoiceTranscriptionService(settings)
        self._app: Any = None
        self._running = False

    def is_configured(self) -> bool:
        return bool(self.settings.telegram_bot_token.strip())

    def _is_authorized(self, user_id: Optional[int]) -> bool:
        allowed = self.settings.allowed_telegram_ids
        if not allowed:
            return True  # First-run convenience; strongly recommend setting TELEGRAM_ALLOWED_USER_ID
        return user_id in allowed

    async def start(self) -> None:
        if not self.is_configured():
            logger.info("Telegram Bot tidak diaktifkan (TELEGRAM_BOT_TOKEN masih kosong).")
            return

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
            from telegram.ext import (
                ApplicationBuilder,
                CallbackQueryHandler,
                CommandHandler,
                ContextTypes,
                MessageHandler,
                filters,
            )
        except ImportError:
            logger.warning("python-telegram-bot belum terpasang.")
            return

        self._app = ApplicationBuilder().token(self.settings.telegram_bot_token.strip()).build()

        async def handle_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.effective_user or not self._is_authorized(update.effective_user.id):
                return
            img_bytes = await asyncio.to_thread(self.pc_control.capture_screenshot_jpeg, 70, 1280)
            if update.message:
                await update.message.reply_photo(photo=img_bytes, caption="Tangkapan layar laptop terkini, Boss.")

        async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.effective_user or not self._is_authorized(update.effective_user.id):
                if update.message:
                    await update.message.reply_text("Akses ditolak. User ID Anda tidak terdaftar.")
                return
            if not update.message or not update.message.text:
                return
            await context.bot.send_chat_action(chat_id=update.message.chat_id, action="typing")
            reply = await self.agent.process_prompt(update.message.text, channel="telegram")
            await update.message.reply_text(reply[:4000])

        async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.effective_user or not self._is_authorized(update.effective_user.id):
                return
            msg = update.message
            if not msg:
                return
            media = msg.voice or msg.audio
            if not media:
                return
            if not self.voice.is_configured():
                await msg.reply_text("Voice note butuh GROQ_API_KEY atau GEMINI_API_KEY di file .env, Boss.")
                return

            await context.bot.send_chat_action(chat_id=msg.chat_id, action="typing")
            try:
                tg_file = await context.bot.get_file(media.file_id)
                audio = bytes(await tg_file.download_as_bytearray())
                result = await self.voice.transcribe(audio, mime_type=getattr(media, "mime_type", None) or "audio/ogg")
            except Exception as exc:
                logger.warning("Transkripsi voice note gagal: %s", exc)
                await msg.reply_text(f"Maaf Boss, voice note gagal ditranskripsi: {str(exc)[:300]}")
                return

            await msg.reply_text(f"Transkrip: {result['text']}")
            reply = await self.agent.process_prompt(result["text"], channel="telegram")
            await msg.reply_text(reply[:4000])

        async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            query = update.callback_query
            if not query or not update.effective_user or not self._is_authorized(update.effective_user.id):
                return
            await query.answer()
            data = query.data or ""

            if data.startswith("ack_alarm:"):
                alarm_id = data.split(":", 1)[1]
                await self.scheduler.acknowledge_alarm(alarm_id, source="telegram")
                await query.edit_message_text(f"Alarm {alarm_id} dimatikan. Terima kasih sudah cek HP, Boss.")
            elif data.startswith("approve:"):
                apr_id = data.split(":", 1)[1]
                res = await self.approval_gate.approve(apr_id)
                await query.edit_message_text(f"Disetujui ({res['status']}), Boss.\nHasil: {res.get('result_text', '-')}")
            elif data.startswith("reject:"):
                apr_id = data.split(":", 1)[1]
                await self.approval_gate.reject(apr_id)
                await query.edit_message_text(f"Aksi {apr_id} dibatalkan oleh Boss.")

        self._app.add_handler(CommandHandler("screen", handle_screen))
        self._app.add_handler(CallbackQueryHandler(handle_callback))
        self._app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
        self._app.add_handler(MessageHandler(filters.TEXT, handle_text))

        async def on_event(event: dict[str, Any]) -> None:
            if not self._app or not self.settings.allowed_telegram_ids:
                return
            ev_type = event["type"]
            payload = event["payload"]

            for chat_id in self.settings.allowed_telegram_ids:
                try:
                    if ev_type in ("alarm_armed", "alarm_warning", "alarm_critical"):
                        prefix = {
                            "alarm_armed": "[PENGINGAT]",
                            "alarm_warning": "[PERINGATAN - BELUM CEK HP]",
                            "alarm_critical": "[ALARM DARURAT AKTIF]",
                        }[ev_type]
                        kb = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("Saya Sudah Cek HP (Matikan Alarm)", callback_data=f"ack_alarm:{payload['id']}")]]
                        )
                        await self._app.bot.send_message(
                            chat_id=chat_id,
                            text=f"{prefix}\n{payload['title']}\n{payload['message']}",
                            reply_markup=kb,
                        )
                    elif ev_type == "approval_requested":
                        kb = InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton("Approve & Jalankan", callback_data=f"approve:{payload['id']}"),
                                    InlineKeyboardButton("Tolak", callback_data=f"reject:{payload['id']}"),
                                ]
                            ]
                        )
                        await self._app.bot.send_message(
                            chat_id=chat_id,
                            text=f"[KONFIRMASI DIBUTUHKAN]\n{payload['title']}\n\n{payload['summary']}",
                            reply_markup=kb,
                        )
                    elif ev_type == "health_alert":
                        await self._app.bot.send_message(
                            chat_id=chat_id,
                            text=f"[PERINGATAN LAPTOP] {payload['title']}\n{payload['message']}",
                        )
                except Exception as exc:
                    logger.warning("Gagal mengirim notifikasi Telegram ke %s: %s", chat_id, exc)

        self.bus.subscribe(on_event)

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        self._running = True
        logger.info("Telegram Remote Interface aktif (teks + voice note).")

    async def stop(self) -> None:
        if self._app and self._running:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._running = False
