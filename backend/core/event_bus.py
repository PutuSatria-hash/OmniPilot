"""Lightweight async pub/sub event bus for real-time WebSocket and Telegram fan-out."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """In-memory async event dispatcher decoupling backend modules from UIs."""

    def __init__(self) -> None:
        self._subscribers: list[EventHandler] = []
        self._ws_queues: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self, handler: EventHandler) -> None:
        if handler not in self._subscribers:
            self._subscribers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        if handler in self._subscribers:
            self._subscribers.remove(handler)

    def register_ws_queue(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._ws_queues.add(queue)
        return queue

    def unregister_ws_queue(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._ws_queues.discard(queue)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Broadcast an event to all subscribers and WebSocket clients."""
        event = {
            "type": event_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        for queue in list(self._ws_queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except asyncio.QueueEmpty:
                    pass

        for handler in list(self._subscribers):
            try:
                await handler(event)
            except Exception as exc:  # pragma: no cover - defensive isolation
                logger.exception("Event handler failed for %s: %s", event_type, exc)
