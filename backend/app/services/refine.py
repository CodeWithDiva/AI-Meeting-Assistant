"""High-accuracy second pass over a meeting's opt-in recording.

The live transcript has to keep up with the meeting, and on a small CPU that
caps it at a modest Whisper model and a narrow beam. Once the meeting is over
there is no deadline, so this re-reads the saved audio with a bigger model and
a wider beam, then replaces the live transcript (the old one is backed up to a
text file first) and, optionally, regenerates the notes from the better text.

It only ever works from audio the owner explicitly chose to record — see
`Recording` — and never fetches or stores anything new.
"""

from __future__ import annotations

import asyncio
import logging
import os
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Meeting, Recording, TranscriptSegment
from app.transcription import base as whisper_base
from app.transcription.base import FasterWhisperService

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BLOCK_TARGET_S = 300.0  # ~5 minutes per decode block keeps memory flat
CUT_SEARCH_S = 20.0  # look this far either side of the target for a quiet spot
_FRAME_S = 0.1
BACKUP_DIR = Path(__file__).resolve().parents[2] / "transcript-backups"


@dataclass
class RefineJob:
    meeting_id: int
    status: str = "queued"  # queued | running | done | failed
    progress: float = 0.0
    model: str = ""
    message: str = ""
    segments: int = 0
    _task: asyncio.Task | None = field(default=None, repr=False)

    def public(self) -> dict:
        return {
            "meeting_id": self.meeting_id,
            "status": self.status,
            "progress": round(self.progress, 3),
            "model": self.model,
            "message": self.message,
            "segments": self.segments,
        }


_JOBS: dict[int, RefineJob] = {}


def get_job(meeting_id: int) -> RefineJob | None:
    return _JOBS.get(meeting_id)


def refine_model_name() -> str:
    # Measured on this 2-core machine (4 Urdu clips, clean + degraded audio):
    #   small          avgWER 0.29 / 0.36
    #   medium         avgWER 0.15 / 0.17   (14.5x realtime — very slow)
    #   large-v3-turbo avgWER 0.09 / 0.10   (2.5x realtime — turbo has fewer
    #                                        decoder layers than `large`, so
    #                                        it is both more accurate AND
    #                                        faster than `medium` here)
    # large-v3-turbo wins on both axes, so it's the default for this
    # no-live-deadline second pass. Override with WHISPER_MODEL_REFINE.
    return os.getenv("WHISPER_MODEL_REFINE", "large-v3-turbo").strip() or "large-v3-turbo"


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without a model)
# ---------------------------------------------------------------------------

def split_blocks(
    audio,  # noqa: ANN001 — 1-D float array at SAMPLE_RATE
    target_s: float = BLOCK_TARGET_S,
    search_s: float = CUT_SEARCH_S,
) -> list[tuple[int, int]]:
    """Cut a long recording into blocks, at the quietest point near each target.

    Cutting on silence instead of on a fixed second keeps a word from being
    sliced in half and decoded as two different words.
    """
    import numpy as np

    total = len(audio)
    target = int(target_s * SAMPLE_RATE)
    if total <= target + int(search_s * SAMPLE_RATE):
        return [(0, total)] if total else []

    frame = int(_FRAME_S * SAMPLE_RATE)
    blocks: list[tuple[int, int]] = []
    start = 0
    while total - start > target + int(search_s * SAMPLE_RATE):
        lo = start + target - int(search_s * SAMPLE_RATE)
        hi = start + target + int(search_s * SAMPLE_RATE)
        window = audio[lo:hi]
        usable = (len(window) // frame) * frame
        energy = np.sqrt((window[:usable].reshape(-1, frame) ** 2).mean(axis=1))
        cut = lo + int(np.argmin(energy)) * frame + frame // 2
        blocks.append((start, cut))
        start = cut
    blocks.append((start, total))
    return blocks


def assign_speakers(new_segments, old_segments) -> list[str | None]:  # noqa: ANN001
    """Give each refined segment the speaker who was talking at that time.

    Speaker names come from the live pass (the browser bot knows who the
    active speaker is; Whisper does not). Each new segment takes the label of
    the old segment it overlaps most; with no overlap, the nearest one.
    """
    labelled = [(s.start_time, s.end_time, s.speaker_label) for s in old_segments if s.speaker_label]
    result: list[str | None] = []
    for seg in new_segments:
        best_label, best_overlap = None, 0.0
        for start, end, label in labelled:
            overlap = min(seg.end, end) - max(seg.start, start)
            if overlap > best_overlap:
                best_overlap, best_label = overlap, label
        if best_label is None and labelled:
            mid = (seg.start + seg.end) / 2
            best_label = min(labelled, key=lambda item: abs((item[0] + item[1]) / 2 - mid))[2]
        result.append(best_label)
    return result


def build_transcript(segments, speakers: list[str | None]) -> str:  # noqa: ANN001
    """Flat "[Speaker]: text" transcript, merging consecutive same-speaker lines.

    The same shape the live pipeline writes — the notes model reads the
    bracketed name to know who is talking.
    """
    lines: list[tuple[str, list[str]]] = []
    for seg, speaker in zip(segments, speakers):
        name = speaker or "Speaker"
        if lines and lines[-1][0] == name:
            lines[-1][1].append(seg.text)
        else:
            lines.append((name, [seg.text]))
    return "\n".join(f"[{name}]: " + " ".join(texts) for name, texts in lines)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def _read_wav(path: Path):
    """The recording as 16 kHz mono float32, whatever rate it was saved at."""
    import numpy as np

    with wave.open(str(path), "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        raw = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError(f"Unsupported recording format ({width * 8}-bit).")
    samples = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        target_len = int(len(samples) * SAMPLE_RATE / rate)
        samples = np.interp(
            np.linspace(0, len(samples) - 1, target_len), np.arange(len(samples)), samples
        ).astype("float32")
    return samples


def _decode_blocks(audio, model_name: str, on_progress) -> tuple[list, str]:  # noqa: ANN001
    """Blocking: decode every block with `model_name`. Returns (segments, model used).

    Loads the model as a one-off (`load_transient_model`), never into the
    shared cache the live pipeline's `small`/`base` live in — a refinement
    is rare, and this machine cannot afford to permanently give up the 1.5+
    GB `large-v3-turbo` needs just because one meeting was once refined.
    """
    import gc

    service = FasterWhisperService(model_size=model_name)
    model, used = service.load_transient_model(model_name)
    if used != model_name:
        # The big model would not fit in RAM. A "refinement" with the quick
        # model would be a downgrade dressed up as an upgrade, so stop.
        del model
        gc.collect()
        raise RuntimeError(
            f"Not enough free memory to load Whisper {model_name!r} (got {used!r}). "
            "Close other programs and try again."
        )

    try:
        beam = int(os.getenv("WHISPER_REFINE_BEAM", "5"))
        blocks = split_blocks(audio)
        collected: list = []
        prefer: str | None = None
        for index, (lo, hi) in enumerate(blocks):
            block = audio[lo:hi]
            offset = lo / SAMPLE_RATE
            language, _ = service.choose_language_for_audio(block, prefer)
            prefer = language
            segments, _, _ = service._decode(model, block, language, beam_size=beam)
            for seg in segments:
                seg.start += offset
                seg.end += offset
            collected.extend(segments)
            on_progress((index + 1) / len(blocks))
            logger.info(
                "Refine block %d/%d: language=%s lines=%d", index + 1, len(blocks), language, len(segments)
            )
        return collected, used
    finally:
        # Give the RAM back to the OS immediately — the live pipeline's own
        # small/base models need it for the next meeting, and this one may
        # not be refined again for weeks.
        if used not in whisper_base._MODEL_CACHE:  # don't evict a model something else is sharing
            del model
            gc.collect()
            logger.info("Released Whisper %r after refinement — RAM freed for live transcription.", used)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

async def _broadcast(meeting_id: int, event: str, data: dict) -> None:
    try:
        from app.services.ws_manager import ws_manager

        await ws_manager.broadcast(meeting_id, event, data)
    except Exception:
        logger.debug("Refine broadcast failed", exc_info=True)


def start_refine(meeting_id: int, regenerate_notes: bool = True) -> RefineJob:
    """Begin a background refinement (or return the one already running)."""
    existing = _JOBS.get(meeting_id)
    if existing and existing.status in {"queued", "running"}:
        return existing
    job = RefineJob(meeting_id=meeting_id, model=refine_model_name())
    _JOBS[meeting_id] = job
    job._task = asyncio.get_running_loop().create_task(_run(job, regenerate_notes))
    return job


async def _run(job: RefineJob, regenerate_notes: bool) -> None:
    loop = asyncio.get_running_loop()
    meeting_id = job.meeting_id
    try:
        with SessionLocal() as db:
            recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
            path = Path(recording.file_path) if recording and recording.file_path else None
        if not path or not path.exists():
            raise FileNotFoundError("This meeting has no saved recording to improve.")

        job.status = "running"
        await _broadcast(meeting_id, "refine_progress", job.public())

        def on_progress(fraction: float) -> None:
            job.progress = fraction * 0.95  # the last 5% is saving + notes
            asyncio.run_coroutine_threadsafe(
                _broadcast(meeting_id, "refine_progress", job.public()), loop
            )

        def work():
            audio = _read_wav(path)
            return _decode_blocks(audio, job.model, on_progress)

        segments, used = await loop.run_in_executor(None, work)
        if not segments:
            raise RuntimeError("The recording contained no recognisable speech.")

        _replace_transcript(meeting_id, segments)
        job.segments = len(segments)

        if regenerate_notes:
            job.message = "Rewriting notes from the improved transcript…"
            await _broadcast(meeting_id, "refine_progress", job.public())
            from app.services.meeting_analysis import analyze_and_persist

            with SessionLocal() as db:
                await analyze_and_persist(meeting_id, db)

        job.status, job.progress, job.model = "done", 1.0, used
        job.message = "Transcript improved."
        logger.info("Refined meeting %d with %s: %d segments", meeting_id, used, len(segments))
    except Exception as error:
        logger.exception("Refinement of meeting %d failed", meeting_id)
        job.status = "failed"
        job.message = str(error) or error.__class__.__name__
    await _broadcast(meeting_id, "refine_done", job.public())


def _replace_transcript(meeting_id: int, segments) -> None:  # noqa: ANN001
    """Swap the live transcript for the refined one, keeping a backup file."""
    with SessionLocal() as db:
        meeting = db.get(Meeting, meeting_id)
        if not meeting:
            raise LookupError("Meeting not found.")
        old = list(
            db.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.meeting_id == meeting_id)
                .order_by(TranscriptSegment.start_time)
            )
        )
        speakers = assign_speakers(segments, old)

        if meeting.transcript:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            (BACKUP_DIR / f"meeting-{meeting_id}-live-{stamp}.txt").write_text(
                meeting.transcript, encoding="utf-8"
            )

        db.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id))
        for seg, speaker in zip(segments, speakers):
            db.add(TranscriptSegment(
                meeting_id=meeting_id,
                text=seg.text,
                start_time=seg.start,
                end_time=seg.end,
                speaker_label=speaker,
                source="refined",
            ))
        meeting.transcript = build_transcript(segments, speakers)
        db.commit()
