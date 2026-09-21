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
import os
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
#
# The speech/silence threshold adapts to the room instead of being a fixed
# number: a phone-as-microphone over Wi-Fi, or a voice already squashed by
# Zoom's codec, can sit far below any constant you pick, and a constant that
# is too high silently discards whole sentences as "silence" — the words just
# never reach Whisper. So the noise floor is measured continuously and speech
# is anything meaningfully above it.
SILENCE_RMS = 320          # starting guess, immediately adapted (see _speech_floor)
NOISE_FLOOR_MARGIN = 2.2   # speech must be this much louder than the noise floor
MIN_SPEECH_RMS = 90        # never treat near-digital-silence as speech
MAX_SPEECH_RMS = 400       # never demand more than this, however noisy the room
# A pause has to be a real one to end an utterance. At 700ms nearly every
# sentence boundary cut the audio, and since Whisper charges for a full
# 30-second window per call however short the audio, that meant many tiny,
# expensive windows (measured: 9 windows for 37s of speech).
SILENCE_HANG_MS = 1_100    # pause that ends an utterance
MIN_UTTERANCE_MS = 1_200   # floor on a window's total length (speech + closing pause)
# Speech (not counting the pause that closes it) needed for a window to be
# worth sending to Whisper at all — a cough or keyboard click is shorter than
# this. Measured on speech alone because the closing pause is now long enough
# (SILENCE_HANG_MS) that a lone click plus its pause used to clear the old
# whole-window minimum and cost a full transcription pass.
MIN_SPEECH_MS = 500
MAX_UTTERANCE_MS = 20_000  # hard cut so one long talker still streams
# Before that hard cut lands mid-word, look for the next natural pause: once an
# utterance has run this long, an ordinary short breath is enough to end it.
# (Measured: a 20s hard cut split "...ہو تو ابھی بتا دیں" across two windows
# and the 3s tail was lost.)
SOFT_CUT_AFTER_MS = 12_000
SOFT_HANG_MS = 450
# Upper bound when the worker merges queued utterances into one window. Well
# under Whisper's own 30s window: measured, a 26s merged window transcribed
# Urdu noticeably worse than shorter ones (it dropped and garbled a sentence),
# while ~16s still cuts the per-second cost by half or more.
MAX_MERGED_WINDOW_S = 16.0

# How long to keep draining queued utterances once the meeting ends. Whisper
# on a slow CPU can be several minutes behind a long meeting; the tail of the
# conversation is usually where the decisions are, so it is worth waiting for.
FINALIZE_DRAIN_SECONDS = float(os.getenv("BOT_FINALIZE_DRAIN_SECONDS", "600"))

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "recordings"

SpeakerResolver = Callable[[], str | None]


class LiveMeetingPipeline:
    """Buffer live PCM audio, transcribe whole utterances, and persist them."""

    def __init__(
        self,
        meeting_id: int,
        sample_rate: int = SAMPLE_RATE,
        speaker_resolver: SpeakerResolver | None = None,
        on_text: Callable[[str], "asyncio.Future | None"] | None = None,
    ) -> None:
        self.meeting_id = meeting_id
        self.sample_rate = sample_rate
        # Called when an utterance *ends* to ask "who was talking?" — the
        # browser bot reads this off the meeting UI. Captured at segmentation
        # time, not at transcription time, because transcription can finish
        # long after the words were actually spoken.
        self._speaker_resolver = speaker_resolver
        # Awaited for each finished line — this is how the wake-word assistant
        # hears the transcript.
        self._on_text = on_text

        self._service = FasterWhisperService()
        self._language = StickyLanguage()
        # Language of the last window that produced text — breaks ties only.
        self._last_language: str | None = None
        self._lock = asyncio.Lock()
        # True while the transcript is behind the meeting — see _worker_loop.
        self._fast_mode = False

        self._buffer = bytearray()
        self._silence_ms = 0
        self._speech_ms = 0
        self._offset = 0.0
        # Rolling estimate of how loud this room is when nobody is talking,
        # used to decide what counts as speech. See _speech_floor().
        self._noise_floor: float | None = None

        # Finished utterances waiting to be transcribed. Whisper on a weak CPU
        # runs several times slower than real time, so transcribing inline
        # stalled audio ingestion for the whole call and the back half of a
        # meeting simply never got captured. Queuing decouples the two: audio
        # is always consumed at real speed, and the transcript catches up —
        # lagging during the meeting, complete by the end.
        # Created lazily in _ensure_worker(), inside the loop that will use it:
        # an asyncio.Queue binds to the loop it first blocks on, so building it
        # here would tie the pipeline to whichever loop happened to construct it.
        self._work: asyncio.Queue[tuple[bytes, float, float, str]] | None = None
        self._worker: asyncio.Task | None = None

        self._recorder: wave.Wave_write | None = None
        self._recording_path: Path | None = None
        self._recording_checked = False

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    async def add_chunk(self, chunk: bytes) -> list[str]:
        """Add PCM16 mono audio. Completed utterances are queued, not awaited.

        Always returns `[]` — finished text is delivered through the `on_text`
        callback once the background worker has transcribed it. Returning it
        here would mean blocking the caller (and therefore audio capture) for
        the length of a Whisper run.
        """
        if not chunk:
            return []

        self._ensure_worker()

        async with self._lock:
            self._write_to_recording(chunk)
            self._buffer.extend(chunk)

            chunk_ms = len(chunk) / (self.sample_rate * BYTES_PER_SAMPLE) * 1000
            level = _rms(chunk)
            floor = self._speech_floor(level)
            if level < floor:
                self._silence_ms += chunk_ms
            else:
                self._silence_ms = 0
                self._speech_ms += chunk_ms

            buffered_ms = len(self._buffer) / (self.sample_rate * BYTES_PER_SAMPLE) * 1000
            hang = SILENCE_HANG_MS if buffered_ms < SOFT_CUT_AFTER_MS else SOFT_HANG_MS
            paused = self._silence_ms >= hang
            if paused and self._speech_ms < MIN_SPEECH_MS:
                # A cough or click followed by quiet: not worth a Whisper pass.
                # Drop it now rather than letting silence pile up around it.
                self._offset += buffered_ms / 1000
                self._buffer.clear()
                self._silence_ms = 0
                self._speech_ms = 0
                return []

            ended_on_pause = paused and buffered_ms >= MIN_UTTERANCE_MS
            if not ended_on_pause and buffered_ms < MAX_UTTERANCE_MS:
                return []

            window = bytes(self._buffer)
            self._buffer.clear()
            self._silence_ms = 0
            self._speech_ms = 0
            duration = buffered_ms / 1000

            if _rms(window) < self._speech_floor():
                # Pure silence — advance the clock but don't ask Whisper, which
                # would only hallucinate filler onto the transcript.
                self._offset += duration
                return []

            self._queue_window(window, duration)
            return []

    async def flush(self) -> list[str]:
        """Queue whatever is left in the buffer at the end of a meeting."""
        self._ensure_worker()
        async with self._lock:
            if not self._buffer:
                return []
            window = bytes(self._buffer)
            self._buffer.clear()
            self._silence_ms = 0
            self._speech_ms = 0
            duration = len(window) / (self.sample_rate * BYTES_PER_SAMPLE)
            if _rms(window) < self._speech_floor():
                self._offset += duration
                return []
            self._queue_window(window, duration)
            return []

    def _speech_floor(self, level: float | None = None) -> float:
        """The loudness above which audio counts as speech, tracked live.

        Feeding a level in also updates the noise-floor estimate, but only
        downward-biased: quiet chunks pull the floor down quickly, loud ones
        (i.e. probably speech) barely move it. That way the floor settles on
        the room's background rather than creeping up to swallow the speaker.
        """
        if level is not None:
            if self._noise_floor is None:
                self._noise_floor = level
            elif level < self._noise_floor:
                self._noise_floor = 0.7 * self._noise_floor + 0.3 * level
            else:
                self._noise_floor = 0.995 * self._noise_floor + 0.005 * level

        floor = (self._noise_floor or 0.0) * NOISE_FLOOR_MARGIN
        return max(MIN_SPEECH_RMS, min(floor, MAX_SPEECH_RMS))

    def _queue_window(self, window: bytes, duration: float) -> None:
        """Hand a finished utterance to the transcription worker."""
        # Claim this utterance's slot on the meeting timeline now, so queued
        # work keeps correct timestamps however far behind it runs.
        start_at = self._offset
        self._offset += duration
        assert self._work is not None  # _ensure_worker() ran first
        self._work.put_nowait((window, duration, start_at, self._current_speaker()))
        depth = self._work.qsize()
        if depth > 3:
            logger.info(
                "Meeting %d: %d utterances waiting to transcribe — the transcript "
                "is running behind the meeting and will catch up.",
                self.meeting_id, depth,
            )

    def _ensure_worker(self) -> None:
        if self._work is None:
            self._work = asyncio.Queue()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        """Transcribe queued utterances, merging whatever has piled up.

        Whisper pads every window to 30 seconds before encoding, so a 2-second
        utterance costs the same ~10s of CPU (measured, `small` on this
        machine) as a 25-second one. Transcribing each short utterance alone
        therefore ran at roughly 3x real time — 117s to transcribe 37s of
        continuous Urdu — and the transcript fell further behind the longer
        the meeting ran. So when utterances are waiting, consecutive ones from
        the same speaker are joined into a single window (up to
        MAX_MERGED_WINDOW_S) and paid for once. When the queue is empty an
        utterance is still transcribed immediately, by itself, so a quiet
        meeting keeps its low latency.
        """
        carry = None
        try:
            while True:
                first = carry if carry is not None else await self._work.get()
                carry = None
                batch = [first]
                total = first[1]
                while True:
                    try:
                        nxt = self._work.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if nxt[3] != first[3] or total + nxt[1] > MAX_MERGED_WINDOW_S:
                        carry = nxt  # starts the next batch
                        break
                    batch.append(nxt)
                    total += nxt[1]

                window = b"".join(item[0] for item in batch)
                start_at, speaker = first[2], first[3]
                # Anything still waiting (or just merged) means the transcript
                # is behind the meeting: take the quick model for this one so
                # the backlog actually clears. An empty queue means we are
                # caught up, so the accurate model gets to run.
                self._fast_mode = (
                    len(batch) > 1 or carry is not None or not self._work.empty()
                )
                try:
                    texts = await self._transcribe(window, total, start_at, speaker)
                    if self._on_text:
                        for text in texts:
                            try:
                                await self._on_text(text)
                            except Exception:
                                logger.exception(
                                    "on_text callback failed for meeting %d", self.meeting_id
                                )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # One bad utterance must not stop the queue draining.
                    logger.exception(
                        "Transcription worker failed on one utterance for meeting %d",
                        self.meeting_id,
                    )
                finally:
                    # Exactly once per get()/get_nowait(), including on
                    # cancellation, or _drain()'s join() would hang forever.
                    for _ in batch:
                        self._work.task_done()
        finally:
            if carry is not None:
                self._work.task_done()

    async def _drain(self, timeout: float) -> None:
        """Wait for queued utterances to finish, up to `timeout` seconds."""
        if self._work is None:
            return
        # Not `if self._work.empty(): return` — an empty queue does not mean
        # nothing is left: the worker takes the last utterance *out* of the
        # queue before transcribing it, so "empty" was true for the whole time
        # the final window was still being decoded. Finalizing then went ahead
        # and cancelled it, and the end of every meeting — where the decisions
        # usually are — could be lost. join() counts in-flight work too, and
        # returns immediately when there is truly nothing left.
        if self._work.qsize():
            logger.info(
                "Meeting %d: waiting for %d queued utterance(s) to transcribe...",
                self.meeting_id, self._work.qsize(),
            )
        try:
            await asyncio.wait_for(self._work.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Meeting %d: %d utterance(s) still untranscribed after %.0fs — "
                "finalizing without them.",
                self.meeting_id, self._work.qsize(), timeout,
            )

    # ------------------------------------------------------------------
    # Transcribe + persist
    # ------------------------------------------------------------------

    async def _transcribe(
        self,
        pcm_data: bytes,
        duration: float,
        start_at: float,
        speaker: str,
    ) -> list[str]:
        """Transcribe one queued utterance and persist it.

        `start_at` and `speaker` are captured when the utterance *ended*, not
        now — this can run well after the words were spoken, so deriving
        either here would misattribute both the timestamp and the talker.
        """
        with NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            path = Path(temp_file.name)
        try:
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(BYTES_PER_SAMPLE)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(_normalize_level(pcm_data))
            # The language is decided fresh for every window (Urdu vs English,
            # biased to Urdu), not locked from the first one. Locking meant one
            # noisy opening window could put a whole Urdu meeting on English —
            # which Whisper then "transcribes" as invented English (seen live).
            # An operator-forced language (WHISPER_LANGUAGE) still wins; the
            # previous window's language only breaks ties.
            result = await self._service.transcribe(
                path,
                language=self._language.forced,
                fast=self._fast_mode,
                prefer=self._last_language,
            )
        except Exception:
            logger.exception("Live transcription failed for meeting %d", self.meeting_id)
            return []
        finally:
            # On Windows, Defender/AV briefly locks a just-written file for
            # scanning, so unlink() can throw PermissionError right after a
            # perfectly good transcription. That used to propagate out of this
            # `finally` and kill the whole live-audio loop — one lock hiccup
            # silenced transcription for the rest of the meeting. Retry
            # briefly, then just leave the temp file for the OS to reap rather
            # than lose a working transcript over a cleanup failure.
            await _safe_unlink(path)

        self._language.observe(result.language, result.language_probability)
        if result.segments and result.language:
            self._last_language = result.language
        logger.info(
            "Meeting %d window: language=%s (%.2f) model=%s fast=%s lines=%d",
            self.meeting_id, result.language, result.language_probability,
            self._service._last_size_used, self._fast_mode, len(result.segments),
        )

        texts = [segment.text.strip() for segment in result.segments if segment.text.strip()]
        if not texts:
            return []

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
                    start_time=start_at + segment.start,
                    end_time=start_at + segment.end,
                    speaker_label=speaker,
                    source="live_bot",
                ))
            meeting.transcript = _append_transcript(meeting.transcript, speaker, texts)
            db.commit()

        # The single most useful line for diagnosing "the assistant never
        # replies in the meeting": without it there is no way to tell whether
        # Whisper ever actually heard the wake word, or the audio pipeline
        # never received speech at all.
        for text in texts:
            logger.info("Meeting %d transcript [%s]: %s", self.meeting_id, speaker, text)

        await self._broadcast(texts, speaker, result.language)
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
        """Flush audio, drain the transcription backlog, then write the notes.

        On a CPU where Whisper runs slower than real time the queue is still
        several utterances deep when the meeting ends. Those are the tail of
        the conversation — usually where the decisions and tasks are — so the
        backlog is drained before analysis rather than thrown away.
        """
        await self.flush()
        self._close_recording()
        await self._drain(timeout=FINALIZE_DRAIN_SECONDS)

        if self._worker and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        self._worker = None

        with SessionLocal() as db:
            meeting = db.scalar(select(Meeting).where(Meeting.id == self.meeting_id))
            transcript = meeting.transcript if meeting else None
            # The people on the call plus the registered team: what lets the
            # model (or the offline fallback) attribute each task to a real,
            # notifiable person even when Whisper spelled the name its own way.
            from app.services.meeting_analysis import build_roster

            participants = build_roster(self.meeting_id, db)

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


async def _safe_unlink(path: Path, attempts: int = 5, delay: float = 0.1) -> None:
    """Delete a temp file, tolerating Windows' transient AV-scan file lock.

    A brand-new file can be briefly held open by Defender's real-time scan;
    deleting it right away can raise `PermissionError` (WinError 32) even
    though nothing in this process still has it open. Retries a few times
    with a short backoff, and gives up quietly — a leftover few-KB temp WAV
    is a non-issue next to crashing the live transcription loop over it.
    """
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == attempts - 1:
                logger.debug("Could not delete temp file %s (still locked) — leaving it.", path)
                return
            await asyncio.sleep(delay)
        except OSError:
            return


def _normalize_level(pcm_data: bytes, target_rms: float = 2500.0, max_gain: float = 6.0) -> bytes:
    """Bring quiet speech up to a level Whisper handles well.

    Whisper's features are not level-invariant: a voice squashed by Zoom's
    codec, or a phone mic over Wi-Fi, can arrive so quiet that words are lost
    even though the VAD (which adapts to the room) correctly called it
    speech. Only ever amplifies — capped, and never into clipping — so loud
    audio is left exactly as captured. Falls back to the original bytes if
    numpy isn't there.
    """
    try:
        import numpy as np
    except ModuleNotFoundError:
        return pcm_data
    usable = len(pcm_data) - (len(pcm_data) % BYTES_PER_SAMPLE)
    if usable <= 0:
        return pcm_data
    samples = np.frombuffer(pcm_data[:usable], dtype="<i2").astype(np.float32)
    level = float(np.sqrt(np.mean(samples * samples)))
    peak = float(np.max(np.abs(samples)))
    if level <= 0 or peak <= 0:
        return pcm_data
    gain = min(target_rms / level, max_gain, 30000.0 / peak)
    if gain <= 1.15:
        return pcm_data
    return np.clip(samples * gain, -32768, 32767).astype("<i2").tobytes()


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
