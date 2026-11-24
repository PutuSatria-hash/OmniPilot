"""Safe WhatsApp Bridge Client: Reads & Summarizes Chats, Always Requires Approval Before Reply."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.core.approval_gate import ApprovalGate
from backend.core.config import Settings

logger = logging.getLogger(__name__)


class WhatsAppService:
    """Communicates with local isolated Node.js WhatsApp Bridge with strict anti-ban safeguards."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_status(self) -> dict[str, Any]:
        if not self.settings.whatsapp_enabled:
            return {
                "enabled": False,
                "connected": False,
                "message": "WhatsApp Bridge dalam mode nonaktif (aman). Set WHATSAPP_ENABLED=true di .env dan jalankan whatsapp-bridge untuk mengaktifkan.",
            }
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{self.settings.whatsapp_bridge_url}/status")
                resp.raise_for_status()
                return {"enabled": True, **resp.json()}
        except Exception as exc:
            return {
                "enabled": True,
                "connected": False,
                "message": f"Bridge belum aktif di {self.settings.whatsapp_bridge_url}: {exc}",
            }

    async def get_unread_messages(self, limit: int = 20) -> dict[str, Any]:
        if not self.settings.whatsapp_enabled:
            return {
                "connected": False,
                "messages": [],
                "note": "Aktifkan WHATSAPP_ENABLED=true dan jalankan service whatsapp-bridge terlebih dahulu.",
            }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    f"{self.settings.whatsapp_bridge_url}/unread",
                    params={"limit": limit},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("Gagal mengambil pesan unread WA: %s", exc)
            return {"connected": False, "messages": [], "note": f"Error bridge: {exc}"}

    async def queue_reply(
        self,
        chat_id: str,
        contact_name: str,
        reply_text: str,
        approval_gate: ApprovalGate,
    ) -> dict[str, Any]:
        """Queue a WhatsApp reply in Approval Gate (Human-in-the-Loop anti-ban protection)."""
        approval = await approval_gate.request_approval(
            action_type="reply_whatsapp",
            title=f"Balas WhatsApp: {contact_name}",
            summary=f"Tujuan: {contact_name} ({chat_id})\nPesan balasan:\n{reply_text}",
            payload={
                "chat_id": chat_id,
                "contact_name": contact_name,
                "text": reply_text,
            },
        )
        return {
            "status": "pending_approval",
            "approval_id": approval["id"],
            "message": "Draft balasan WhatsApp menunggu konfirmasi Approve dari Boss agar aman dari spam/banned.",
        }

    async def execute_reply(self, payload: dict[str, Any]) -> str:
        """Send approved WhatsApp message through local bridge with natural delay."""
        if not self.settings.whatsapp_enabled:
            raise RuntimeError("WhatsApp Bridge belum diaktifkan di .env.")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.settings.whatsapp_bridge_url}/send",
                json={"chatId": payload["chat_id"], "text": payload["text"]},
            )
            resp.raise_for_status()
        return f"Balasan WhatsApp berhasil dikirim ke {payload.get('contact_name', payload['chat_id'])}."
