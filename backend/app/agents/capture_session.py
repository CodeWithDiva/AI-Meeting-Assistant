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

# How long to let an in-flight transcription finish naturally when the user
# leaves, before giving up and cancelling it outright. Whisper `small` on a
# modest CPU has measured 20+ seconds for a single utterance.
STOP_GRACE_SECONDS = 45

# Which audio source to capture lives in app.agents.audio_capture, shared with
# the browser bot so the two modes cannot drift apart.


class CaptureSession:
    """Listen to a meeting through the capture device and run the AI pipeline.

    Mirrors :class:`app.agents.browser_bot.BrowserMeetingBot`'s public surface
    (``status``, ``get_status``, ``leave_meeting``) so the agent router can hold
    either kind of session in the same registry.
    """

    def __init__(
        self,
        meeting_id: int,
        user_id: int,
        *,
        enable_voice: bool = True,
        display_name: str | None = None,
    ) -> None:
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.enable_voice = enable_voice
        # What your own voice is labelled as in the transcript. The other
        # side of the call has no name to attribute (attach mode never reads
        # the meeting UI), so it's labelled generically.
        self.display_name = (display_name or "").strip() or "You"
        self.status = "idle"  # idle -> listening -> leaving -> left
        self.is_connected = False
        self._simulated = False

        self._mic_stream = None
        self._pipeline = None
        self._voice_assistant = None
        self._audio_task: asyncio.Task | None = None
        # Whether the user's own mic was actually captured (attach + loopback
        # mode) — set once start() runs. See get_status().
        self.mic_captured = False
        self.mic_error: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> dict[str, Any]:
        """Open the capture device and begin transcribing."""
        from app.agents.audio_capture import (
            BOT_SPEAKER_PLAYBACK_DEVICE,
            CAPTURE_MODE,
            MIX_MIC,
            build_capture_stream,
            capture_device_hint,
        )
        from app.services.live_pipeline import LiveMeetingPipeline
        from app.services.voice_assistant import AvaVoiceAssistant

        self.status = "joining"
        # Label each transcript line with whichever source (your mic vs. the
        # loopback) was louder for that utterance — see MicCaptureStream's
        # last_speaker_label / _mix_in_mic.
        self._pipeline = LiveMeetingPipeline(
            self.meeting_id,
            speaker_resolver=lambda: getattr(self._mic_stream, "last_speaker_label", None),
            on_text=self._handle_text,
        )
        if self.enable_voice:
            self._voice_assistant = AvaVoiceAssistant(
                self.meeting_id, on_audio_out=self._speak_reply
            )
            self._playback_device = BOT_SPEAKER_PLAYBACK_DEVICE

        use_loopback = CAPTURE_MODE != "cable"
        try:
            self._mic_stream = build_capture_stream(mic_speaker_name=self.display_name)
            self._mic_stream.start()
        except ModuleNotFoundError as exc:
            logger.warning(
                "sounddevice not installed — capture session for meeting %d is "
                "simulated (%s).", self.meeting_id, exc,
            )
            self._simulated = True
        except Exception as exc:
            self.status = "FAILED_JOIN"
            hint = f"Could not start audio capture — {capture_device_hint()}"
            raise RuntimeError(f"{hint} ({exc})") from exc

        await self._record_listener_participant()

        if self._mic_stream is not None:
            self._audio_task = asyncio.create_task(self._audio_loop())

        # Cache mic status now — leave_meeting() nulls out _mic_stream.
        wants_mic = use_loopback and MIX_MIC and not self._simulated
        self.mic_captured = bool(self._mic_stream and getattr(self._mic_stream, "mic_active", False))
        self.mic_error = getattr(self._mic_stream, "mic_error", None) if self._mic_stream else None

        self.status = "listening"
        self.is_connected = True
        message = (
            "Listening to the meeting through the capture device."
            if not self._simulated
            else "Audio hardware not available — capture session is simulated."
        )
        if wants_mic and not self.mic_captured:
            message += (
                " Warning: your own microphone could not be captured "
                f"({self.mic_error or 'unknown error'}) — only what plays through "
                "your speakers (the other participants) will be transcribed."
            )
            logger.warning(
                "Meeting %d: mic not captured in attach mode — %s",
                self.meeting_id, self.mic_error,
            )
        return {
            "status": "listening",
            "meeting_id": self.meeting_id,
            "mode": "attach",
            "simulated": self._simulated,
            "mic_captured": self.mic_captured,
            "message": message,
        }

    async def leave_meeting(self) -> dict[str, Any]:
        """Stop listening and finalize notes, decisions and tasks."""
        self.status = "leaving"

        # Whisper now runs off the event loop (so it no longer freezes the
        # server), but a single utterance can still take 10-20+ seconds on a
        # modest CPU. Cancelling the audio task immediately — the old
        # behaviour — could cut that transcription off mid-flight and lose
        # whatever was just said, right when someone hits "leave". Stop new
        # audio from arriving first, then give the loop a grace window to
        # finish whatever it was already transcribing before force-cancelling.
        #
        # `self._mic_stream` is left set (only `.stop()` is called here, not
        # nulled) until the audio task actually finishes: the speaker_resolver
        # passed to LiveMeetingPipeline reads `self._mic_stream.last_speaker_label`
        # on every call, including for whatever utterance is still in flight —
        # clearing the reference early made every in-flight transcription at
        # leave time land as the generic "Speaker" instead of "You"/"Participant".
        stream_to_stop = self._mic_stream
        if stream_to_stop:
            stream_to_stop.stop()

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
            "mic_captured": self.mic_captured if self.is_connected else None,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _audio_loop(self) -> None:
        assert self._mic_stream is not None and self._pipeline is not None
        try:
            async for chunk in self._mic_stream.chunks():
                # A single bad utterance (a transient file-lock, a Whisper
                # hiccup) must not take down capture for the rest of the
                # meeting — that previously went quiet with no visible sign
                # beyond "the transcript stopped". Handle per-chunk instead
                # of letting one exception end the whole `async for`.
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
            logger.exception("Capture audio loop crashed for meeting %d", self.meeting_id)

    async def _handle_text(self, text: str) -> None:
        """One finished transcript line — let the wake-word assistant see it."""
        if self._voice_assistant:
            await self._voice_assistant.handle_transcript(text)

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
