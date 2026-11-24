"""Human-in-the-loop Approval Gate protecting sensitive external actions."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.database import Database
from backend.core.event_bus import EventBus

logger = logging.getLogger(__name__)

ActionExecutor = Callable[[dict[str, Any]], Awaitable[str]]


class ApprovalGate:
    """Queues sensitive actions and executes them only after explicit approval."""

    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus
        self._executors: dict[str, ActionExecutor] = {}

    def register_executor(self, action_type: str, executor: ActionExecutor) -> None:
        self._executors[action_type] = executor

    async def request_approval(
        self,
        action_type: str,
        title: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Store a new approval request and notify Web PWA & Telegram immediately."""
        record = await self.db.create_approval(
            action_type=action_type,
            title=title,
            summary=summary,
            payload=payload,
        )
        await self.bus.publish("approval_requested", record)
        return record

    async def approve(self, approval_id: str) -> dict[str, Any]:
        """Approve a pending request and run its registered executor."""
        record = await self.db.get_approval(approval_id)
        if not record:
            raise ValueError(f"Approval ID tidak ditemukan: {approval_id}")
        if record["status"] != "PENDING":
            return record

        executor = self._executors.get(record["action_type"])
        if not executor:
            updated = await self.db.update_approval(
                approval_id,
                "FAILED",
                f"Executor tidak terdaftar untuk tipe aksi: {record['action_type']}",
            )
            await self.bus.publish("approval_resolved", updated or record)
            return updated or record

        try:
            result_text = await executor(record["payload"])
            updated = await self.db.update_approval(approval_id, "EXECUTED", result_text)
        except Exception as exc:
            logger.exception("Approval executor error (%s): %s", approval_id, exc)
            updated = await self.db.update_approval(approval_id, "FAILED", f"Error: {exc}")

        final_record = updated or record
        await self.bus.publish("approval_resolved", final_record)
        return final_record

    async def reject(self, approval_id: str, reason: str = "Dibatalkan oleh Boss") -> dict[str, Any]:
        """Reject a pending approval request."""
        record = await self.db.get_approval(approval_id)
        if not record:
            raise ValueError(f"Approval ID tidak ditemukan: {approval_id}")
        if record["status"] != "PENDING":
            return record

        updated = await self.db.update_approval(approval_id, "REJECTED", reason)
        final_record = updated or record
        await self.bus.publish("approval_resolved", final_record)
        return final_record
