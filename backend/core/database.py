"""Async SQLite persistence layer for schedules, alarms, approvals, and telemetry."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Structured async SQLite repository."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._init_schema()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database belum terkoneksi. Panggil connect() terlebih dahulu.")
        return self._conn

    async def _init_schema(self) -> None:
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                event_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT DEFAULT '',
                category TEXT DEFAULT 'general',
                source TEXT DEFAULT 'local',
                alarm_enabled INTEGER DEFAULT 1,
                alarm_timeout_minutes INTEGER DEFAULT 5,
                reminded_today INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alarm_watchdogs (
                id TEXT PRIMARY KEY,
                schedule_id TEXT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                timeout_minutes INTEGER NOT NULL,
                stage INTEGER DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'ARMED',
                created_at TEXT NOT NULL,
                deadline_at TEXT NOT NULL,
                acknowledged_at TEXT
            );

            CREATE TABLE IF NOT EXISTS phone_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                device_name TEXT DEFAULT 'phone',
                battery_pct INTEGER,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_approvals (
                id TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                result_text TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chat_channel ON chat_messages (channel, id);

            CREATE TABLE IF NOT EXISTS memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        await self.conn.commit()

    # ------------------------------------------------------------------
    # Schedules
    # ------------------------------------------------------------------
    async def add_schedule(
        self,
        title: str,
        event_date: str,
        start_time: str,
        end_time: str = "",
        description: str = "",
        category: str = "general",
        source: str = "local",
        alarm_enabled: bool = True,
        alarm_timeout_minutes: int = 5,
    ) -> dict[str, Any]:
        item_id = str(uuid.uuid4())[:8]
        created_at = utc_now_iso()
        await self.conn.execute(
            """
            INSERT INTO schedules (
                id, title, description, event_date, start_time, end_time,
                category, source, alarm_enabled, alarm_timeout_minutes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                title,
                description,
                event_date,
                start_time,
                end_time,
                category,
                source,
                1 if alarm_enabled else 0,
                alarm_timeout_minutes,
                created_at,
            ),
        )
        await self.conn.commit()
        return await self.get_schedule(item_id)  # type: ignore[return-value]

    async def get_schedule(self, item_id: str) -> Optional[dict[str, Any]]:
        cursor = await self.conn.execute("SELECT * FROM schedules WHERE id = ?", (item_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_schedules(self, event_date: Optional[str] = None) -> list[dict[str, Any]]:
        if event_date:
            cursor = await self.conn.execute(
                "SELECT * FROM schedules WHERE event_date = ? ORDER BY start_time ASC",
                (event_date,),
            )
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM schedules ORDER BY event_date ASC, start_time ASC LIMIT 50"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_schedule_reminded(self, item_id: str) -> None:
        await self.conn.execute("UPDATE schedules SET reminded_today = 1 WHERE id = ?", (item_id,))
        await self.conn.commit()

    async def delete_schedule(self, item_id: str) -> bool:
        cursor = await self.conn.execute("DELETE FROM schedules WHERE id = ?", (item_id,))
        await self.conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Alarm Watchdogs (Dead-Man's Switch Escalation)
    # ------------------------------------------------------------------
    async def create_alarm_watchdog(
        self,
        title: str,
        message: str,
        timeout_minutes: int,
        deadline_at: str,
        schedule_id: Optional[str] = None,
    ) -> dict[str, Any]:
        alarm_id = f"alm_{uuid.uuid4().hex[:8]}"
        created_at = utc_now_iso()
        await self.conn.execute(
            """
            INSERT INTO alarm_watchdogs (
                id, schedule_id, title, message, timeout_minutes, stage, status, created_at, deadline_at
            ) VALUES (?, ?, ?, ?, ?, 1, 'ARMED', ?, ?)
            """,
            (alarm_id, schedule_id, title, message, timeout_minutes, created_at, deadline_at),
        )
        await self.conn.commit()
        return await self.get_alarm_watchdog(alarm_id)  # type: ignore[return-value]

    async def get_alarm_watchdog(self, alarm_id: str) -> Optional[dict[str, Any]]:
        cursor = await self.conn.execute("SELECT * FROM alarm_watchdogs WHERE id = ?", (alarm_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_active_alarms(self) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM alarm_watchdogs
            WHERE status IN ('ARMED', 'WARNING', 'CRITICAL')
            ORDER BY created_at DESC
            """
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_recent_alarms(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM alarm_watchdogs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def update_alarm_state(
        self,
        alarm_id: str,
        status: str,
        stage: Optional[int] = None,
        acknowledged_at: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if stage is not None and acknowledged_at is not None:
            await self.conn.execute(
                "UPDATE alarm_watchdogs SET status = ?, stage = ?, acknowledged_at = ? WHERE id = ?",
                (status, stage, acknowledged_at, alarm_id),
            )
        elif stage is not None:
            await self.conn.execute(
                "UPDATE alarm_watchdogs SET status = ?, stage = ? WHERE id = ?",
                (status, stage, alarm_id),
            )
        elif acknowledged_at is not None:
            await self.conn.execute(
                "UPDATE alarm_watchdogs SET status = ?, acknowledged_at = ? WHERE id = ?",
                (status, acknowledged_at, alarm_id),
            )
        else:
            await self.conn.execute(
                "UPDATE alarm_watchdogs SET status = ? WHERE id = ?",
                (status, alarm_id),
            )
        await self.conn.commit()
        return await self.get_alarm_watchdog(alarm_id)

    # ------------------------------------------------------------------
    # Phone Activity Heartbeat
    # ------------------------------------------------------------------
    async def record_phone_activity(
        self,
        event_type: str,
        device_name: str = "phone",
        battery_pct: Optional[int] = None,
    ) -> dict[str, Any]:
        recorded_at = utc_now_iso()
        cursor = await self.conn.execute(
            """
            INSERT INTO phone_activity (event_type, device_name, battery_pct, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, device_name, battery_pct, recorded_at),
        )
        await self.conn.commit()
        return {
            "id": cursor.lastrowid,
            "event_type": event_type,
            "device_name": device_name,
            "battery_pct": battery_pct,
            "recorded_at": recorded_at,
        }

    async def get_latest_phone_activity(self) -> Optional[dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM phone_activity ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Approval Gate
    # ------------------------------------------------------------------
    async def create_approval(
        self,
        action_type: str,
        title: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        approval_id = f"apr_{uuid.uuid4().hex[:8]}"
        created_at = utc_now_iso()
        await self.conn.execute(
            """
            INSERT INTO pending_approvals (
                id, action_type, title, summary, payload_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
            """,
            (approval_id, action_type, title, summary, json.dumps(payload), created_at),
        )
        await self.conn.commit()
        return await self.get_approval(approval_id)  # type: ignore[return-value]

    async def get_approval(self, approval_id: str) -> Optional[dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM pending_approvals WHERE id = ?", (approval_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json", "{}"))
        return data

    async def list_approvals(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        if status:
            cursor = await self.conn.execute(
                "SELECT * FROM pending_approvals WHERE status = ? ORDER BY created_at DESC LIMIT 30",
                (status,),
            )
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM pending_approvals ORDER BY created_at DESC LIMIT 30"
            )
        results: list[dict[str, Any]] = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json", "{}"))
            results.append(item)
        return results

    async def update_approval(
        self,
        approval_id: str,
        status: str,
        result_text: str = "",
    ) -> Optional[dict[str, Any]]:
        resolved_at = utc_now_iso()
        await self.conn.execute(
            """
            UPDATE pending_approvals
            SET status = ?, result_text = ?, resolved_at = ?
            WHERE id = ?
            """,
            (status, result_text, resolved_at, approval_id),
        )
        await self.conn.commit()
        return await self.get_approval(approval_id)

    # ------------------------------------------------------------------
    # Chat History
    # ------------------------------------------------------------------
    async def add_chat_message(self, channel: str, role: str, content: str) -> dict[str, Any]:
        created_at = utc_now_iso()
        cursor = await self.conn.execute(
            "INSERT INTO chat_messages (channel, role, content, created_at) VALUES (?, ?, ?, ?)",
            (channel, role, content, created_at),
        )
        await self.conn.commit()
        return {
            "id": cursor.lastrowid,
            "channel": channel,
            "role": role,
            "content": content,
            "created_at": created_at,
        }

    async def list_chat_messages(self, limit: int = 40, channel: Optional[str] = None) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        if channel:
            cursor = await self.conn.execute(
                "SELECT * FROM chat_messages WHERE channel = ? ORDER BY id DESC LIMIT ?", (channel, limit)
            )
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?", (limit,)
            )
        rows = [dict(r) for r in await cursor.fetchall()]
        rows.reverse()
        return rows

    async def clear_chat_messages(self, channel: str) -> int:
        cursor = await self.conn.execute("DELETE FROM chat_messages WHERE channel = ?", (channel,))
        await self.conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Long-Term Memory Facts (Profil & Preferensi Boss)
    # ------------------------------------------------------------------
    async def add_memory_fact(self, fact: str) -> dict[str, Any]:
        cleaned = " ".join(fact.split())[:300]
        cursor = await self.conn.execute(
            "SELECT * FROM memory_facts WHERE lower(fact) = lower(?)", (cleaned,)
        )
        existing = await cursor.fetchone()
        if existing:
            return dict(existing)
        created_at = utc_now_iso()
        cursor = await self.conn.execute(
            "INSERT INTO memory_facts (fact, created_at) VALUES (?, ?)", (cleaned, created_at)
        )
        await self.conn.commit()
        return {"id": cursor.lastrowid, "fact": cleaned, "created_at": created_at}

    async def list_memory_facts(self, limit: int = 40) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM memory_facts ORDER BY id ASC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def delete_memory_fact(self, fact_id: int) -> bool:
        cursor = await self.conn.execute("DELETE FROM memory_facts WHERE id = ?", (fact_id,))
        await self.conn.commit()
        return cursor.rowcount > 0
