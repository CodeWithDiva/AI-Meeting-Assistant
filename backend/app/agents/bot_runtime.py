"""A dedicated event loop for the browser meeting bot.

Playwright drives Chromium by spawning it as a subprocess. On Windows,
`asyncio.create_subprocess_exec` only works on a `ProactorEventLoop` — a
`SelectorEventLoop` raises `NotImplementedError`. And uvicorn, when run with
`--reload` or multiple workers, deliberately puts the server on a
`SelectorEventLoop` on Windows. So the bot cannot reliably share the request
loop.

This module owns one daemon thread running a Proactor loop (on Windows; the
default loop elsewhere, which also supports subprocesses). Routers submit the
bot's coroutines here with :func:`submit` and await the result from their own
loop. WebSocket broadcasts triggered from inside the bot hop back to the
server loop via `ws_manager` (see `ws_manager.bind_loop`), because the socket
objects belong to that loop.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import sys
import threading
from concurrent.futures import Future
from typing import Any, Coroutine

logger = logging.getLogger(__name__)


class _BotLoopThread:
    """Lazily-started daemon thread that runs a subprocess-capable event loop."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None:
                return self._loop

            if sys.platform == "win32":
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            self._loop = loop

            self._thread = threading.Thread(
                target=self._run, name="meeting-bot-loop", daemon=True
            )
            self._thread.start()
            logger.info("Meeting-bot event loop started (%s).", type(loop).__name__)
            return loop

    def _run(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future:
        """Schedule a coroutine on the bot loop; returns a concurrent Future."""
        loop = self._ensure_started()
        return asyncio.run_coroutine_threadsafe(coro, loop)

    def shutdown(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)


_runtime = _BotLoopThread()


def submit(coro: Coroutine[Any, Any, Any]) -> Future:
    """Run a bot coroutine on the dedicated loop and return its Future.

    Await it from an async context with ``await asyncio.wrap_future(future)``.
    """
    return _runtime.submit(coro)


async def run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Await a bot coroutine from the caller's event loop."""
    return await asyncio.wrap_future(_runtime.submit(coro))


atexit.register(_runtime.shutdown)
