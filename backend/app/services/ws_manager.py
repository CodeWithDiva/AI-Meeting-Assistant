"""
Global WebSocket Connection Manager
=====================================
Har meeting ka ek channel hota hai. Jab bhi Ava reply kare, agent
state change ho, ya transcript segment aaye — sab clients ko instantly
broadcast karo bina HTTP polling ke.

Usage:
    from app.services.ws_manager import ws_manager

    # Connect karo (in WebSocket endpoint)
    await ws_manager.connect(meeting_id, websocket)

    # Broadcast karo (anywhere in backend)
    await ws_manager.broadcast(meeting_id, "agent_state_changed", {"state": "IN_MEETING"})

Cross-loop safety
-----------------
The meeting bot runs on its own event loop thread (see
`app.agents.bot_runtime`), but WebSocket objects belong to the server's loop.
`bind_loop()` is called once at startup to record the server loop; any
`broadcast()` invoked from another loop is marshalled back onto it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages per-meeting WebSocket connections and broadcast."""

    def __init__(self) -> None:
        # meeting_id → set of active WebSocket connections
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        # The server's event loop, recorded by bind_loop() at startup.
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the loop that owns the WebSocket connections (server startup)."""
        self._loop = loop

    async def connect(self, meeting_id: int, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection for a meeting."""
        await websocket.accept()
        async with self._lock:
            self._connections[meeting_id].add(websocket)
        logger.info("WS connected for meeting %d (total: %d)", meeting_id, len(self._connections[meeting_id]))

    async def disconnect(self, meeting_id: int, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket from the registry."""
        async with self._lock:
            self._connections[meeting_id].discard(websocket)
            if not self._connections[meeting_id]:
                del self._connections[meeting_id]
        logger.info("WS disconnected for meeting %d", meeting_id)

    async def broadcast(self, meeting_id: int, event_type: str, data: dict) -> None:
        """Send a JSON event to ALL connected clients for a given meeting.

        Payload shape: ``{ "event": "<event_type>", "data": { ... } }``

        Safe to call from any event loop: if this is running on a loop other
        than the one that owns the sockets, the work is handed to the owning
        loop.
        """
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None

        if self._loop is not None and current is not self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._broadcast(meeting_id, event_type, data), self._loop
            )
            await asyncio.wrap_future(future)
            return

        await self._broadcast(meeting_id, event_type, data)

    async def _broadcast(self, meeting_id: int, event_type: str, data: dict) -> None:
        payload = json.dumps({"event": event_type, "data": data})
        dead_sockets: list[WebSocket] = []

        async with self._lock:
            sockets = set(self._connections.get(meeting_id, set()))

        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead_sockets.append(ws)

        if dead_sockets:
            async with self._lock:
                for ws in dead_sockets:
                    self._connections[meeting_id].discard(ws)

    def connection_count(self, meeting_id: int) -> int:
        return len(self._connections.get(meeting_id, set()))


# Singleton — import this everywhere
ws_manager = ConnectionManager()
