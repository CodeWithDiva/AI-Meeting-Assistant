"""Live meeting audio → transcript → notes, for our own browser bot.

Replaces the old `rtms_transcription` module (Zoom RTMS is gone). The bot feeds
raw PCM16 chunks in with :meth:`LiveMeetingPipeline.add_chunk` and this module:

* cuts the stream at **speech boundaries** instead of every fixed 4 seconds,
  so Urdu and English sentences are transcribed whole rather than sliced
  mid-word (the single biggest cause of garbage transcripts before);
* keeps the meeting's language stable across windows via `StickyLanguage`;
* attributes each line to whoever the bot reports as the active speaker;
* optionally writes the full session to a WAV file when the meeting owner has
  opted into recording;
* on :meth:`finalize`, analyzes the transcript and persists summary, decisions
  and **assigned, notified** tasks.
"""

from __future__ import annotations

import array
import asyncio
import logging
import wave
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from sqlalchemy import select

from app.ai.service import analyze_meeting
from app.database import SessionLocal
from app.models import Meeting, Participant, Recording, TranscriptSegment
from app.services.action_items import persist_meeting_notes
from app.transcription.base import FasterWhisperService, StickyLanguage

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2

# Utterance segmentation. Audio is buffered until the speaker pauses, so a
# window lines up with a sentence rather than a stopwatch.
SILENCE_RMS = 320          # below this, a chunk counts as silence
SILENCE_HANG_MS = 700      # pause that ends an utterance
MIN_UTTERANCE_MS = 1_200   # ignore coughs/keyboard clicks
MAX_UTTERANCE_MS = 20_000  # hard cut so one long talker still streams

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "recordings"

SpeakerResolver = Callable[[], str | None]


class LiveMeetingPipeline:
    """Buffer live PCM audio, transcribe whole utterances, and persist them."""

    def __init__(
        self,
        meeting_id: int,
        sample_rate: int = SAMPLE_RATE,
        speaker_resolver: SpeakerResolver | None = None,
    ) -> None:
        self.meeting_id = meeting_id
        self.sample_rate = sample_rate
        # Called at transcription time to ask the bot "who is talking right
        # now?" — the browser bot reads this off the meeting UI.
        self._speaker_resolver = speaker_resolver

        self._service = FasterWhisperService()
        self._language = StickyLanguage()
        self._lock = asyncio.Lock()

        self._buffer = bytearray()
        self._silence_ms = 0
        self._offset = 0.0

        self._recorder: wave.Wave_write | None = None
        self._recording_path: Path | None = None
        self._recording_checked = False

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    async def add_chunk(self, chunk: bytes) -> list[str]:
        """Add PCM16 mono audio; return text for any utterance that completed."""
        if not chunk:
            return []

        async with self._lock:
            self._write_to_recording(chunk)
            self._buffer.extend(chunk)

            chunk_ms = len(chunk) / (self.sample_rate * BYTES_PER_SAMPLE) * 1000
            if _rms(chunk) < SILENCE_RMS:
                self._silence_ms += chunk_ms
            else:
                self._silence_ms = 0

            buffered_ms = len(self._buffer) / (self.sample_rate * BYTES_PER_SAMPLE) * 1000
            ended_on_pause = (
                self._silence_ms >= SILENCE_HANG_MS and buffered_ms >= MIN_UTTERANCE_MS
            )
            if not ended_on_pause and buffered_ms < MAX_UTTERANCE_MS:
                return []

            window = bytes(self._buffer)
            self._buffer.clear()
            self._silence_ms = 0

            if _rms(window) < SILENCE_RMS:
                # Pure silence — advance the clock but don't ask Whisper, which
                # would only hallucinate filler onto the transcript.
                self._offset += buffered_ms / 1000
                return []

            return await self._transcribe(window, buffered_ms / 1000)

    async def flush(self) -> list[str]:
        """Transcribe whatever is left in the buffer at the end of a meeting."""
        async with self._lock:
            if not self._buffer:
                return []
            window = bytes(self._buffer)
            self._buffer.clear()
            duration = len(window) / (self.sample_rate * BYTES_PER_SAMPLE)
            if _rms(window) < SILENCE_RMS:
                self._offset += duration
                return []
            return await self._transcribe(window, duration)

    # ------------------------------------------------------------------
    # Transcribe + persist
    # ------------------------------------------------------------------

    async def _transcribe(self, pcm_data: bytes, duration: float) -> list[str]:
        with NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            path = Path(temp_file.name)
        try:
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(BYTES_PER_SAMPLE)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(pcm_data)
            result = await self._service.transcribe(
                path, language=self._language.language_for_next_window()
            )
        except Exception:
            logger.exception("Live transcription failed for meeting %d", self.meeting_id)
            return []
        finally:
            path.unlink(missing_ok=True)

        self._language.observe(result.language, result.language_probability)

        texts = [segment.text.strip() for segment in result.segments if segment.text.strip()]
        if not texts:
            self._offset += duration
            return []

        speaker = self._current_speaker()
        with SessionLocal() as db:
            meeting = db.scalar(select(Meeting).where(Meeting.id == self.meeting_id))
            if not meeting:
                return []
            for segment in result.segments:
                text = segment.text.strip()
                if not text:
                    continue
                db.add(TranscriptSegment(
                    meeting_id=self.meeting_id,
                    text=text,
                    start_time=self._offset + segment.start,
                    end_time=self._offset + segment.end,
                    speaker_label=speaker,
                    source="live_bot",
                ))
            meeting.transcript = _append_transcript(meeting.transcript, speaker, texts)
            db.commit()

        await self._broadcast(texts, speaker, result.language)
        self._offset += duration
        return texts

    def _current_speaker(self) -> str:
        """Whoever the bot says is talking, else a neutral label."""
        if not self._speaker_resolver:
            return "Speaker"
        try:
            return self._speaker_resolver() or "Speaker"
        except Exception:
            logger.debug("Speaker resolver failed", exc_info=True)
            return "Speaker"

    async def _broadcast(self, texts: list[str], speaker: str, language: str | None) -> None:
        try:
            from app.services.ws_manager import ws_manager

            for text in texts:
                await ws_manager.broadcast(
                    self.meeting_id,
                    "transcript_live",
                    {"speaker": speaker, "text": text, "language": language},
                )
        except Exception as exc:
            logger.debug("Failed to broadcast transcript_live: %s", exc)

    # ------------------------------------------------------------------
    # Recording (opt-in)
    # ------------------------------------------------------------------

    def _write_to_recording(self, chunk: bytes) -> None:
        """Append audio to the session WAV, opening it on the first chunk.

        Recording stays off unless the meeting owner explicitly enabled it —
        the consent check lives in the `Recording` row, and is read once.
        """
        if not self._recording_checked:
            self._recording_checked = True
            self._open_recording()
        if self._recorder is not None:
            try:
                self._recorder.writeframes(chunk)
            except Exception:
                logger.exception("Recording write failed for meeting %d", self.meeting_id)
                self._close_recording()

    def _open_recording(self) -> None:
        with SessionLocal() as db:
            recording = db.scalar(
                select(Recording).where(Recording.meeting_id == self.meeting_id)
            )
            if not recording or not recording.enabled:
                logger.info("Recording is off for meeting %d — audio is not stored.", self.meeting_id)
                return

        try:
            RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            self._recording_path = RECORDINGS_DIR / f"meeting-{self.meeting_id}-{stamp}.wav"
            self._recorder = wave.open(str(self._recording_path), "wb")
            self._recorder.setnchannels(1)
            self._recorder.setsampwidth(BYTES_PER_SAMPLE)
            self._recorder.setframerate(self.sample_rate)
            logger.info("Recording meeting %d to %s", self.meeting_id, self._recording_path)
        except Exception:
            logger.exception("Could not start recording for meeting %d", self.meeting_id)
            self._recorder = None
            self._recording_path = None

    def _close_recording(self) -> None:
        if self._recorder is None:
            return
        try:
            self._recorder.close()
        except Exception:
            logger.exception("Error closing recording for meeting %d", self.meeting_id)
        self._recorder = None

        if not self._recording_path or not self._recording_path.exists():
            return
        size = self._recording_path.stat().st_size
        with SessionLocal() as db:
            recording = db.scalar(
                select(Recording).where(Recording.meeting_id == self.meeting_id)
            )
            if recording:
                recording.file_path = str(self._recording_path)
                recording.file_size_bytes = size
                db.commit()
        logger.info("Saved recording for meeting %d (%d bytes)", self.meeting_id, size)

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------

    async def finalize(self) -> dict:
        """Flush audio, then generate and persist the meeting's notes."""
        await self.flush()
        self._close_recording()

        with SessionLocal() as db:
            meeting = db.scalar(select(Meeting).where(Meeting.id == self.meeting_id))
            transcript = meeting.transcript if meeting else None
            # The names the bot read off the meeting UI are what let the model
            # attribute each task to a real person.
            participants = [
                p.name for p in db.scalars(
                    select(Participant).where(
                        Participant.meeting_id == self.meeting_id,
                        Participant.role == "human",
                    )
                )
            ]

        if not transcript or not transcript.strip():
            logger.info("Meeting %d produced no transcript — nothing to analyze.", self.meeting_id)
            return {"decisions": 0, "action_items": 0, "assigned": 0, "unassigned": 0}

        notes = await analyze_meeting(transcript, participants)
        with SessionLocal() as db:
            report = persist_meeting_notes(self.meeting_id, notes, db, notify_summary=True)
            db.commit()

        try:
            from app.services.ws_manager import ws_manager

            await ws_manager.broadcast(self.meeting_id, "notes_ready", report)
        except Exception:
            logger.debug("Failed to broadcast notes_ready", exc_info=True)
        return report


def _rms(pcm_data: bytes) -> float:
    """Root-mean-square loudness of PCM16 audio (0 for an empty buffer).

    `audioop.rms` did this until Python 3.13 removed the module, so this uses
    numpy where available and falls back to stdlib `array` otherwise — the
    backend must not hard-depend on numpy just to measure loudness.
    """
    usable = len(pcm_data) - (len(pcm_data) % BYTES_PER_SAMPLE)
    if usable <= 0:
        return 0.0
    data = pcm_data[:usable]

    try:
        import numpy as np

        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(np.square(samples))))
    except ImportError:
        samples = array.array("h")
        samples.frombytes(data)
        return (sum(s * s for s in samples) / len(samples)) ** 0.5


def _append_transcript(existing: str | None, speaker: str, texts: list[str]) -> str:
    """Append speaker-attributed lines to the meeting's flat transcript.

    Keeping "[Ali]: ..." in the flat text matters: it is what the LLM reads
    when deciding who a task belongs to.
    """
    line = f"[{speaker}]: " + " ".join(texts)
    return f"{existing}\n{line}".strip() if existing else line
