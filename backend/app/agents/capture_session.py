"""Attach mode — transcribe a meeting a human already joined.

No browser, no bot participant, no meeting-platform login. The person runs the
meeting in their normal Zoom/Meet/Teams client; this session listens to the
meeting audio through the same virtual audio cable the browser bot uses
(``BOT_MIC_CAPTURE_DEVICE``) and runs the identical transcription → notes →
tasks pipeline.

Trade-off vs. the browser agent: there is no meeting UI to read, so transcript
lines are attributed to diarised "Speaker 1 / Speaker 2" rather than real
names. The LLM still resolves who owns each task from the transcript itself.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)

# "loopback" — capture whatever plays on the speakers/headphones the user
#   already listens on (WASAPI loopback). No Windows or Zoom audio settings to
#   change. Default for attach mode.
# "cable"    — capture from BOT_MIC_CAPTURE_DEVICE (the virtual audio cable the
#   browser bot uses). Requires the meeting audio to be routed into that cable.
CAPTURE_MODE = os.getenv("BOT_CAPTURE_MODE", "loopback").strip().lower()
# Optional: a specific output device to loop back from. Blank = current default.
LOOPBACK_DEVICE = os.getenv("BOT_LOOPBACK_DEVICE") or None
# In loopback mode, also capture the user's own microphone and mix it in —
# loopback alone carries only the *other* participants. Default on.
MIX_MIC = os.getenv("BOT_MIX_MIC", "true").strip().lower() not in {"0", "false", "no"}
# Optional: which input device is the user's mic. Blank = system default input.
MIC_INPUT_DEVICE = os.getenv("BOT_MIC_INPUT_DEVICE") or None


class CaptureSession:
    """Listen to a meeting through the capture device and run the AI pipeline.

    Mirrors :class:`app.agents.browser_bot.BrowserMeetingBot`'s public surface
    (``status``, ``get_status``, ``leave_meeting``) so the agent router can hold
    either kind of session in the same registry.
    """

    def __init__(self, meeting_id: int, user_id: int, *, enable_voice: bool = True) -> None:
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.enable_voice = enable_voice
        self.status = "idle"  # idle -> listening -> leaving -> left
        self.is_connected = False
        self._simulated = False

        self._mic_stream = None
        self._pipeline = None
        self._voice_assistant = None
        self._audio_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> dict[str, Any]:
        """Open the capture device and begin transcribing."""
        from app.agents.browser_bot import (
            BOT_MIC_CAPTURE_DEVICE,
            BOT_SPEAKER_PLAYBACK_DEVICE,
        )
        from app.audio.device_io import MicCaptureStream
        from app.services.live_pipeline import LiveMeetingPipeline
        from app.services.voice_assistant import AvaVoiceAssistant

        self.status = "joining"
        self._pipeline = LiveMeetingPipeline(self.meeting_id)
        if self.enable_voice:
            self._voice_assistant = AvaVoiceAssistant(
                self.meeting_id, on_audio_out=self._speak_reply
            )
            self._playback_device = BOT_SPEAKER_PLAYBACK_DEVICE

        use_loopback = CAPTURE_MODE != "cable"
        device = LOOPBACK_DEVICE if use_loopback else BOT_MIC_CAPTURE_DEVICE
        try:
            self._mic_stream = MicCaptureStream(
                device,
                loopback=use_loopback,
                mix_mic=use_loopback and MIX_MIC,
                mic_device=MIC_INPUT_DEVICE,
            )
            self._mic_stream.start()
        except ModuleNotFoundError as exc:
            logger.warning(
                "sounddevice not installed — capture session for meeting %d is "
                "simulated (%s).", self.meeting_id, exc,
            )
            self._simulated = True
        except Exception as exc:
            self.status = "FAILED_JOIN"
            if use_loopback:
                hint = (
                    "Could not start loopback capture of the speaker output. "
                    "Set BOT_LOOPBACK_DEVICE in .env to the exact name of the device "
                    "you hear the meeting on (see "
                    "`python scripts/list_audio_devices.py`), or set "
                    "BOT_CAPTURE_MODE=cable to use the virtual audio cable instead."
                )
            else:
                hint = (
                    f"Could not open the capture device {BOT_MIC_CAPTURE_DEVICE!r}. "
                    "Check BOT_MIC_CAPTURE_DEVICE in .env against "
                    "`python scripts/list_audio_devices.py`."
                )
            raise RuntimeError(f"{hint} ({exc})") from exc

        await self._record_listener_participant()

        if self._mic_stream is not None:
            self._audio_task = asyncio.create_task(self._audio_loop())

        self.status = "listening"
        self.is_connected = True
        return {
            "status": "listening",
            "meeting_id": self.meeting_id,
            "mode": "attach",
            "simulated": self._simulated,
            "message": (
                "Listening to the meeting through the capture device."
                if not self._simulated
                else "Audio hardware not available — capture session is simulated."
            ),
        }

    async def leave_meeting(self) -> dict[str, Any]:
        """Stop listening and finalize notes, decisions and tasks."""
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

        report: dict[str, Any] = {}
        if self._pipeline:
            report = await self._pipeline.finalize()
            self._pipeline = None

        self.status = "left"
        self.is_connected = False
        return {
            "status": "left",
            "meeting_id": self.meeting_id,
            "mode": "attach",
            "notes": report,
            "message": "Stopped listening and finalized the notes.",
        }

    def get_status(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "status": self.status,
            "is_connected": self.is_connected,
            "platform": "attach",
            "simulated": self._simulated,
            "active_speaker": "Speaker",
            "participants": [],
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _audio_loop(self) -> None:
        assert self._mic_stream is not None and self._pipeline is not None
        try:
            async for chunk in self._mic_stream.chunks():
                texts = await self._pipeline.add_chunk(chunk)
                if self._voice_assistant:
                    for text in texts:
                        await self._voice_assistant.handle_transcript(text)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Capture audio loop crashed for meeting %d", self.meeting_id)

    async def _speak_reply(self, wav_bytes: bytes) -> None:
        from app.audio.device_io import play_wav_bytes

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, play_wav_bytes, wav_bytes, self._playback_device,
            )
        except ModuleNotFoundError:
            logger.debug("sounddevice not installed — Ava's reply was not played out.")
        except Exception:
            logger.exception("Failed to play Ava's reply for meeting %d", self.meeting_id)

    async def _record_listener_participant(self) -> None:
        from app.database import SessionLocal
        from app.models import Participant

        def _write() -> None:
            with SessionLocal() as db:
                exists = db.scalar(
                    select(Participant).where(
                        Participant.meeting_id == self.meeting_id,
                        Participant.name == "AI Assistant (listening)",
                    )
                )
                if exists:
                    return
                db.add(Participant(
                    meeting_id=self.meeting_id,
                    name="AI Assistant (listening)",
                    role="ai_agent",
                    joined_at=datetime.now(timezone.utc).replace(tzinfo=None),
                ))
                db.commit()

        await asyncio.get_event_loop().run_in_executor(None, _write)
