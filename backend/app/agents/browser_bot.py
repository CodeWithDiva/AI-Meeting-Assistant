"""Our own browser-based meeting agent — no vendor SDK, no RTMS, no webhooks.

The bot joins a meeting exactly the way a person would: a real Chromium window
opens the meeting's web client, types a display name and joins. Zoom and Google
Meet are supported; the platform is detected from the pasted link, and the
per-platform DOM work lives in `app.agents.platforms`.

Audio moves through two OS-level virtual audio cable devices set up once on the
machine running the bot (see docs/browser-bot-setup.md):

    join_meeting()
        1. Chromium opens the meeting and the platform strategy gets the bot in.
        2. MicCaptureStream records the virtual CAPTURE device — everything the
           bot "hears".
        3. Audio flows into LiveMeetingPipeline: utterance-boundary windows,
           bilingual Whisper, speaker-attributed transcript rows, optional
           recording to disk.
        4. A background poller reads the meeting UI for the active speaker and
           the participant roster, so transcript lines carry real names and
           tasks can be assigned to the right person.
        5. Each transcribed line reaches AvaVoiceAssistant; on the wake word,
           Ava's TTS reply is played into the virtual PLAYBACK device that the
           browser uses as its microphone, so the room hears her answer live.

    leave_meeting()
        Stops capture, finalizes transcript → summary → decisions → assigned
        tasks, and closes the browser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agents.meeting_link import MeetingLink, parse_meeting_link
from app.agents.platforms import JoinFailedError, get_strategy

logger = logging.getLogger(__name__)

BOT_DISPLAY_NAME = os.getenv("BOT_DISPLAY_NAME", "Ava Notetaker")
BOT_HEADLESS = os.getenv("BOT_HEADLESS", "False").strip().lower() in {"1", "true", "yes"}
BOT_MIC_CAPTURE_DEVICE = os.getenv("BOT_MIC_CAPTURE_DEVICE") or None
BOT_SPEAKER_PLAYBACK_DEVICE = os.getenv("BOT_SPEAKER_PLAYBACK_DEVICE") or None
BOT_JOIN_TIMEOUT_MS = int(os.getenv("BOT_JOIN_TIMEOUT_SECONDS", "90")) * 1000
BOT_UI_TIMEOUT_MS = int(os.getenv("BOT_UI_TIMEOUT_SECONDS", "20")) * 1000

# Real Chrome is fingerprinted far less aggressively than Playwright's bundled
# Chromium — Zoom blocks the latter as "an automated bot". Default to the
# installed Chrome; set BOT_BROWSER_CHANNEL="chromium" to force the bundled build.
BOT_BROWSER_CHANNEL = os.getenv("BOT_BROWSER_CHANNEL", "chrome").strip() or "chrome"

# The bot always runs on a PERSISTENT Chrome profile (real cookies, history and
# a stable fingerprint — this is what stops Zoom flagging it as a bot). It lives
# here by default; override with BOT_BROWSER_PROFILE_DIR. Whatever you sign this
# profile into (Zoom, Google) once, in the visible window, stays signed in.
BOT_BROWSER_PROFILE_DIR = (
    os.getenv("BOT_BROWSER_PROFILE_DIR")
    or str(Path(__file__).resolve().parents[2] / ".bot-profile")
)

# Attach to a Chrome you started yourself instead of launching one. Start it with
#   chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\some\dir"
# log into Zoom in it, then set BOT_CDP_URL=http://localhost:9222. This is the
# most reliable path when Zoom is aggressive about bot detection, because the
# browser is 100% a normal one you opened.
BOT_CDP_URL = os.getenv("BOT_CDP_URL") or None

# The input device the bot's own browser uses as its microphone — the recording
# side of the cable that BOT_SPEAKER_PLAYBACK_DEVICE plays the assistant's
# replies into. Without this, Chromium silently takes the *Windows default*
# microphone, which on a machine where a person is also in the call means the
# bot re-broadcasts that person's voice under the bot's name, and the
# assistant's own spoken replies never reach the meeting at all. Matched as a
# case-insensitive substring of the device label the browser reports.
BOT_VIRTUAL_MIC_LABEL = os.getenv("BOT_VIRTUAL_MIC_LABEL") or None

# Injected before any page script: routes every microphone request the meeting
# client makes to BOT_VIRTUAL_MIC_LABEL, whatever device it asked for. Echo
# cancellation / noise suppression / auto-gain are turned off for that device
# because they treat a clean synthesized voice as something to suppress.
_VIRTUAL_MIC_SCRIPT = """
(() => {
  const LABEL = __LABEL__;
  const md = navigator.mediaDevices;
  if (!LABEL || !md || !md.getUserMedia) return;
  const original = md.getUserMedia.bind(md);
  let cachedId = null;

  async function findDevice() {
    if (cachedId) return cachedId;
    const match = (list) => list.find((d) => d.kind === 'audioinput' && d.label
      && d.label.toLowerCase().includes(LABEL.toLowerCase()));
    try {
      let hit = match(await md.enumerateDevices());
      if (!hit) {
        // Device labels stay blank until the page has used a microphone once.
        const probe = await original({ audio: true });
        probe.getTracks().forEach((t) => t.stop());
        hit = match(await md.enumerateDevices());
      }
      if (hit) cachedId = hit.deviceId;
    } catch (e) {}
    return cachedId;
  }

  md.getUserMedia = async (constraints) => {
    if (constraints && constraints.audio) {
      const id = await findDevice();
      if (id) {
        const base = typeof constraints.audio === 'object' ? constraints.audio : {};
        constraints = Object.assign({}, constraints, {
          audio: Object.assign({}, base, {
            deviceId: { exact: id },
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
          }),
        });
      }
    }
    return original(constraints);
  };
})();
"""

# How often the bot re-reads the meeting UI for who is talking. Fast enough to
# attribute a short sentence, slow enough not to fight the render loop.
SPEAKER_POLL_SECONDS = 1.5
DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "debug")

# How long to let an in-flight transcription finish naturally when the user
# leaves, before giving up and cancelling it outright. Whisper `small` on a
# modest CPU has measured 20+ seconds for a single utterance.
STOP_GRACE_SECONDS = 45


class _BrowserNotReadyError(Exception):
    """Raised when Chromium binaries aren't installed yet (`playwright install`)."""


class BrowserMeetingBot:
    """Joins a meeting as a real participant and runs the live AI pipeline."""

    def __init__(self, meeting_id: int, user_id: int) -> None:
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.status = "idle"  # idle -> joining -> listening -> leaving -> left
        self.is_connected = False
        self.link: MeetingLink | None = None
        # True when playwright/sounddevice aren't installed and we fell back to
        # a no-hardware join (dev/test convenience only).
        self._simulated = False

        self._strategy = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

        self._mic_stream = None
        self._pipeline = None
        self._voice_assistant = None
        self._audio_task: asyncio.Task | None = None
        self._speaker_task: asyncio.Task | None = None

        self._active_speaker: str = "Speaker"
        self._roster: list[str] = []

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def join_meeting(self, meeting_link: str) -> dict[str, Any]:
        """Join the meeting behind a pasted link and start listening."""
        self.status = "joining"
        self.link = parse_meeting_link(meeting_link)
        self._strategy = get_strategy(
            self.link.platform,
            join_timeout_ms=BOT_JOIN_TIMEOUT_MS,
            ui_timeout_ms=BOT_UI_TIMEOUT_MS,
        )
        logger.info(
            "Bot joining %s meeting %s for app meeting %d...",
            self.link.platform, self.link.meeting_code, self.meeting_id,
        )

        try:
            await self._launch_browser()
            await self._strategy.join(
                self._page, self.link.join_url, BOT_DISPLAY_NAME, self.link.password
            )
        except (ModuleNotFoundError, _BrowserNotReadyError) as exc:
            # Playwright or its browsers aren't installed here (CI, or a dev box
            # that skipped docs/browser-bot-setup.md). Fall back to a simulated
            # join so the rest of the app stays usable.
            logger.warning(
                "Browser bot environment not ready (%s) — simulated join for meeting %d.",
                exc, self.meeting_id,
            )
            self._simulated = True
            await self._cleanup_browser()
        except JoinFailedError:
            self.status = "FAILED_JOIN"
            await self._capture_debug_info("join_failed")
            await self._cleanup_browser()
            raise
        except Exception:
            self.status = "FAILED_JOIN"
            await self._capture_debug_info("unexpected_error")
            await self._cleanup_browser()
            raise

        await self._record_bot_participant()
        self._start_audio_pipeline()
        if self._page is not None:
            self._speaker_task = asyncio.create_task(self._speaker_loop())

        self.status = "listening"
        self.is_connected = True
        return {
            "status": "listening",
            "meeting_id": self.meeting_id,
            "platform": self.link.platform,
            "simulated": self._simulated,
            "message": (
                "Assistant joined the meeting and is listening."
                if not self._simulated
                else "Browser/audio hardware not available — running in simulated mode."
            ),
        }

    async def leave_meeting(self) -> dict[str, Any]:
        """Leave the meeting, finalize notes, and close the browser."""
        self.status = "leaving"

        # The DOM-polling task is safe to cut off immediately — it holds no
        # in-flight work worth keeping.
        if self._speaker_task:
            self._speaker_task.cancel()
            try:
                await self._speaker_task
            except asyncio.CancelledError:
                pass
            self._speaker_task = None

        # The audio task is different: Whisper now runs off the event loop
        # (so it no longer freezes the server), but a single utterance can
        # still take 10-20+ seconds on a modest CPU. Cancelling it immediately
        # — the old behaviour — could cut a transcription off mid-flight and
        # lose whatever was just said, right as someone hits "leave". Stop new
        # audio from arriving first, then give the loop a grace window to
        # finish whatever it was already transcribing before force-cancelling.
        if self._mic_stream:
            self._mic_stream.stop()
            self._mic_stream = None

        if self._audio_task:
            try:
                await asyncio.wait_for(self._audio_task, timeout=STOP_GRACE_SECONDS)
            except asyncio.TimeoutError:
                logger.warning(
                    "Meeting %d: audio loop still busy after %ds — cancelling it.",
                    self.meeting_id, STOP_GRACE_SECONDS,
                )
                self._audio_task.cancel()
                try:
                    await self._audio_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
            self._audio_task = None

        report = {}
        if self._pipeline:
            report = await self._pipeline.finalize()
            self._pipeline = None

        await self._cleanup_browser()

        self.status = "left"
        self.is_connected = False
        return {
            "status": "left",
            "meeting_id": self.meeting_id,
            "notes": report,
            "message": "Assistant left the meeting and finalized the notes.",
        }

    def get_status(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "status": self.status,
            "is_connected": self.is_connected,
            "platform": self.link.platform if self.link else None,
            "simulated": self._simulated,
            "active_speaker": self._active_speaker,
            "participants": self._roster,
        }

    # ------------------------------------------------------------------
    # Browser
    # ------------------------------------------------------------------

    # Launch args shared by both the persistent-profile and throwaway paths.
    _LAUNCH_ARGS = [
        "--use-fake-ui-for-media-stream",       # auto-accept mic/cam prompt, real devices
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        # Chrome's own "Restore pages?" bubble fires whenever a profile's last
        # exit wasn't clean (including a force-killed Chrome from a previous
        # crashed run) and steals focus over the join form.
        "--disable-session-crashed-bubble",
        "--disable-features="
        # Windows' native window-occlusion tracking makes Chrome stop
        # rendering (paint solid black) when it thinks the window isn't
        # visible — trivially true for an unfocused/background automation
        # window. This is the documented fix for "Chrome renders black" under
        # Playwright/Selenium on Windows.
        "CalculateNativeWinOcclusion,"
        "IsolateOrigins,"
        "site-per-process",
        # A background-ish automation window otherwise gets Chrome's
        # power-saving throttling, which can stall Meet/Zoom's own rendering
        # and audio timers.
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
    ]

    # Injected before any page script runs. Meeting clients (Zoom especially)
    # fingerprint the browser and block anything that looks automated; this
    # papers over the tells Playwright leaves behind.
    _STEALTH_SCRIPT = """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = {
            runtime: {}, loadTimes: () => {}, csi: () => {},
            app: { isInstalled: false, InstallState: {}, RunningState: {} },
        };
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Plugin' },
                { name: 'Chrome PDF Viewer' },
                { name: 'Native Client' },
            ],
        });
        Object.defineProperty(navigator, 'mimeTypes', { get: () => [{ type: 'application/pdf' }] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        const origQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (p) => (
            p && p.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : origQuery(p)
        );
        // WebGL vendor/renderer — headless Chromium reports 'Google SwiftShader'.
        const getParam = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function (p) {
            if (p === 37445) return 'Intel Inc.';
            if (p === 37446) return 'Intel Iris OpenGL Engine';
            return getParam.call(this, p);
        };
    """

    async def _launch_browser(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        context_opts: dict[str, Any] = dict(
            permissions=["microphone", "camera"],
            viewport=None if not BOT_HEADLESS else {"width": 1366, "height": 850},
            locale="en-US",
            timezone_id="Asia/Karachi",
        )
        if BOT_HEADLESS:
            # Headless Chrome puts "HeadlessChrome" in its UA — an instant tell.
            # (Headless can't use the real audio devices anyway; this is only a
            # safety net for CI-style runs.)
            context_opts["user_agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )

        if BOT_CDP_URL:
            await self._attach_over_cdp(context_opts)
        else:
            await self._launch_persistent(context_opts)

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        await self._page.add_init_script(self._STEALTH_SCRIPT)
        if BOT_VIRTUAL_MIC_LABEL:
            await self._page.add_init_script(
                _VIRTUAL_MIC_SCRIPT.replace("__LABEL__", json.dumps(BOT_VIRTUAL_MIC_LABEL))
            )
            logger.info("Bot microphone pinned to input device matching %r.", BOT_VIRTUAL_MIC_LABEL)
        else:
            logger.warning(
                "BOT_VIRTUAL_MIC_LABEL is not set — the bot's browser will use the "
                "Windows default microphone, so spoken replies won't reach the meeting."
            )

    async def _attach_over_cdp(self, context_opts: dict[str, Any]) -> None:
        """Use a Chrome the user started with --remote-debugging-port."""
        self._browser = await self._playwright.chromium.connect_over_cdp(BOT_CDP_URL)
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else await self._browser.new_context()
        # Best-effort: apply the media-permission grant to the attached context.
        try:
            await self._context.grant_permissions(["microphone", "camera"])
        except Exception:
            pass
        logger.info("Bot browser: attached to Chrome at %s.", BOT_CDP_URL)

    async def _launch_persistent(self, context_opts: dict[str, Any]) -> None:
        """Launch a persistent Chrome profile — real cookies, stable fingerprint."""
        Path(BOT_BROWSER_PROFILE_DIR).mkdir(parents=True, exist_ok=True)

        async def _persistent(channel: str | None):
            return await self._playwright.chromium.launch_persistent_context(
                BOT_BROWSER_PROFILE_DIR,
                headless=BOT_HEADLESS,
                channel=channel,
                args=self._LAUNCH_ARGS,
                ignore_default_args=["--enable-automation"],
                **context_opts,
            )

        try:
            self._context = await _persistent(BOT_BROWSER_CHANNEL)
            logger.info(
                "Bot browser: persistent profile %s (channel=%s).",
                BOT_BROWSER_PROFILE_DIR, BOT_BROWSER_CHANNEL,
            )
        except Exception as exc:
            message = str(exc)
            if "Executable doesn't exist" in message or "playwright install" in message:
                raise _BrowserNotReadyError(
                    "No usable browser — install Google Chrome, or run "
                    "`playwright install chromium` and set BOT_BROWSER_CHANNEL=chromium."
                ) from exc
            if BOT_BROWSER_CHANNEL != "chromium":
                logger.warning(
                    "Chrome channel unavailable (%s) — using bundled Chromium.",
                    message.splitlines()[0],
                )
                self._context = await _persistent(None)
            else:
                raise
        self._browser = None

    async def _cleanup_browser(self) -> None:
        try:
            if self._page and self._strategy:
                await self._strategy.leave(self._page)
        except Exception:
            logger.debug("Leave click failed", exc_info=True)
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

    async def _capture_debug_info(self, reason: str) -> None:
        """Save a screenshot and a dump of the page's controls on a failed join.

        Meeting clients change their DOM without notice, so when a join breaks
        this is what makes the selectors fixable without asking the user to
        reproduce it by hand.
        """
        if not self._page:
            return
        try:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            base = os.path.join(DEBUG_DIR, f"join_{self.meeting_id}_{reason}_{stamp}")
            await self._page.screenshot(path=f"{base}.png", full_page=True)
            controls = await self._page.eval_on_selector_all(
                "input, button",
                "els => els.map(e => ({tag: e.tagName, id: e.id, name: e.name, "
                "type: e.type, placeholder: e.placeholder, "
                "aria_label: e.getAttribute('aria-label'), text: e.innerText}))",
            )
            with open(f"{base}.txt", "w", encoding="utf-8") as handle:
                handle.write(f"URL: {self._page.url}\n\n")
                for item in controls:
                    handle.write(f"{item}\n")
            logger.error("Saved join debug info to %s.png / %s.txt", base, base)
        except Exception:
            logger.exception("Failed to capture debug info for meeting %d", self.meeting_id)

    # ------------------------------------------------------------------
    # Who is in the room, and who is talking
    # ------------------------------------------------------------------

    async def _speaker_loop(self) -> None:
        """Keep the active speaker and roster fresh while the bot is listening."""
        assert self._page is not None and self._strategy is not None
        roster_countdown = 0
        try:
            while True:
                try:
                    speaker = await self._strategy.active_speaker(self._page)
                    if speaker:
                        self._active_speaker = speaker

                    # The roster changes far less often than the speaker does.
                    roster_countdown -= 1
                    if roster_countdown <= 0:
                        roster_countdown = 10
                        names = await self._strategy.participants(self._page)
                        if names and names != self._roster:
                            self._roster = names
                            await self._sync_participants(names)
                except Exception:
                    logger.debug("Speaker poll failed", exc_info=True)
                await asyncio.sleep(SPEAKER_POLL_SECONDS)
        except asyncio.CancelledError:
            pass

    async def _sync_participants(self, names: list[str]) -> None:
        """Persist newly-seen attendees and tell the meeting owner who joined.

        Runs off the roster poll, so a name only triggers a notification the
        first time it is seen — nobody gets pinged again just because the
        roster was re-read a few seconds later.
        """
        from app.database import SessionLocal
        from app.models import Meeting, Notification, Participant

        def _write() -> list[str]:
            with SessionLocal() as db:
                known = {
                    p.name for p in db.scalars(
                        select(Participant).where(Participant.meeting_id == self.meeting_id)
                    )
                }
                newly_seen: list[str] = []
                for name in names:
                    if name in known or name == BOT_DISPLAY_NAME:
                        continue
                    db.add(Participant(
                        meeting_id=self.meeting_id,
                        name=name,
                        role="human",
                        joined_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    ))
                    newly_seen.append(name)

                if newly_seen:
                    meeting = db.get(Meeting, self.meeting_id)
                    if meeting:
                        body = (
                            f"{newly_seen[0]} joined {meeting.title}"
                            if len(newly_seen) == 1
                            else f"{', '.join(newly_seen)} joined {meeting.title}"
                        )
                        db.add(Notification(
                            user_id=meeting.owner_id,
                            meeting_id=self.meeting_id,
                            type="participant_joined",
                            title="Someone joined the meeting" if len(newly_seen) == 1 else "People joined the meeting",
                            body=body,
                            read=False,
                        ))
                db.commit()
                return newly_seen

        await asyncio.get_event_loop().run_in_executor(None, _write)

    async def _record_bot_participant(self) -> None:
        """Record the assistant itself as an attendee of the meeting."""
        from app.database import SessionLocal
        from app.models import Participant

        def _write() -> None:
            with SessionLocal() as db:
                existing = db.scalar(
                    select(Participant).where(
                        Participant.meeting_id == self.meeting_id,
                        Participant.name == BOT_DISPLAY_NAME,
                    )
                )
                if existing:
                    return
                db.add(Participant(
                    meeting_id=self.meeting_id,
                    name=BOT_DISPLAY_NAME,
                    role="ai_agent",
                    joined_at=datetime.now(timezone.utc).replace(tzinfo=None),
                ))
                db.commit()

        await asyncio.get_event_loop().run_in_executor(None, _write)

    # ------------------------------------------------------------------
    # Audio pipeline (listen + speak)
    # ------------------------------------------------------------------

    def _start_audio_pipeline(self) -> None:
        from app.agents.audio_capture import build_capture_stream, capture_device_hint
        from app.services.live_pipeline import LiveMeetingPipeline
        from app.services.voice_assistant import AvaVoiceAssistant

        self._pipeline = LiveMeetingPipeline(
            self.meeting_id,
            speaker_resolver=lambda: self._active_speaker,
            on_text=self._handle_text,
        )
        self._voice_assistant = AvaVoiceAssistant(
            self.meeting_id, on_audio_out=self._speak_reply
        )

        try:
            # Same capture source as attach mode: by default a WASAPI loopback
            # of the speaker output, which is where this bot's own Chromium
            # window plays the meeting. The older cable-only path needed
            # Windows' default playback device repointed at a virtual cable,
            # which silenced every other app (including the user's own Zoom
            # client) for as long as the bot ran.
            self._mic_stream = build_capture_stream(
                mic_speaker_name=BOT_DISPLAY_NAME, other_speaker_name="Participant"
            )
            self._mic_stream.start()
        except ModuleNotFoundError as exc:
            logger.warning(
                "sounddevice isn't installed — no audio will be captured for "
                "meeting %d (%s). See docs/browser-bot-setup.md.",
                self.meeting_id, exc,
            )
            self._mic_stream = None
        except Exception:
            logger.exception(
                "Could not start audio capture for meeting %d — %s",
                self.meeting_id, capture_device_hint(),
            )
            self._mic_stream = None

        if self._mic_stream is not None:
            self._audio_task = asyncio.create_task(self._audio_loop())

    async def _handle_text(self, text: str) -> None:
        """One finished transcript line — let the wake-word assistant see it."""
        if self._voice_assistant:
            await self._voice_assistant.handle_transcript(text)

    async def _audio_loop(self) -> None:
        assert self._mic_stream is not None and self._pipeline is not None
        try:
            async for chunk in self._mic_stream.chunks():
                # One bad utterance (a transient file lock, a Whisper hiccup)
                # must not silently end transcription for the rest of the
                # meeting — handle it per-chunk instead of letting a single
                # exception break the whole `async for`.
                try:
                    # Returns immediately — finished lines arrive via
                    # _handle_text once the pipeline's worker transcribes them.
                    await self._pipeline.add_chunk(chunk)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Skipped one audio chunk for meeting %d after an error; "
                        "still listening.", self.meeting_id,
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Audio loop crashed for meeting %d", self.meeting_id)

    async def _speak_reply(self, wav_bytes: bytes) -> None:
        """Play Ava's TTS reply into the outbound virtual cable — the room hears it."""
        from app.audio.device_io import play_wav_bytes

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, play_wav_bytes, wav_bytes, BOT_SPEAKER_PLAYBACK_DEVICE,
            )
        except ModuleNotFoundError:
            logger.debug("sounddevice not installed — Ava's reply stayed browser-only.")
        except Exception:
            logger.exception("Failed to play Ava's reply into meeting %d", self.meeting_id)
