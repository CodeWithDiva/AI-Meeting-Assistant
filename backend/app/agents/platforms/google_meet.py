"""Join a Google Meet call as an unauthenticated guest.

Meet's guest flow is friendlier to a bot than Zoom's: no download prompt and no
passcode. Two things still need care:

* **Camera and mic must be turned off before joining.** Meet's pre-join screen
  enables both by default; leaving the camera on makes the bot conspicuous, and
  leaving the mic hot creates a feedback loop with the virtual cable the bot
  plays Ava's replies into.
* **The host must admit the bot.** Guests land in a lobby, so
  :meth:`join` waits out the admission rather than assuming instant entry.
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

# Meet's generated class names change constantly; these lead with stable
# `data-*` and `aria-*` hooks and only then fall back to layout classes.
_ACTIVE_SPEAKER_SELECTORS = [
    "[data-participant-id][class*='speaking'] [data-self-name]",
    "div[data-is-speaking='true'] [data-self-name]",
    "div[class*='IisKdb'] [data-self-name]",
    "[data-participant-id][data-is-speaking='true']",
]
_PARTICIPANT_SELECTORS = [
    "[role='listitem'][data-participant-id] [data-self-name]",
    "div[data-participant-id] [data-self-name]",
    "[aria-label*='participant'] [role='listitem']",
]


class GoogleMeetJoinStrategy:
    """Drive the Google Meet guest join flow."""

    name = "google_meet"

    def __init__(self, join_timeout_ms: int, ui_timeout_ms: int) -> None:
        self.join_timeout_ms = join_timeout_ms
        self.ui_timeout_ms = ui_timeout_ms

    async def join(self, page: Any, join_url: str, display_name: str, password: str | None) -> None:
        await goto_spa(page, join_url, self.join_timeout_ms)

        await click_if_visible(page, r"accept all|i agree|got it|dismiss", 5_000)

        await self._disable_devices(page)

        name_field = await find_first_visible(
            page,
            [
                page.get_by_placeholder(re.compile("your name", re.I)),
                page.get_by_label(re.compile("your name", re.I)),
                page.locator("input[aria-label*='name' i]"),
                page.locator("input[type='text']"),
            ],
            timeout_ms=self.ui_timeout_ms,
        )
        if name_field:
            await name_field.fill(display_name)
        else:
            # A signed-in Chromium profile skips the name prompt entirely.
            logger.info("No guest name field on Meet — continuing with the profile's name.")

        join_btn = await find_first_visible(
            page,
            [
                page.get_by_role("button", name=re.compile("ask to join|join now", re.I)),
                page.get_by_text(re.compile("^(ask to join|join now)$", re.I)),
            ],
            timeout_ms=self.ui_timeout_ms,
        )
        if not join_btn:
            raise JoinFailedError(
                "Google Meet did not offer a join button — the meeting may have "
                "ended, or the link may be restricted to signed-in accounts."
            )
        await join_btn.click()

        await self._wait_for_admission(page)

    async def _disable_devices(self, page: Any) -> None:
        """Turn the camera and microphone off on the pre-join screen."""
        for pattern in (r"turn off camera", r"turn off microphone"):
            button = await find_first_visible(
                page,
                [page.get_by_role("button", name=re.compile(pattern, re.I))],
                timeout_ms=4_000,
                poll_ms=250,
            )
            if button:
                await button.click()
                logger.debug("Meet: clicked %r", pattern)

    async def _wait_for_admission(self, page: Any) -> None:
        """Block until the host admits the bot, or the wait times out."""
        inside = await find_first_visible(
            page,
            [
                page.get_by_role("button", name=re.compile("leave call", re.I)),
                page.locator("[aria-label*='Leave call' i]"),
                page.get_by_role("button", name=re.compile("chat with everyone", re.I)),
            ],
            timeout_ms=self.join_timeout_ms,
            poll_ms=1_000,
        )
        if inside is None:
            raise JoinFailedError(
                "Waited for the Google Meet host to admit the assistant, but it "
                "was never let in. Ask the host to admit "
                "the assistant, or turn on 'Quick access' for the meeting."
            )
        await click_if_visible(page, r"got it|dismiss|close", 3_000)
        # Opening the People panel is what exposes participant names to the DOM.
        await click_if_visible(page, r"^people$|show everyone", 3_000)
        logger.info("Google Meet: admitted into the call.")

    async def active_speaker(self, page: Any) -> str | None:
        names = await read_texts(page, _ACTIVE_SPEAKER_SELECTORS, limit=1)
        return names[0] if names else None

    async def participants(self, page: Any) -> list[str]:
        return await read_texts(page, _PARTICIPANT_SELECTORS, limit=50)

    async def leave(self, page: Any) -> None:
        await click_if_visible(page, r"leave call", 3_000)
