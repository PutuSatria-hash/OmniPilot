"""Gmail Service using Official Google OAuth2 API with Approval Gate for Sending."""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from backend.core.approval_gate import ApprovalGate
from backend.core.config import BASE_DIR, Settings

logger = logging.getLogger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]


class GmailService:
    """Reads unread emails and safely sends Gmail messages after Boss approval."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def credentials_path(self) -> Path:
        return BASE_DIR / self.settings.google_credentials_file

    @property
    def token_path(self) -> Path:
        return BASE_DIR / self.settings.google_token_file

    def is_configured(self) -> bool:
        return self.token_path.exists()

    def get_status(self) -> dict[str, Any]:
        return {
            "credentials_present": self.credentials_path.exists(),
            "token_present": self.token_path.exists(),
            "ready": self.token_path.exists(),
            "hint": (
                "Gmail OAuth siap digunakan."
                if self.token_path.exists()
                else "Letakkan google_credentials.json di folder data/ lalu jalankan oauth setup, atau gunakan Plugin Gmail resmi di Antigravity."
            ),
        }

    def _build_client(self) -> Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not self.token_path.exists():
            raise RuntimeError(
                "Token OAuth Gmail belum tersedia di data/google_token.json. Lihat panduan PREPARE_LAPTOP_DAN_HP.md."
            )

        creds = Credentials.from_authorized_user_file(str(self.token_path), GMAIL_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    async def list_unread(self, max_results: int = 8) -> dict[str, Any]:
        """Fetch unread inbox messages."""
        if not self.is_configured():
            return {"ready": False, "messages": [], "note": self.get_status()["hint"]}

        service = self._build_client()
        response = (
            service.users()
            .messages()
            .list(userId="me", q="is:unread in:inbox", maxResults=max_results)
            .execute()
        )
        items = response.get("messages", [])
        summaries: list[dict[str, str]] = []

        for item in items:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=item["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            summaries.append(
                {
                    "id": item["id"],
                    "from": headers.get("From", "(Unknown)"),
                    "subject": headers.get("Subject", "(Tanpa Subjek)"),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                }
            )

        return {"ready": True, "count": len(summaries), "messages": summaries}

    async def queue_send_email(
        self,
        to: str,
        subject: str,
        body: str,
        approval_gate: ApprovalGate,
    ) -> dict[str, Any]:
        """Always pass outbound emails through the Human-in-the-Loop Approval Gate."""
        approval = await approval_gate.request_approval(
            action_type="send_gmail",
            title=f"Kirim Gmail ke {to}",
            summary=f"Subjek: {subject}\n\nIsi:\n{body[:400]}",
            payload={"to": to, "subject": subject, "body": body},
        )
        return {
            "status": "pending_approval",
            "approval_id": approval["id"],
            "message": "Draft email masuk antrean konfirmasi. Klik Approve untuk mengirim via Gmail.",
        }

    async def execute_send_email(self, payload: dict[str, Any]) -> str:
        """Actual send handler invoked ONLY by ApprovalGate after Boss approves."""
        if not self.is_configured():
            raise RuntimeError("Gmail OAuth belum dikonfigurasi di data/google_token.json.")

        service = self._build_client()
        msg = EmailMessage()
        msg["To"] = payload["to"]
        msg["Subject"] = payload["subject"]
        msg.set_content(payload["body"])

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"Email berhasil dikirim ke {payload['to']} (Message ID: {sent.get('id')})."
