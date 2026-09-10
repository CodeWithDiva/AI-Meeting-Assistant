"""Shared contract and Playwright helpers for platform join strategies.

Each meeting platform has its own join flow and its own DOM, but the bot's
lifecycle is identical everywhere: land on a page, get past the pre-join
screen, sit in the meeting reading who is talking, then leave. A
:class:`JoinStrategy` supplies only the platform-specific parts.

Every selector list here is intentionally a *list*: Zoom and Meet both ship
frequent, unannounced DOM changes, so each lookup tries several plausible
locators and falls back to text/role matching rather than pinning one brittle
CSS class.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class JoinStrategy(Protocol):
    """Platform-specific meeting join/observe/leave behaviour."""

    name: str

    async def join(self, page: Any, join_url: str, display_name: str, password: str | None) -> None:
        """Navigate to the meeting and get the bot admitted, or raise."""

    async def active_speaker(self, page: Any) -> str | None:
        """Best-effort name of whoever is currently talking, or None."""

    async def participants(self, page: Any) -> list[str]:
        """Best-effort roster of participant names currently visible."""

    async def leave(self, page: Any) -> None:
        """Click the platform's leave control. Failures are non-fatal."""


class JoinFailedError(RuntimeError):
    """Raised when the bot could not get into the meeting."""


async def goto_spa(page: Any, url: str, timeout_ms: int) -> None:
    """Navigate to a single-page-app meeting client.

    Zoom and Google Meet hold network connections open indefinitely, so
    Playwright's default `wait_until="load"` never resolves and `goto` times
    out even after the page is fully interactive. This waits only for the DOM,
    and treats a navigation timeout as non-fatal as long as the browser did
    land on the right origin — the join-form pollers that run next will fail
    clearly if the page is actually unusable.
    """
    from urllib.parse import urlparse

    try:
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    except Exception as exc:
        if "Timeout" not in type(exc).__name__ and "Timeout" not in str(exc):
            raise
        landed = urlparse(page.url).netloc
        wanted = urlparse(url).netloc
        if not landed or landed not in {wanted, wanted.replace("app.", "")}:
            raise
        logger.info("goto(%s) kept loading; DOM is ready, continuing.", wanted)


async def find_first_visible(
    page: Any,
    candidates: list[Any],
    timeout_ms: int,
    poll_ms: int = 500,
) -> Any | None:
    """Poll every candidate locator until one is visible or time runs out.

    Meeting web clients render a loading spinner for many seconds before the
    real form appears, so this polls all candidates on each pass rather than
    letting a single locator burn the whole budget on its own wait.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_ms / 1000
    while loop.time() < deadline:
        for locator in candidates:
            try:
                target = locator.first
                if await target.is_visible():
                    return target
            except Exception:
                continue
        await asyncio.sleep(poll_ms / 1000)
    return None


async def click_if_visible(page: Any, pattern: str, timeout_ms: int = 3_000) -> bool:
    """Click the first button/text matching `pattern`. Returns whether it clicked.

    Used for the endless stream of optional consent, cookie and "Got it"
    dialogs that must be dismissed but whose absence is perfectly normal.
    """
    regex = re.compile(pattern, re.I)
    candidates = [
        page.get_by_role("button", name=regex),
        page.get_by_text(regex),
    ]
    target = await find_first_visible(page, candidates, timeout_ms, poll_ms=250)
    if target is None:
        return False
    try:
        await target.click()
        return True
    except Exception:
        logger.debug("Could not click %r", pattern, exc_info=True)
        return False


async def read_texts(page: Any, selectors: list[str], limit: int = 50) -> list[str]:
    """Return de-duplicated visible text for the first selector that matches.

    Runs entirely inside one `evaluate` call so a busy meeting page isn't
    walked from Python one node at a time.
    """
    try:
        return await page.evaluate(
            """
            ([selectors, limit]) => {
                const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                for (const selector of selectors) {
                    let nodes;
                    try { nodes = document.querySelectorAll(selector); }
                    catch (e) { continue; }
                    const out = [];
                    for (const node of nodes) {
                        const text = clean(node.innerText || node.textContent
                            || node.getAttribute('aria-label'));
                        if (text && text.length < 60 && !out.includes(text)) out.push(text);
                        if (out.length >= limit) break;
                    }
                    if (out.length) return out;
                }
                return [];
            }
            """,
            [selectors, limit],
        )
    except Exception:
        logger.debug("read_texts failed for %s", selectors, exc_info=True)
        return []
