"""Join a Google Meet call as an unauthenticated guest.

Meet's guest flow is friendlier to a bot than Zoom's: no download prompt and no
passcode. Things that still need care:

* **The camera goes off before joining.** The microphone stays ON when the bot
  has a virtual microphone (BOT_VIRTUAL_MIC_LABEL) — that cable carries only
  the assistant's spoken replies — and goes off otherwise, so the machine's
  real microphone is never re-broadcast under the bot's name.
* **The host must admit the bot.** Guests land in a lobby, so :meth:`join`
  waits out the admission, and fails fast when Meet says the request was
  denied instead of sitting out the whole timeout.
* **Speaker names come from Meet's own captions.** Once inside, the bot turns
  captions on. Meet labels every caption with the name of whoever is talking,
  which is far more reliable than guessing from video-tile CSS. The caption
  *text* is ignored — transcription is still our own Whisper (Urdu + English).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
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

# Fallbacks when captions are unavailable. Meet's generated class names change
# constantly; these lead with stable `data-*` hooks.
_ACTIVE_SPEAKER_SELECTORS = [
    "[data-participant-id][class*='speaking'] [data-self-name]",
    "div[data-is-speaking='true'] [data-self-name]",
    "[data-participant-id][data-is-speaking='true']",
]
_PARTICIPANT_SELECTORS = [
    "[role='listitem'][data-participant-id] [data-self-name]",
    "div[data-participant-id] [data-self-name]",
]

# The newest caption block's speaker badge. `.NWpY1d` / `.xoMHSc` are the
# badge classes Meet has used for caption speaker names; the region lookup
# keeps the search inside the captions area when Meet labels it.
_CAPTION_SPEAKER_JS = """
() => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const region = document.querySelector('[role="region"][aria-label*="aption" i]')
    || document.querySelector('[jsname="dsyhDe"]');
  const badges = (region || document).querySelectorAll('.NWpY1d, .xoMHSc');
  for (let i = badges.length - 1; i >= 0; i--) {
    const name = clean(badges[i].innerText || badges[i].textContent);
    if (name && name.length < 60) return name;
  }
  return null;
}
"""

# The People panel lists everyone in the call; each row's aria-label is the
# participant's name. Falls back to names printed on the video tiles.
_ROSTER_JS = """
() => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim()
    .replace(/\\s*\\((you|meeting host|host|presentation)\\)\\s*$/i, '');
  const out = [];
  const push = (raw) => {
    const name = clean(raw);
    if (name && name.length < 60 && name.toLowerCase() !== 'you' && !out.includes(name)) out.push(name);
  };
  document.querySelectorAll('[role="list"][aria-label*="articipant" i] [role="listitem"]')
    .forEach((el) => push(el.getAttribute('aria-label') || el.innerText.split('\\n')[0]));
  if (!out.length) {
    document.querySelectorAll('[data-participant-id] [data-self-name], [data-participant-id] .notranslate')
      .forEach((el) => push(el.innerText || el.textContent));
  }
  return out.slice(0, 50);
}
"""

# What Meet shows when the bot will not be let in. Checked while waiting in
# the lobby so a denial surfaces in seconds rather than after the timeout.
_DENIALS = (
    (
        ("denied your request", "request to join was denied", "you can't join this call"),
        "The Google Meet host denied the assistant's request to join.",
    ),
    (
        ("no one responded to your request",),
        "Nobody admitted the assistant into the Google Meet call. Ask the host "
        "to watch for the join request, or turn on 'Quick access' for guests.",
    ),
    (
        ("you've been removed", "you were removed", "removed you from the meeting"),
        "The assistant was removed from the Google Meet call by the host.",
    ),
    (
        ("you can't join this video call",),
        "Google Meet refused the guest join (\"You can't join this video call\"). "
        "The meeting only allows its organisation's accounts, or Google flagged the "
        "browser. Sign the bot's Chrome profile into a Google account once "
        "(BOT_HEADLESS=False, open meet.google.com in the bot window), or ask the "
        "host to allow guests.",
    ),
)


def _page_text(raw: str | None) -> str:
    # Meet uses typographic apostrophes ("can’t"); normalise before matching.
    return (raw or "").replace("’", "'").lower()


async def _type_name(field: Any, name: str) -> None:
    """Type the guest name key by key, so Meet's own input handlers see it."""
    try:
        await field.click()
        await field.fill("")
        await field.press_sequentially(name, delay=random.uniform(40, 90))
    except Exception:
        await field.fill(name)


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
            await _type_name(name_field, display_name)
            await asyncio.sleep(random.uniform(0.4, 0.9))
        else:
            # A signed-in Chromium profile skips the name prompt entirely.
            logger.info("No guest name field on Meet — continuing with the profile's name.")

        join_btn = await find_first_visible(
            page,
            [
                page.get_by_role(
                    "button", name=re.compile(r"ask to join|join now|join anyway|join here too", re.I)
                ),
                page.get_by_text(re.compile(r"^(ask to join|join now|join anyway)$", re.I)),
            ],
            timeout_ms=self.ui_timeout_ms,
        )
        if not join_btn:
            raise JoinFailedError(await self._diagnose(page))
        await join_btn.click()
        logger.info("Google Meet: asked to join as %r.", display_name)

        await self._wait_for_admission(page)

    async def _disable_devices(self, page: Any) -> None:
        """Turn the camera (and, without a virtual mic, the microphone) off.

        Best-effort by design: joining matters, muting is a courtesy. Meet's
        pre-join overlay makes the toolbar buttons findable but not clickable,
        so its keyboard shortcuts lead and a forced click is the fallback.
        """
        mute_mic = not os.getenv("BOT_VIRTUAL_MIC_LABEL")
        shortcuts = [("Control+e", "camera")]
        if mute_mic:
            shortcuts.append(("Control+d", "microphone"))
        for keys, what in shortcuts:
            try:
                await page.keyboard.press(keys)
                logger.debug("Meet: pressed %s to turn off the %s.", keys, what)
            except Exception:
                logger.debug("Meet: %s shortcut failed for the %s.", keys, what, exc_info=True)

        # Verify, and fall back to a forced click if the shortcut didn't take.
        toggles = [(r"turn off camera", "camera")]
        if mute_mic:
            toggles.append((r"turn off microphone", "microphone"))
        for pattern, what in toggles:
            try:
                button = await find_first_visible(
                    page,
                    [page.get_by_role("button", name=re.compile(pattern, re.I))],
                    timeout_ms=2_000,
                    poll_ms=250,
                )
                if button:
                    await button.click(force=True, timeout=3_000)
                    logger.debug("Meet: force-clicked the %s toggle.", what)
            except Exception:
                logger.info("Meet: could not turn the %s off — joining anyway.", what)

    async def _denial(self, page: Any) -> str | None:
        """Return why Meet is refusing the bot, if the page says so."""
        try:
            body = _page_text(await page.evaluate("document.body.innerText"))
        except Exception:
            return None
        for phrases, message in _DENIALS:
            if any(phrase in body for phrase in phrases):
                return message
        return None

    async def _diagnose(self, page: Any) -> str:
        """Turn Meet's on-page state into a message that names the real cause."""
        try:
            body = _page_text(await page.evaluate("document.body.innerText"))
        except Exception:
            body = ""

        if "check your meeting code" in body or "invalid video call name" in body:
            return (
                "Google Meet rejected that meeting code. Check the link, or "
                "paste a fresh one from a meeting that is currently running."
            )
        if "return to home screen" in body or "the call has ended" in body:
            return (
                "This Google Meet call has ended (Meet is showing its "
                "'return to home screen' page). Start the meeting first, then "
                "send the assistant in."
            )
        denial = await self._denial(page)
        if denial:
            return denial
        if "sign in" in body and "join" not in body:
            return (
                "This Google Meet requires a signed-in Google account. Sign the "
                "bot's Chrome profile into Google once, or ask the host to allow guests."
            )
        return (
            "Google Meet did not show a join button. The meeting may not have "
            "started yet, or the link may be restricted to signed-in accounts. "
            "(A screenshot of what the assistant saw is in backend/debug/.)"
        )

    async def _wait_for_admission(self, page: Any) -> None:
        """Block until the host admits the bot; fail fast if it is refused."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.join_timeout_ms / 1000
        inside_markers = [
            page.get_by_role("button", name=re.compile("leave call", re.I)),
            page.locator("button[aria-label*='Leave call' i]"),
            page.get_by_role("button", name=re.compile("chat with everyone", re.I)),
        ]
        while loop.time() < deadline:
            if await find_first_visible(page, inside_markers, timeout_ms=1_000, poll_ms=250):
                break
            denial = await self._denial(page)
            if denial:
                raise JoinFailedError(denial)
        else:
            raise JoinFailedError(
                "Waited for the Google Meet host to admit the assistant, but it "
                "was never let in. Ask the host to admit the assistant, or turn "
                "on 'Quick access' for the meeting."
            )

        logger.info("Google Meet: admitted into the call.")
        await click_if_visible(page, r"^(got it|dismiss|close)$", 3_000)
        await self._unmute_for_replies(page)
        await self._enable_captions(page)
        # Opening the People panel is what exposes the full roster to the DOM.
        await click_if_visible(page, r"^people$|show everyone", 3_000)

    async def _unmute_for_replies(self, page: Any) -> None:
        """Turn the bot's microphone back on when it is the reply cable.

        Meet mutes people who join a large call, and the host can mute anyone.
        Only a control that says "turn on microphone" is clicked, so a live
        mic is never toggled off.
        """
        if not os.getenv("BOT_VIRTUAL_MIC_LABEL"):
            return
        button = await find_first_visible(
            page,
            [
                page.get_by_role("button", name=re.compile(r"^\s*turn on microphone", re.I)),
                page.locator("button[aria-label^='turn on microphone' i]"),
            ],
            timeout_ms=3_000,
            poll_ms=250,
        )
        if button is None:
            return
        try:
            await button.click(force=True, timeout=3_000)
            logger.info("Google Meet: turned the bot's microphone on for spoken replies.")
        except Exception:
            logger.info("Google Meet: could not turn the microphone on — replies may not be heard.")

    async def _enable_captions(self, page: Any) -> None:
        """Turn Meet captions on so every line carries the speaker's name."""
        try:
            turn_on = await find_first_visible(
                page,
                [
                    page.get_by_role("button", name=re.compile(r"turn on captions", re.I)),
                    page.locator("button[aria-label*='turn on captions' i]"),
                ],
                timeout_ms=4_000,
                poll_ms=250,
            )
            if turn_on:
                await turn_on.click(force=True, timeout=3_000)
                logger.info("Google Meet: captions on (used for speaker names).")
                return
            already_on = await find_first_visible(
                page,
                [page.get_by_role("button", name=re.compile(r"turn off captions", re.I))],
                timeout_ms=1_000,
                poll_ms=250,
            )
            if already_on is None:
                # "c" is Meet's own captions shortcut; the button was not found.
                await page.keyboard.press("c")
                logger.info("Google Meet: pressed 'c' to turn captions on.")
        except Exception:
            logger.info("Google Meet: could not turn captions on — speaker names may be missing.")

    async def active_speaker(self, page: Any) -> str | None:
        try:
            name = await page.evaluate(_CAPTION_SPEAKER_JS)
        except Exception:
            name = None
        if not name:
            names = await read_texts(page, _ACTIVE_SPEAKER_SELECTORS, limit=1)
            name = names[0] if names else None
        # "You" is the bot itself — its own replies are handled by the echo guard.
        if name and name.strip().lower() in {"you", "unknown"}:
            return None
        return name

    async def participants(self, page: Any) -> list[str]:
        try:
            names = await page.evaluate(_ROSTER_JS)
        except Exception:
            names = []
        return names or await read_texts(page, _PARTICIPANT_SELECTORS, limit=50)

    async def leave(self, page: Any) -> None:
        await click_if_visible(page, r"leave call", 3_000)
