"""AI Agent Orchestrator: Multi-Turn Memory + Multi-Provider Free Waterfall (Gemini, Groq, Cerebras, OpenRouter, Mistral, Ollama)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

import httpx

from backend.core.approval_gate import ApprovalGate
from backend.core.config import Settings, parse_csv
from backend.core.database import Database
from backend.core.runtime_state import load_runtime_state
from backend.modules.documents import DocumentService
from backend.modules.gmail_service import GmailService
from backend.modules.lms_automation import LMSAutomationService
from backend.modules.pc_control import PCControlService
from backend.modules.scheduler_alarm import SchedulerAlarmService
from backend.modules.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

_parse_csv = parse_csv  # backward-compatible alias

MAX_TOOL_ROUNDS = 4
MAX_HISTORY_CHARS = 1500
RETRYABLE_MARKERS = (
    "500",
    "502",
    "503",
    "504",
    "429",
    "404",
    "UNAVAILABLE",
    "RESOURCE_EXHAUSTED",
    "NOT_FOUND",
    "DEADLINE_EXCEEDED",
    "timed out",
    "Timeout",
)

SYSTEM_INSTRUCTION = """Kamu adalah OmniPilot, asisten AI otomasi pribadi profesional untuk Boss.
Aturan wajib:
1. Selalu panggil pengguna dengan sebutan "Boss".
2. Jangan gunakan emoji berlebihan; gunakan gaya bahasa Indonesia yang ringkas, rapi, dan jelas.
3. Gunakan tools yang tersedia untuk mengecek jadwal, memasang pengingat, membuat dokumen, mengecek/mengirim Gmail (lewat approval), merangkum/membalas WhatsApp (lewat approval), mengontrol PC, menutup aplikasi berat (lewat approval), atau mengecek LMS.
4. Untuk aksi sensitif (kirim email, balas WhatsApp, submit LMS, perintah terminal berisiko, menutup aplikasi), informasikan bahwa aksi sudah masuk Approval Gate agar Boss bisa klik Approve dari HP.
5. Perhatikan riwayat percakapan sebelumnya agar jawaban nyambung (misalnya "revisi yang tadi", "balas dia").
6. Jika Boss menyebut fakta/preferensi pribadi yang berguna jangka panjang (kampus, jurusan, format dokumen favorit, kontak penting), simpan dengan tool remember_fact.
"""

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "launch_pc_application",
        "description": "Membuka aplikasi di laptop Windows Boss: antigravity, vscode, chrome, edge, terminal, explorer, rustdesk.",
        "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]},
    },
    {
        "name": "generate_document",
        "description": "Membuat dokumen tugas/laporan dalam format docx, pdf, atau md.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "fmt": {"type": "string", "enum": ["docx", "pdf", "md"]},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "get_pc_status",
        "description": "Mengambil status CPU, RAM, baterai, dan IP Tailscale laptop Boss.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "add_schedule_item",
        "description": "Menambahkan jadwal baru (start_time format HH:MM, event_date YYYY-MM-DD kosong=hari ini).",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_time": {"type": "string"},
                "event_date": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["title", "start_time"],
        },
    },
    {
        "name": "arm_timer_reminder",
        "description": "Memasang pengingat / timer alarm untuk Boss.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "timeout_minutes": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "run_pc_shell",
        "description": "Menjalankan perintah PowerShell di laptop Boss (perintah berbahaya otomatis masuk Approval Gate).",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    },
    {
        "name": "check_lms_dashboard",
        "description": "Mengecek halaman LMS dan mendeteksi daftar tugas/deadline aktif.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "queue_gmail_send",
        "description": "Menyiapkan draft kirim Gmail yang wajib disetujui Boss lewat Approval Gate.",
        "parameters": {
            "type": "object",
            "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "check_unread_whatsapp",
        "description": "Membaca pesan WhatsApp belum dibaca dari bridge lokal untuk dirangkum.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "queue_whatsapp_reply",
        "description": "Menyiapkan draft balasan WhatsApp yang wajib disetujui Boss lewat Approval Gate (aman anti-ban).",
        "parameters": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "ID chat dari hasil check_unread_whatsapp."},
                "contact_name": {"type": "string"},
                "reply_text": {"type": "string"},
            },
            "required": ["chat_id", "contact_name", "reply_text"],
        },
    },
    {
        "name": "lock_laptop_screen",
        "description": "Mengunci layar Windows laptop rumah Boss secara instan.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_heavy_processes",
        "description": "Menampilkan aplikasi yang paling banyak memakan RAM di laptop Boss.",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "request_close_process",
        "description": "Meminta penutupan aplikasi berat berdasarkan nama exe (misal chrome.exe) atau PID; wajib Approve Boss.",
        "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
    },
    {
        "name": "remember_fact",
        "description": "Menyimpan fakta/preferensi jangka panjang tentang Boss ke memori permanen.",
        "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]},
    },
]

OPENAI_TOOL_SCHEMAS: list[dict[str, Any]] = [{"type": "function", "function": spec} for spec in TOOL_SPECS]


def _is_retryable(err: str) -> bool:
    return any(marker in err for marker in RETRYABLE_MARKERS)


def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Map DB chat rows to alternating user/assistant turns (merging consecutive same-role turns)."""
    turns: list[dict[str, str]] = []
    for row in history:
        role = "assistant" if row.get("role") == "assistant" else "user"
        content = str(row.get("content", "")).strip()[:MAX_HISTORY_CHARS]
        if not content:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] = f"{turns[-1]['content']}\n{content}"[: MAX_HISTORY_CHARS * 2]
        else:
            turns.append({"role": role, "content": content})
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return turns


def _summarize_tool_log(tool_log: list[str]) -> str:
    lines = "\n".join(f"- {item}" for item in tool_log[-6:])
    return f"Aksi sudah dijalankan, Boss (model AI terputus sebelum sempat merangkum):\n{lines}"


class AgentEngine:
    """Unified prompt router with conversation memory, cascading free-tier AI failover, and offline slash commands."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        approval_gate: ApprovalGate,
        scheduler: SchedulerAlarmService,
        pc_control: PCControlService,
        documents: DocumentService,
        gmail: GmailService,
        lms: LMSAutomationService,
        whatsapp: WhatsAppService,
    ) -> None:
        self.settings = settings
        self.db = db
        self.approval_gate = approval_gate
        self.scheduler = scheduler
        self.pc_control = pc_control
        self.documents = documents
        self.gmail = gmail
        self.lms = lms
        self.whatsapp = whatsapp
        self.last_used_model: Optional[str] = None

    # ------------------------------------------------------------------
    # Provider Discovery
    # ------------------------------------------------------------------
    def get_configured_providers(self) -> list[dict[str, Any]]:
        """List all AI providers currently configured in .env in waterfall priority order."""
        providers: list[dict[str, Any]] = []
        if self.settings.gemini_api_key.strip():
            providers.append(
                {"provider": "gemini", "models": parse_csv(f"{self.settings.gemini_model},{self.settings.gemini_fallback_models}")}
            )
        if self.settings.groq_api_key.strip():
            providers.append({"provider": "groq", "models": parse_csv(self.settings.groq_models)})
        if self.settings.cerebras_api_key.strip():
            providers.append({"provider": "cerebras", "models": parse_csv(self.settings.cerebras_models)})
        if self.settings.openrouter_api_key.strip():
            providers.append({"provider": "openrouter", "models": parse_csv(self.settings.openrouter_models)})
        if self.settings.mistral_api_key.strip():
            providers.append({"provider": "mistral", "models": parse_csv(self.settings.mistral_models)})
        if self.settings.ollama_model.strip():
            providers.append({"provider": "ollama", "models": parse_csv(self.settings.ollama_model)})
        return providers

    def has_any_ai_provider(self) -> bool:
        return len(self.get_configured_providers()) > 0

    # ------------------------------------------------------------------
    # Entry Point
    # ------------------------------------------------------------------
    async def process_prompt(self, prompt: str, channel: str = "web") -> str:
        """Process a prompt from Web PWA / Telegram / Voice with per-channel conversation memory."""
        text = prompt.strip()
        if not text:
            return "Siap, Boss. Kirimkan perintah atau ketik /help untuk melihat daftar aksi cepat."

        history = await self.db.list_chat_messages(limit=self.settings.chat_history_turns, channel=channel)
        await self.db.add_chat_message(channel=channel, role="user", content=text)

        await self.scheduler.register_phone_heartbeat(
            event_type=f"chat_{channel}",
            device_name=channel,
            auto_ack_alarms=True,
        )

        if text.startswith("/"):
            reply = await self._handle_slash_command(text, channel=channel)
        elif self.has_any_ai_provider():
            try:
                reply = await self._run_ai_waterfall(text, history)
            except Exception as exc:
                logger.exception("All configured AI providers failed: %s", exc)
                reply = await self._handle_natural_fallback(text, api_error=str(exc))
        else:
            reply = await self._handle_natural_fallback(text)

        await self.db.add_chat_message(channel=channel, role="assistant", content=reply)
        return reply

    # ------------------------------------------------------------------
    # Slash Commands (offline, deterministic)
    # ------------------------------------------------------------------
    async def _handle_slash_command(self, text: str, channel: str = "web") -> str:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/help", "/start"):
            return (
                "Siap, Boss. Daftar perintah cepat OmniPilot Hub:\n"
                "- /jadwal : Lihat jadwal hari ini\n"
                "- /tambah_jadwal HH:MM Judul : Tambah jadwal dengan smart alarm\n"
                "- /alarm <menit> <judul> : Pasang timer cek HP\n"
                "- /ack : Matikan semua alarm aktif\n"
                "- /pc : Status CPU, RAM, baterai, IP Tailscale\n"
                "- /top : Aplikasi pemakan RAM terbesar\n"
                "- /kill <nama.exe|PID> : Tutup aplikasi berat (wajib Approve)\n"
                "- /screen : Tangkapan layar laptop\n"
                "- /tunnel : Link HTTPS untuk PC Lab Kampus\n"
                "- /ingat <fakta> | /memori | /lupa <id> : Kelola memori AI\n"
                "- /reset : Bersihkan riwayat percakapan channel ini\n"
                "- /models : Daftar provider & model AI aktif\n"
                "- /buka <antigravity|vscode|chrome|terminal|explorer> : Buka aplikasi\n"
                "- /run <perintah powershell> : Jalankan perintah terminal\n"
                "- /doc <Judul> | <Isi> : Buat dokumen DOCX\n"
                "- /gmail | /wa | /lms : Cek email, WhatsApp, dan tugas LMS\n"
                "Tips: kirim voice note di Telegram untuk memberi perintah dengan suara."
            )

        if cmd == "/models":
            configured = self.get_configured_providers()
            if not configured:
                return "Belum ada provider AI di .env, Boss. Isi GEMINI_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY, atau OPENROUTER_API_KEY."
            lines = [f"Waterfall AI Aktif ({len(configured)} provider):"]
            for idx, p in enumerate(configured, start=1):
                lines.append(f"{idx}. {p['provider'].upper()}: {', '.join(p['models'])}")
            lines.append(f"Model terakhir merespons: {self.last_used_model or 'Belum ada'}")
            lines.append(f"Memori percakapan: {self.settings.chat_history_turns} pesan terakhir per channel")
            return "\n".join(lines)

        if cmd == "/ingat":
            if not arg:
                return "Format: /ingat <fakta>, contoh: /ingat Saya kuliah Teknik Informatika semester 5"
            fact = await self.db.add_memory_fact(arg)
            return f"Siap, Boss. Memori tersimpan [{fact['id']}]: {fact['fact']}"

        if cmd == "/memori":
            facts = await self.db.list_memory_facts()
            if not facts:
                return "Belum ada memori tersimpan, Boss. Tambahkan dengan /ingat <fakta>."
            lines = ["Memori & preferensi Boss yang diingat AI:"]
            lines.extend(f"[{f['id']}] {f['fact']}" for f in facts)
            lines.append("Hapus satu memori: /lupa <id>")
            return "\n".join(lines)

        if cmd == "/lupa":
            if not arg.isdigit():
                return "Format: /lupa <id> (lihat id dengan /memori)"
            deleted = await self.db.delete_memory_fact(int(arg))
            return f"Memori [{arg}] dihapus, Boss." if deleted else f"Memori [{arg}] tidak ditemukan."

        if cmd == "/reset":
            count = await self.db.clear_chat_messages(channel)
            return f"Riwayat percakapan channel '{channel}' dibersihkan ({count} pesan dihapus). Memori fakta tetap tersimpan."

        if cmd == "/tunnel":
            url = load_runtime_state().get("tunnel_url") or self.settings.campus_tunnel_url
            if not url:
                return "Tunnel PC Lab belum aktif, Boss. Jalankan START_ALL.bat di laptop rumah."
            return f"Link PC Lab Kampus aktif:\n{url}\nBuka di Incognito, centang 'Mode PC Lab / Umum', lalu Logout setelah selesai."

        if cmd == "/top":
            procs = await asyncio.to_thread(self.pc_control.list_top_processes, 8)
            t = self.pc_control.get_telemetry()
            lines = [f"Aplikasi pemakan RAM terbesar (RAM terpakai {t['ram_percent']}%):"]
            for idx, p in enumerate(procs, start=1):
                tag = " [dilindungi]" if p["protected"] else ""
                lines.append(f"{idx}. {p['name']} — {p['memory_mb']:,.0f} MB ({p['count']} proses){tag}")
            lines.append("Tutup aplikasi: /kill <nama.exe> atau /kill <PID> (wajib Approve).")
            return "\n".join(lines)

        if cmd == "/kill":
            if not arg:
                return "Format: /kill chrome.exe atau /kill 1234"
            try:
                res = await self.pc_control.request_close_process(arg, self.approval_gate)
            except (PermissionError, LookupError, ValueError) as exc:
                return f"Tidak bisa diproses, Boss: {exc}"
            return f"{res['message']} (Approval ID: {res['approval_id']})"

        if cmd == "/jadwal":
            return await self.scheduler.format_today_briefing()

        if cmd == "/tambah_jadwal":
            match = re.match(r"^(\d{1,2}:\d{2})\s+(.+)$", arg)
            if not match:
                return "Format: /tambah_jadwal 14:00 Kuliah Pemrograman"
            start_time, title = match.group(1).zfill(5), match.group(2).strip()
            ev = await self.db.add_schedule(
                title=title,
                event_date=datetime.now().strftime("%Y-%m-%d"),
                start_time=start_time,
                alarm_enabled=True,
                alarm_timeout_minutes=self.settings.alarm_default_timeout_minutes,
            )
            return (
                f"Jadwal tersimpan, Boss: [{ev['start_time']}] {ev['title']} "
                f"(Smart Alarm aktif, eskalasi jika tidak cek HP dalam {ev['alarm_timeout_minutes']} menit)."
            )

        if cmd == "/alarm":
            match = re.match(r"^(\d+)\s+(.+)$", arg)
            if match:
                minutes = max(1, min(120, int(match.group(1))))
                title = match.group(2).strip()
            else:
                minutes = self.settings.alarm_default_timeout_minutes
                title = arg or "Cek HP & Agenda Penting"
            alarm = await self.scheduler.arm_escalation_alarm(
                title=title,
                message=f"Timer pengecekan HP aktif selama {minutes} menit.",
                timeout_minutes=minutes,
            )
            return (
                f"Smart Escalation Alarm aktif, Boss (ID: {alarm['id']}).\n"
                f"Judul: {title}\n"
                f"Jika tidak ada tanda cek HP / ACK dalam {minutes} menit, alarm darurat akan berbunyi."
            )

        if cmd == "/ack":
            acked = await self.scheduler.acknowledge_all_active_alarms(source="slash_ack")
            if not acked:
                return "Tidak ada alarm aktif saat ini, Boss. Status kehadiran HP sudah diperbarui."
            return f"Siap, Boss. {len(acked)} alarm aktif berhasil dimatikan dan dikonfirmasi."

        if cmd == "/pc":
            t = self.pc_control.get_telemetry()
            batt = (
                f"{t['battery_percent']}% ({'Charging' if t['battery_plugged'] else 'Battery'})"
                if t["battery_percent"] is not None
                else "Desktop/AC"
            )
            return (
                f"Status PC ({t['hostname']} - {t['os']}):\n"
                f"- CPU: {t['cpu_percent']}% | RAM: {t['ram_percent']}% ({t['ram_used_gb']}/{t['ram_total_gb']} GB)\n"
                f"- Disk: {t['disk_percent']}% | Baterai: {batt}\n"
                f"- Local IP: {t['local_ip']} | Tailscale IP: {t['tailscale_ip'] or 'Belum aktif'}"
            )

        if cmd == "/screen":
            return "Siap, Boss. Membuka pratinjau layar laptop terbaru di tab 'PC & Layar' (untuk gambar langsung di chat, gunakan /screen di Telegram Bot)."

        if cmd == "/buka":
            if not arg:
                return "Format: /buka antigravity | vscode | chrome | terminal | explorer | rustdesk"
            try:
                res = self.pc_control.launch_app(arg)
                return f"Berhasil membuka {res['app']} di PC (workspace: {res['workspace']}), Boss."
            except Exception as exc:
                return f"Gagal membuka aplikasi: {exc}"

        if cmd == "/run":
            if not arg:
                return "Format: /run <perintah powershell>"
            res = await self.pc_control.run_shell_command(arg, self.approval_gate)
            if res.get("status") == "pending_approval":
                return f"{res['message']} (Approval ID: {res['approval_id']})"
            out = res.get("stdout") or res.get("stderr") or "(tidak ada output)"
            return f"Hasil perintah (exit {res.get('exit_code')}):\n```\n{out[:1500]}\n```"

        if cmd == "/doc":
            if "|" in arg:
                title, body = [x.strip() for x in arg.split("|", 1)]
            else:
                title = arg or "Dokumen Tugas"
                body = "Draft awal dokumen dibuat otomatis oleh OmniPilot Hub."
            doc = self.documents.create_document(
                title=title,
                sections=[{"heading": "Isi Utama", "content": body}],
                fmt="docx",
            )
            return f"Dokumen DOCX berhasil dibuat, Boss: {doc['filename']} ({doc['size_bytes']} bytes)."

        if cmd == "/gmail":
            data = await self.gmail.list_unread()
            if not data.get("ready"):
                return f"Gmail API lokal belum dihubungkan, Boss.\n{data.get('note')}"
            msgs = data.get("messages", [])
            if not msgs:
                return "Tidak ada email baru yang belum dibaca di Inbox, Boss."
            lines = [f"Ringkasan {len(msgs)} Gmail belum dibaca:"]
            for idx, m in enumerate(msgs, start=1):
                lines.append(f"{idx}. {m['subject']} — dari {m['from']}\n   {m['snippet'][:120]}")
            return "\n".join(lines)

        if cmd == "/wa":
            data = await self.whatsapp.get_unread_messages()
            if not data.get("connected"):
                return f"WhatsApp Bridge belum tersambung, Boss.\n{data.get('note', '')}"
            msgs = data.get("messages", [])
            if not msgs:
                return "Tidak ada pesan WhatsApp belum dibaca saat ini, Boss."
            lines = [f"Rangkuman {len(msgs)} pesan WhatsApp belum dibaca:"]
            for idx, m in enumerate(msgs[:10], start=1):
                lines.append(f"{idx}. {m.get('sender', 'Kontak')}: {m.get('body', '')[:120]}")
            return "\n".join(lines)

        if cmd == "/lms":
            res = await self.lms.inspect_dashboard()
            if res.get("status") != "ok":
                return f"Info LMS: {res.get('message')}"
            items = res.get("detected_items", [])
            if not items:
                return f"Halaman LMS '{res.get('page_title')}' berhasil dicek, tidak terdeteksi item tugas aktif."
            lines = [f"Item tugas terdeteksi di LMS ({res.get('page_title')}):"]
            for idx, item in enumerate(items[:8], start=1):
                lines.append(f"{idx}. {item['text']}")
            return "\n".join(lines)

        return f"Perintah '{cmd}' tidak dikenali, Boss. Ketik /help untuk daftar perintah."

    async def _handle_natural_fallback(self, text: str, api_error: Optional[str] = None) -> str:
        lowered = text.lower()
        if any(k in lowered for k in ("jadwal", "agenda", "hari ini", "schedule")):
            return await self.scheduler.format_today_briefing()
        if any(k in lowered for k in ("alarm", "ingatkan", "bangunkan", "timer")):
            m = re.search(r"(\d+)\s*(menit|m|min)", lowered)
            minutes = int(m.group(1)) if m else self.settings.alarm_default_timeout_minutes
            alarm = await self.scheduler.arm_escalation_alarm(
                title=text[:80],
                message="Dipasang melalui perintah chat.",
                timeout_minutes=minutes,
            )
            return (
                f"Smart Alarm diaktifkan untuk {minutes} menit (ID: {alarm['id']}), Boss. "
                "Jika tidak ada tanda cek HP sampai timer habis, alarm darurat akan berbunyi."
            )
        if any(k in lowered for k in ("proses berat", "pemakan ram", "aplikasi berat")):
            return await self._handle_slash_command("/top")
        if any(k in lowered for k in ("status pc", "cpu", "ram", "baterai", "laptop")):
            return await self._handle_slash_command("/pc")
        if "buka antigravity" in lowered:
            return await self._handle_slash_command("/buka antigravity")
        if "buka vscode" in lowered or "buka code" in lowered:
            return await self._handle_slash_command("/buka vscode")
        if "gmail" in lowered or "email" in lowered:
            return await self._handle_slash_command("/gmail")
        if "whatsapp" in lowered or "wa " in lowered or lowered == "wa":
            return await self._handle_slash_command("/wa")
        if "lms" in lowered or "tugas" in lowered:
            return await self._handle_slash_command("/lms")

        if api_error:
            return (
                "Maaf, Boss. Seluruh provider AI yang dikonfigurasi sedang padat atau batas kuota tercapai.\n"
                f"Detail terakhir: {api_error[:240]}\n"
                "Boss tetap bisa memakai perintah cepat (`/jadwal`, `/pc`, `/top`, `/screen`, `/doc`, `/models`, `/lms`) "
                "atau tambahkan API key gratis cadangan (Groq/Cerebras/OpenRouter) di `.env`."
            )

        return (
            "Siap, Boss. Belum ada API key AI yang diisi di file `.env`, sehingga mode chat bebas belum aktif.\n"
            "Boss tetap bisa langsung memakai perintah cepat seperti `/jadwal`, `/alarm 5 Cek Tugas`, `/doc`, `/pc`, `/buka antigravity`, `/gmail`, `/wa`, `/lms`, atau ketik `/help`."
        )

    # ------------------------------------------------------------------
    # Shared Context, Memory & Tool Dispatcher
    # ------------------------------------------------------------------
    async def _build_live_context(self, user_prompt: str) -> str:
        today_briefing = await self.scheduler.format_today_briefing()
        active_alarms = await self.db.list_active_alarms()
        telemetry = self.pc_control.get_telemetry()
        presence = await self.scheduler.get_phone_presence_status()
        return (
            f"[LIVE SYSTEM CONTEXT]\n"
            f"Waktu Lokal: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"PC Telemetry: CPU {telemetry['cpu_percent']}%, RAM {telemetry['ram_percent']}%, "
            f"Baterai {telemetry['battery_percent']}%, Tailscale {telemetry['tailscale_ip']}\n"
            f"Phone Last Seen: {presence['inactive_minutes']} menit lalu\n"
            f"Alarm Aktif: {len(active_alarms)}\n"
            f"{today_briefing}\n"
            f"[/LIVE SYSTEM CONTEXT]\n\n"
            f"Permintaan Boss: {user_prompt}"
        )

    async def _build_system_prompt(self) -> str:
        facts = await self.db.list_memory_facts(limit=30)
        if not facts:
            return SYSTEM_INSTRUCTION
        block = "\n".join(f"- {f['fact']}" for f in facts)
        return f"{SYSTEM_INSTRUCTION}\n[PROFIL & MEMORI BOSS]\n{block}\n[/PROFIL & MEMORI BOSS]"

    async def _execute_tool_async(self, name: str, args: dict[str, Any]) -> str:
        """Single async tool executor shared by every provider (Gemini & OpenAI-compatible)."""
        try:
            if name == "launch_pc_application":
                return str(self.pc_control.launch_app(str(args.get("app_name", ""))))
            if name == "generate_document":
                doc = self.documents.create_document(
                    title=str(args.get("title", "Dokumen")),
                    sections=[{"heading": "Pembahasan", "content": str(args.get("content", ""))}],
                    fmt=str(args.get("fmt", "docx")),
                )
                return str(doc)
            if name == "get_pc_status":
                return str(self.pc_control.get_telemetry())
            if name == "add_schedule_item":
                target_date = str(args.get("event_date", "")).strip() or datetime.now().strftime("%Y-%m-%d")
                item = await self.db.add_schedule(
                    title=str(args.get("title", "Agenda")),
                    event_date=target_date,
                    start_time=str(args.get("start_time", "09:00")).strip()[:5],
                    description=str(args.get("description", "")),
                    alarm_enabled=True,
                    alarm_timeout_minutes=self.settings.alarm_default_timeout_minutes,
                )
                return str(item)
            if name == "arm_timer_reminder":
                minutes = max(1, min(120, int(args.get("timeout_minutes", self.settings.alarm_default_timeout_minutes))))
                alarm = await self.scheduler.arm_escalation_alarm(
                    title=str(args.get("title", "Pengingat")),
                    message=str(args.get("message", "Pengingat dari AI")),
                    timeout_minutes=minutes,
                )
                return str(alarm)
            if name == "run_pc_shell":
                return str(await self.pc_control.run_shell_command(str(args.get("command", "")), self.approval_gate))
            if name == "check_lms_dashboard":
                return str(await self.lms.inspect_dashboard())
            if name == "queue_gmail_send":
                res = await self.gmail.queue_send_email(
                    to=str(args.get("to", "")),
                    subject=str(args.get("subject", "")),
                    body=str(args.get("body", "")),
                    approval_gate=self.approval_gate,
                )
                return str(res)
            if name == "check_unread_whatsapp":
                return str(await self.whatsapp.get_unread_messages())
            if name == "queue_whatsapp_reply":
                res = await self.whatsapp.queue_reply(
                    chat_id=str(args.get("chat_id", "")),
                    contact_name=str(args.get("contact_name", "Kontak")),
                    reply_text=str(args.get("reply_text", "")),
                    approval_gate=self.approval_gate,
                )
                return str(res)
            if name == "lock_laptop_screen":
                return str(self.pc_control.lock_workstation())
            if name == "list_heavy_processes":
                limit = max(1, min(15, int(args.get("limit", 8) or 8)))
                return str(await asyncio.to_thread(self.pc_control.list_top_processes, limit))
            if name == "request_close_process":
                return str(await self.pc_control.request_close_process(str(args.get("target", "")), self.approval_gate))
            if name == "remember_fact":
                fact = await self.db.add_memory_fact(str(args.get("fact", "")))
                return f"Memori tersimpan [{fact['id']}]: {fact['fact']}"
            return f"Tool tidak dikenal: {name}"
        except Exception as exc:
            return f"Error eksekusi tool {name}: {exc}"

    # ------------------------------------------------------------------
    # Multi-Provider Cascading Waterfall
    # ------------------------------------------------------------------
    async def _run_ai_waterfall(self, user_prompt: str, history: Optional[list[dict[str, Any]]] = None) -> str:
        context_block = await self._build_live_context(user_prompt)
        system_prompt = await self._build_system_prompt()
        turns = _normalize_history(history or [])
        errors: list[str] = []

        if self.settings.gemini_api_key.strip():
            try:
                return await self._run_gemini_provider(system_prompt, turns, context_block)
            except Exception as exc:
                errors.append(f"Gemini: {str(exc)[:100]}")
                logger.warning("Provider Gemini gagal, lanjut ke provider cadangan: %s", exc)

        openai_providers: list[tuple[str, str, str, list[str], dict[str, str]]] = [
            ("groq", "https://api.groq.com/openai/v1", self.settings.groq_api_key.strip(), parse_csv(self.settings.groq_models), {}),
            ("cerebras", "https://api.cerebras.ai/v1", self.settings.cerebras_api_key.strip(), parse_csv(self.settings.cerebras_models), {}),
            (
                "openrouter",
                "https://openrouter.ai/api/v1",
                self.settings.openrouter_api_key.strip(),
                parse_csv(self.settings.openrouter_models),
                {"HTTP-Referer": "https://omnipilot.local", "X-Title": "OmniPilot Hub"},
            ),
            ("mistral", "https://api.mistral.ai/v1", self.settings.mistral_api_key.strip(), parse_csv(self.settings.mistral_models), {}),
        ]
        if self.settings.ollama_model.strip():
            ollama_key = self.settings.ollama_api_key.strip() or "ollama"
            ollama_url = (
                "https://ollama.com/v1"
                if self.settings.ollama_api_key.strip() and "127.0.0.1" in self.settings.ollama_base_url
                else self.settings.ollama_base_url.rstrip("/")
            )
            openai_providers.append(("ollama", ollama_url, ollama_key, parse_csv(self.settings.ollama_model), {}))

        for provider_name, base_url, api_key, models, extra_headers in openai_providers:
            if not api_key or not models:
                continue
            try:
                return await self._run_openai_compatible_provider(
                    provider_name=provider_name,
                    base_url=base_url,
                    api_key=api_key,
                    models=models,
                    system_prompt=system_prompt,
                    turns=turns,
                    context_block=context_block,
                    extra_headers=extra_headers,
                )
            except Exception as exc:
                errors.append(f"{provider_name}: {str(exc)[:100]}")
                logger.warning("Provider %s gagal, lanjut ke cadangan berikutnya: %s", provider_name, exc)

        raise RuntimeError(" | ".join(errors) or "Tidak ada provider AI yang berhasil merespons.")

    async def _run_gemini_provider(self, system_prompt: str, turns: list[dict[str, str]], context_block: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self.settings.gemini_api_key.strip(),
            http_options=types.HttpOptions(timeout=20_000, retry_options=types.HttpRetryOptions(attempts=1)),
        )
        declarations = [
            types.FunctionDeclaration(
                name=spec["name"],
                description=spec["description"],
                parameters_json_schema=spec["parameters"],
            )
            for spec in TOOL_SPECS
        ]
        history_contents = [
            types.Content(
                role="model" if turn["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=turn["content"])],
            )
            for turn in turns
        ]

        last_error: Optional[Exception] = None
        for model_name in parse_csv(f"{self.settings.gemini_model},{self.settings.gemini_fallback_models}"):
            use_tools = not model_name.lower().startswith("gemma-")
            contents = list(history_contents)
            if use_tools:
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=context_block)]))
                cfg = types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=[types.Tool(function_declarations=declarations)],
                    temperature=0.3,
                )
            else:
                contents.append(
                    types.Content(role="user", parts=[types.Part.from_text(text=f"{system_prompt}\n\n{context_block}")])
                )
                cfg = types.GenerateContentConfig(temperature=0.3)

            tool_log: list[str] = []
            try:
                reply = await self._gemini_tool_loop(client, types, model_name, contents, cfg, tool_log)
                self.last_used_model = f"gemini/{model_name}"
                return reply
            except Exception as exc:
                if tool_log:
                    self.last_used_model = f"gemini/{model_name}"
                    return _summarize_tool_log(tool_log)
                last_error = exc
                logger.warning("Gemini model %s gagal (%s), coba cadangan...", model_name, str(exc)[:100])
                if _is_retryable(str(exc)):
                    continue
                raise
        raise last_error or RuntimeError("Semua model Gemini gagal.")

    async def _gemini_tool_loop(
        self,
        client: Any,
        types: Any,
        model_name: str,
        contents: list[Any],
        cfg: Any,
        tool_log: list[str],
    ) -> str:
        """Manual function-calling loop so tools run on the async event loop with shared executors."""
        for _ in range(MAX_TOOL_ROUNDS):
            resp = await asyncio.to_thread(client.models.generate_content, model=model_name, contents=contents, config=cfg)
            calls = resp.function_calls or []
            if not calls:
                return (resp.text or "Perintah telah diproses, Boss.").strip()
            contents.append(resp.candidates[0].content)
            response_parts = []
            for call in calls[:4]:
                result = await self._execute_tool_async(call.name, dict(call.args or {}))
                tool_log.append(f"{call.name}: {result[:160]}")
                response_parts.append(types.Part.from_function_response(name=call.name, response={"result": result[:3000]}))
            contents.append(types.Content(role="user", parts=response_parts))
        return _summarize_tool_log(tool_log)

    async def _run_openai_compatible_provider(
        self,
        provider_name: str,
        base_url: str,
        api_key: str,
        models: list[str],
        system_prompt: str,
        turns: list[dict[str, str]],
        context_block: str,
        extra_headers: dict[str, str],
    ) -> str:
        """Call any OpenAI-compatible free provider (Groq, Cerebras, OpenRouter, Mistral, Ollama) with multi-round tools."""
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", **extra_headers}
        url = f"{base_url.rstrip('/')}/chat/completions"
        last_error: Optional[Exception] = None

        async with httpx.AsyncClient(timeout=25.0) as client:
            for model_name in models:
                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": system_prompt},
                    *[{"role": t["role"], "content": t["content"]} for t in turns],
                    {"role": "user", "content": context_block},
                ]
                use_tools = True
                tool_log: list[str] = []
                try:
                    for _ in range(MAX_TOOL_ROUNDS + 1):
                        payload: dict[str, Any] = {"model": model_name, "messages": messages, "temperature": 0.3}
                        if use_tools:
                            payload["tools"] = OPENAI_TOOL_SCHEMAS
                            # Per Ollama OpenAI-compatibility docs, tool_choice is unsupported there
                            if provider_name != "ollama":
                                payload["tool_choice"] = "auto"
                        resp = await client.post(url, headers=headers, json=payload)

                        if resp.status_code == 400 and use_tools and "tool" in resp.text.lower():
                            use_tools = False
                            continue
                        if resp.status_code in (404, 429, 500, 502, 503, 504):
                            raise RuntimeError(f"{provider_name}/{model_name} HTTP {resp.status_code}: {resp.text[:120]}")
                        resp.raise_for_status()

                        msg = resp.json()["choices"][0]["message"]
                        tool_calls = msg.get("tool_calls") or []
                        if not tool_calls:
                            self.last_used_model = f"{provider_name}/{model_name}"
                            return (msg.get("content") or "Perintah telah diproses, Boss.").strip()

                        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
                        for tc in tool_calls[:4]:
                            fn_name = tc["function"]["name"]
                            raw_args = tc["function"].get("arguments") or "{}"
                            try:
                                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                            except (json.JSONDecodeError, TypeError, ValueError):
                                parsed_args = {}
                            tool_out = await self._execute_tool_async(fn_name, parsed_args)
                            tool_log.append(f"{fn_name}: {tool_out[:160]}")
                            messages.append(
                                {"role": "tool", "tool_call_id": tc.get("id", ""), "name": fn_name, "content": tool_out[:3000]}
                            )
                    self.last_used_model = f"{provider_name}/{model_name}"
                    return _summarize_tool_log(tool_log)
                except Exception as exc:
                    if tool_log:
                        self.last_used_model = f"{provider_name}/{model_name}"
                        return _summarize_tool_log(tool_log)
                    last_error = exc
                    logger.warning("Model %s/%s gagal: %s", provider_name, model_name, exc)
                    continue

        raise last_error or RuntimeError(f"Semua model pada {provider_name} gagal.")
