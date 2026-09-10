"""Join a Zoom meeting through the Zoom Web Client as an ordinary participant.

Deliberately uses no Zoom Marketplace app, OAuth, or RTMS: the bot lands on
`app.zoom.us/wc/<id>/join` in a real Chromium window, types a name, and joins
the same way a person on a locked-down laptop would.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agents.platforms.base import (
    JoinFailedError,
    click_if_visible,
    find_first_visible,
    goto_spa,
    read_texts,
)

logger = logging.getLogger(__name__)

# Zoom renames these classes often, so name/role matching leads and CSS is only
# a fallback.
_ACTIVE_SPEAKER_SELECTORS = [
    ".speaker-active-container__video-frame .video-avatar__avatar-name",
    ".speaker-bar-container__video-frame--active .video-avatar__avatar-name",
    "[class*='speaker-active'] [class*='avatar-name']",
    "[class*='active-speaker'] [class*='participant-name']",
    ".gallery-video-container__main-view [class*='avatar-name']",
]
_PARTICIPANT_SELECTORS = [
    ".participants-item__display-name",
    "[class*='participants-item'] [class*='display-name']",
    "[class*='participants-li'] [class*='name']",
    ".video-avatar__avatar-name",
]


class ZoomJoinStrategy:
    """Drive the Zoom Web Client join flow."""

    name = "zoom"

    def __init__(self, join_timeout_ms: int, ui_timeout_ms: int) -> None:
        self.join_timeout_ms = join_timeout_ms
        self.ui_timeout_ms = ui_timeout_ms

    # The name field on the current Web Client pre-join screen. Older markup
    # used #inputname; both are tried.
    _NAME_SELECTOR = (
        "input#input-for-name, input#inputname, "
        "input[name='inputname'], input[aria-label*='name' i]"
    )

    async def join(self, page: Any, join_url: str, display_name: str, password: str | None) -> None:
        await goto_spa(page, join_url, self.join_timeout_ms)
        await self._dismiss_cookie_wall(page)

        await click_if_visible(page, r"join from your browser|launch meeting", 4_000)

        if await self._is_inside(page):
            await self._settle_in(page)
            return

        # The Web Client SPA can take a long time to render its pre-join form on
        # a cold browser (Zoom serves the marketing shell first). Poll every
        # frame for the name field, re-dismissing the cookie wall each pass in
        # case it reappears after a redirect.
        frame, name_field = await self._await_name_field(page)
        if name_field is None:
            if await self._is_inside(page):
                await self._settle_in(page)
                return
            raise JoinFailedError(await self._diagnose(page))

        if password:
            passcode = frame.locator(
                "input#inputpasscode, input[name='inputpasscode'], input[type='password']"
            )
            try:
                if await passcode.first.is_visible():
                    await passcode.first.fill(password)
            except Exception:
                pass

        await name_field.fill(display_name)

        # Zoom's anti-bot check flips the primary button to "Sign in to join" and
        # shows a warning banner. A guest bot cannot get past that.
        blocked = await self._detect_bot_block(frame)
        if blocked:
            raise JoinFailedError(blocked)

        join_btn = await find_first_visible(
            frame,
            [
                frame.get_by_role("button", name=re.compile(r"^\s*join(\s+meeting)?\s*$", re.I)),
                frame.locator("button.preview-join-button"),
                frame.locator("button.zm-btn--primary"),
                frame.get_by_role("button", name=re.compile("sign in to join", re.I)),
                frame.locator("button[type='submit']"),
            ],
            timeout_ms=10_000,
        )
        if join_btn:
            await join_btn.click()
        else:
            await name_field.press("Enter")

        # After clicking, the bot check can still fire on the next screen.
        blocked = await self._detect_bot_block(page)
        if blocked:
            raise JoinFailedError(blocked)

        await self._settle_in(page)

    async def _detect_bot_block(self, scope: Any) -> str | None:
        """Return an actionable message if Zoom blocked the join, else None."""
        try:
            text = (await scope.evaluate("document.body.innerText") or "").lower()
        except Exception:
            return None

        if "automated bots aren't allowed" in text or "automated bots are not allowed" in text:
            return (
                "Zoom flagged the assistant's browser as an automated bot and blocked "
                "the join. Fixes: (1) in the Zoom web portal turn OFF Settings → "
                "Security → 'Only authenticated users can join', and disable 'Waiting "
                "Room' or admit the assistant manually; (2) set BOT_BROWSER_PROFILE_DIR "
                "to a Chrome profile that is signed into a Zoom account; (3) test with "
                "Google Meet, which allows guest bots. Nothing in the code can bypass "
                "a meeting that requires sign-in."
            )
        if "this meeting is for authorized" in text or (
            "sign in to join" in text and "your name" not in text
        ):
            return (
                "This Zoom meeting requires a signed-in Zoom account. Set "
                "BOT_BROWSER_PROFILE_DIR to a Chrome profile logged into Zoom, or ask "
                "the host to allow guests."
            )
        return None

    async def _diagnose(self, page: Any) -> str:
        """Turn Zoom's on-page error text into a message the user can act on."""
        try:
            body = (await page.evaluate("document.body.innerText") or "").lower()
        except Exception:
            body = ""

        if "meeting link is invalid" in body or "3,001" in body or "3001" in body:
            return (
                "Zoom says this meeting link is invalid — the meeting has ended, "
                "or its passcode has expired. Start the meeting and paste a fresh link."
            )
        if "meeting has not started" in body or "waiting for the host" in body:
            return "The Zoom meeting has not started yet. Try again once the host opens it."
        if "this meeting has been locked" in body:
            return "The host has locked this Zoom meeting, so the assistant cannot join."
        if "sign in" in body and "join" not in body:
            return "This Zoom link requires a signed-in Zoom account, which the assistant does not have."
        return (
            "Zoom's join page never showed a name field within the timeout. The "
            "meeting may be over, or Zoom's web client failed to load. A screenshot "
            "was saved to backend/debug/."
        )

    async def _dismiss_cookie_wall(self, page: Any) -> None:
        """Accept Zoom's OneTrust cookie banner, which otherwise covers the form."""
        for selector in (
            "#onetrust-accept-btn-handler",
            "button#accept-recommended-btn-handler",
        ):
            try:
                button = page.locator(selector)
                if await button.count() and await button.first.is_visible():
                    await button.first.click()
                    logger.info("Dismissed Zoom cookie banner (%s).", selector)
                    return
            except Exception:
                continue
        await click_if_visible(page, r"^(accept all cookies|accept cookies|i agree|agree)$", 3_000)

    async def _await_name_field(self, page: Any):
        """Poll all frames for the pre-join name field until it appears."""
        import asyncio

        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.join_timeout_ms / 1000
        pass_count = 0
        while loop.time() < deadline:
            for frame in page.frames:
                try:
                    field = frame.locator(self._NAME_SELECTOR).first
                    if await field.is_visible():
                        return frame, field
                except Exception:
                    continue
            pass_count += 1
            if pass_count % 6 == 0:  # ~every 3s, cheaply re-handle a re-shown wall
                await self._dismiss_cookie_wall(page)
                await click_if_visible(page, r"join from your browser|launch meeting", 1_000)
            await asyncio.sleep(0.5)
        return page, None

    async def _settle_in(self, page: Any) -> None:
        """Connect computer audio and dismiss the post-join disclaimers."""
        audio_btn = await find_first_visible(
            page,
            [
                page.get_by_text(re.compile("join audio by computer", re.I)),
                page.get_by_role("button", name=re.compile("computer audio", re.I)),
                page.locator("button.join-audio-by-voip__join-btn"),
            ],
            timeout_ms=self.ui_timeout_ms,
        )
        if audio_btn:
            await audio_btn.click()
            logger.info("Connected Zoom computer audio.")

        await click_if_visible(page, r"got it|stay in meeting|continue", 3_000)
        # Keeping the participants panel open is what makes the roster and the
        # active-speaker name readable from the DOM at all.
        await click_if_visible(page, r"^participants$", 3_000)

    async def _is_inside(self, page: Any) -> bool:
        """True once Zoom has moved past the pre-join screen."""
        target = await find_first_visible(
            page,
            [
                page.get_by_text(re.compile("join audio by computer", re.I)),
                page.get_by_text(re.compile("the meeting host will let you in", re.I)),
                page.get_by_text(re.compile("waiting for the host to start", re.I)),
                page.locator("#foot-bar"),
                page.get_by_role("button", name=re.compile("^leave$", re.I)),
            ],
            timeout_ms=2_000,
            poll_ms=250,
        )
        return target is not None

    async def active_speaker(self, page: Any) -> str | None:
        names = await read_texts(page, _ACTIVE_SPEAKER_SELECTORS, limit=1)
        return names[0] if names else None

    async def participants(self, page: Any) -> list[str]:
        return await read_texts(page, _PARTICIPANT_SELECTORS, limit=50)

    async def leave(self, page: Any) -> None:
        if await click_if_visible(page, r"^leave$", 3_000):
            await click_if_visible(page, r"leave meeting|leave now", 3_000)
