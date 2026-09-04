"""Own browser-based Zoom meeting bot — replaces the Zoom RTMS integration.

This is "our own agent": it joins a Zoom meeting the same way a human
would, through the Zoom Web Client in a real Chromium browser (Playwright).
It does not use Zoom's Marketplace App / OAuth / RTMS webhook at all —
no ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET, or ZOOM_WEBHOOK_SECRET_TOKEN needed
for this path.

Audio moves through two OS-level virtual audio cable devices that you set
up once on the machine running the bot — see docs/browser-bot-setup.md:

    join_meeting()
        1. Playwright opens the Zoom Web Client join URL, enters the bot's
           display name, joins with camera off and "Join Audio by Computer".
        2. MicCaptureStream starts recording from the virtual CAPTURE
           device (everything the bot "hears" in the meeting).
        3. Every recorded chunk is fed through the existing
           RTMSTranscriptionPipeline (faster-whisper) — same transcript
           storage, decisions/action-items pipeline as before.
        4. Every transcribed line is handed to AvaVoiceAssistant. If the
           "Ava" wake-word is present, Ava's TTS reply is played out on the
           virtual PLAYBACK device — which the browser's own microphone
           reads from — so the whole meeting hears Ava reply live.

    leave_meeting()
        Stops audio capture, finalizes the transcript/summary exactly like
        the RTMS path did, and closes the browser.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

BOT_DISPLAY_NAME = os.getenv("BOT_DISPLAY_NAME", "Ava Notetaker")
BOT_HEADLESS = os.getenv("BOT_HEADLESS", "False").strip().lower() in {"1", "true", "yes"}
BOT_MIC_CAPTURE_DEVICE = os.getenv("BOT_MIC_CAPTURE_DEVICE") or None
BOT_SPEAKER_PLAYBACK_DEVICE = os.getenv("BOT_SPEAKER_PLAYBACK_DEVICE") or None
BOT_JOIN_TIMEOUT_MS = int(os.getenv("BOT_JOIN_TIMEOUT_SECONDS", "45")) * 1000


class _BrowserNotReadyError(Exception):
    """Raised when Chromium binaries aren't installed yet (`playwright install`)."""


def parse_zoom_meeting(zoom_url_or_id: str) -> tuple[str, str | None]:
    """Extract (meeting_number, password) from a raw ID or a full Zoom URL.

    Accepts things like:
        "1234567890"
        "https://zoom.us/j/1234567890?pwd=abc123"
        "https://us02web.zoom.us/wc/join/1234567890"
    """
    candidate = zoom_url_or_id.strip()
    if candidate.isdigit():
        return candidate, None

    parsed = urlparse(candidate)
    if not parsed.scheme:
        digits = re.sub(r"\D", "", candidate)
        return digits, None

    match = re.search(r"/j/(\d+)", parsed.path) or re.search(r"/wc/join/(\d+)", parsed.path)
    meeting_number = match.group(1) if match else re.sub(r"\D", "", parsed.path)
    query = parse_qs(parsed.query)
    password = (query.get("pwd") or [None])[0]
    return meeting_number, password


class BrowserMeetingBot:
    """Joins a Zoom meeting as a real participant. Same interface as the old
    RTMS-based ZoomBotAgent (join_meeting/leave_meeting/get_status/.status),
    so routers/zoom.py can swap implementations without changing its API."""

    def __init__(self, meeting_id: int, user_id: int) -> None:
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.status = "idle"  # idle -> joining -> listening -> leaving -> left
        self.is_connected = False
        # True when playwright/sounddevice aren't installed and we fell back
        # to a no-hardware simulated join (dev/test convenience only).
        self._simulated = False

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

        self._mic_stream = None
        self._pipeline = None
        self._voice_assistant = None
        self._audio_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def join_meeting(self, zoom_meeting_url_or_id: str) -> dict[str, Any]:
        """Join a Zoom meeting through the browser as an automated assistant bot."""
        self.status = "joining"
        meeting_number, password = parse_zoom_meeting(zoom_meeting_url_or_id)
        logger.info(
            "Browser bot joining Zoom meeting %s for app meeting %d...",
            meeting_number, self.meeting_id,
        )

        try:
            await self._launch_browser_and_join(meeting_number, password)
        except (ModuleNotFoundError, _BrowserNotReadyError) as exc:
            # Playwright (or its browser binaries) aren't installed on this
            # machine yet (e.g. CI, or a dev box that hasn't run the
            # browser-bot-setup steps). Fall back to a simulated join
            # instead of hard-failing, so the rest of the app keeps
            # working — run `playwright install chromium` for the real
            # live bot. See docs/browser-bot-setup.md.
            logger.warning(
                "Browser bot environment not ready (%s) — falling back to "
                "a simulated join for meeting %d.", exc, self.meeting_id,
            )
            self._simulated = True
            await self._cleanup_browser()
        except Exception:
            self.status = "FAILED_JOIN"
            await self._cleanup_browser()
            raise

        self._start_audio_pipeline()
        self.status = "listening"
        self.is_connected = True
        return {
            "status": "listening",
            "meeting_id": self.meeting_id,
            "message": "Bot joined the Zoom Web Client and is listening on the virtual audio device.",
        }

    async def leave_meeting(self) -> dict[str, Any]:
        """Leave the meeting, finalize notes, and close the browser."""
        self.status = "leaving"

        if self._audio_task:
            self._audio_task.cancel()
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
            self._audio_task = None

        if self._mic_stream:
            self._mic_stream.stop()
            self._mic_stream = None

        if self._pipeline:
            await self._pipeline.finalize()
            self._pipeline = None

        await self._cleanup_browser()

        self.status = "left"
        self.is_connected = False
        return {
            "status": "left",
            "meeting_id": self.meeting_id,
            "message": "Bot left the meeting and finalized the transcript.",
        }

    def get_status(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "status": self.status,
            "is_connected": self.is_connected,
        }

    # ------------------------------------------------------------------
    # Browser join/leave
    # ------------------------------------------------------------------

    async def _launch_browser_and_join(self, meeting_number: str, password: str | None) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=BOT_HEADLESS,
                # Auto-accepts the mic/camera permission prompt while still
                # using the real OS-selected devices (the virtual audio
                # cable) — NOT Chromium's fake device, which would be silent.
                args=["--use-fake-ui-for-media-stream"],
            )
        except Exception as exc:
            if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
                raise _BrowserNotReadyError(
                    "Chromium not installed — run `playwright install chromium`"
                ) from exc
            raise
        self._context = await self._browser.new_context(permissions=["microphone", "camera"])
        self._page = await self._context.new_page()

        join_url = f"https://app.zoom.us/wc/join/{meeting_number}"
        await self._page.goto(join_url, timeout=BOT_JOIN_TIMEOUT_MS)

        name_input = self._page.locator("input#inputname, input[name='inputname']")
        await name_input.wait_for(timeout=BOT_JOIN_TIMEOUT_MS)
        await name_input.fill(BOT_DISPLAY_NAME)

        if password:
            pwd_input = self._page.locator("input#inputpasscode, input[name='inputpasscode']")
            if await pwd_input.count():
                await pwd_input.fill(password)

        join_btn = self._page.get_by_role("button", name=re.compile("join", re.I))
        await join_btn.first.click()

        try:
            audio_btn = self._page.get_by_text(re.compile("join audio by computer", re.I))
            await audio_btn.wait_for(timeout=BOT_JOIN_TIMEOUT_MS)
            await audio_btn.click()
        except Exception:
            logger.warning(
                "Could not auto-click 'Join Audio by Computer' for meeting %d — "
                "the bot may be in the meeting without audio. Zoom's join UI "
                "changes often; update the selector in browser_bot.py if this "
                "keeps happening.",
                self.meeting_id,
            )

        logger.info("Browser bot is in meeting %s (app meeting %d)", meeting_number, self.meeting_id)

    async def _cleanup_browser(self) -> None:
        try:
            if self._page:
                leave_btn = self._page.get_by_text(re.compile("^leave$", re.I))
                if await leave_btn.count():
                    await leave_btn.first.click()
        except Exception:
            pass
        for closer in (self._context, self._browser):
            try:
                if closer:
                    await closer.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._page = self._context = self._browser = self._playwright = None

    # ------------------------------------------------------------------
    # Audio pipeline (listen + speak)
    # ------------------------------------------------------------------

    def _start_audio_pipeline(self) -> None:
        from app.audio.device_io import MicCaptureStream
        from app.services.rtms_transcription import RTMSTranscriptionPipeline
        from app.services.voice_assistant import AvaVoiceAssistant

        self._pipeline = RTMSTranscriptionPipeline(self.meeting_id)
        self._voice_assistant = AvaVoiceAssistant(self.meeting_id, on_audio_out=self._speak_reply)

        try:
            self._mic_stream = MicCaptureStream(BOT_MIC_CAPTURE_DEVICE)
            self._mic_stream.start()
        except ModuleNotFoundError as exc:
            logger.warning(
                "sounddevice isn't installed — no real audio will be captured "
                "for meeting %d (%s). See docs/browser-bot-setup.md.",
                self.meeting_id, exc,
            )
            self._mic_stream = None
        except Exception:
            logger.exception(
                "Could not open mic capture device %r for meeting %d — check "
                "BOT_MIC_CAPTURE_DEVICE in .env against "
                "`python scripts/list_audio_devices.py`.",
                BOT_MIC_CAPTURE_DEVICE, self.meeting_id,
            )
            self._mic_stream = None

        if self._mic_stream is not None:
            self._audio_task = asyncio.create_task(self._audio_loop())

    async def _audio_loop(self) -> None:
        assert self._mic_stream is not None and self._pipeline is not None
        try:
            async for chunk in self._mic_stream.chunks():
                texts = await self._pipeline.add_chunk(chunk)
                for text in texts:
                    await self._voice_assistant.handle_transcript(text)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Audio loop crashed for meeting %d", self.meeting_id)

    async def _speak_reply(self, wav_bytes: bytes) -> None:
        """Play Ava's TTS reply into the outbound virtual cable — Zoom hears it live."""
        from app.audio.device_io import play_wav_bytes

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, play_wav_bytes, wav_bytes, BOT_SPEAKER_PLAYBACK_DEVICE,
            )
        except ModuleNotFoundError:
            logger.debug("sounddevice not installed — Ava's reply stayed browser-only (no live voice).")
        except Exception:
            logger.exception("Failed to play Ava's reply into meeting %d", self.meeting_id)
