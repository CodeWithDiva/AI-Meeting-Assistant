"""Provider contract and faster-whisper implementation for transcription.

v4: bilingual (Urdu + English + Roman-Urdu code-switching).

Three things make or break Urdu accuracy here, and all three are handled below:

1. **Model size.** Whisper `base` is close to unusable for Urdu. `small` is the
   realistic CPU floor; `medium` is better if the machine can afford it. Set
   `WHISPER_MODEL` in `.env`.
2. **Language stickiness.** The live bot transcribes short windows, and letting
   Whisper re-detect the language on every window makes it flip between `ur`
   and `en` mid-sentence. Instead the first confident detection is remembered
   for the rest of the meeting (see `StickyLanguage`), which is what you want
   for a meeting that is mostly one language with English words mixed in.
3. **Hallucination filtering.** On silence or noise Whisper emits stock
   phrases ("Thank you.", "شکریہ", subtitle credits). In a live meeting there
   is a lot of silence, so unfiltered these flood the transcript.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "small"

# If the configured model can't be loaded (usually out of memory on a busy CPU
# box — `small` needs noticeably more RAM than `base`), fall back down this chain
# rather than failing the whole request.
_MODEL_FALLBACKS = {
    "large-v3": "medium",
    "large-v2": "medium",
    "large": "medium",
    "medium": "small",
    "small": "base",
    "base": "tiny",
}

# Whisper emits these on silence/noise rather than admitting it heard nothing.
# Matched against the whole normalized segment, so real sentences that merely
# contain "thank you" are unaffected.
_HALLUCINATIONS = {
    "thank you", "thank you.", "thanks for watching", "thanks for watching!",
    "you", "bye", "bye.", ".", "..", "...", "okay", "ok",
    "subtitles by the amara.org community", "amara.org",
    "please subscribe", "subscribe", "music", "applause",
    "شکریہ", "شکریہ۔", "بہت شکریہ", "آپ کا شکریہ",
    "الله", "اللہ", "سبسکرائب",
}
_PUNCT_ONLY = re.compile(r"^[\s\W_]+$", re.UNICODE)

# Nudges Whisper towards natural mixed Urdu/English business speech instead of
# forcing everything into one script. Whisper conditions on this as if it were
# the previous sentence, so it must read like real meeting speech.
_URDU_PRIMER = (
    "یہ ایک آفس میٹنگ ہے۔ ٹیم پروجیکٹ، ڈیڈلائن، ٹاسک اور رپورٹ پر بات کر رہی ہے۔ "
    "Ali, deadline Friday tak hai. Client ko update bhej dena."
)
_ENGLISH_PRIMER = (
    "This is a business meeting. The team is discussing the project, "
    "deadlines, action items and who owns each task."
)


@dataclass
class TranscriptSegment:
    """One piece of transcribed audio with timing info."""

    text: str
    start: float = 0.0
    end: float = 0.0
    speaker_label: str | None = None


@dataclass
class TranscriptResult:
    """Complete transcription output."""

    full_text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str | None = None
    language_probability: float = 0.0


class TranscriptionService(Protocol):
    async def transcribe(self, audio_path: Path) -> TranscriptResult:
        """Return a transcript for an audio file."""


class StickyLanguage:
    """Remembers the language of a live meeting after a confident detection.

    A meeting does not change language every four seconds, but Whisper's
    per-window detection does. Once a window comes back above
    ``confidence`` the language is locked for the rest of the session, so a
    quiet or English-loanword-heavy window can no longer flip an Urdu meeting
    into `en` (or vice versa).
    """

    def __init__(self, forced: str | None = None, confidence: float = 0.65) -> None:
        self.forced = forced
        self.confidence = confidence
        self.locked: str | None = forced

    def language_for_next_window(self) -> str | None:
        """The language to force on the next call, or None to auto-detect."""
        return self.locked

    def observe(self, detected: str | None, probability: float) -> None:
        if self.forced or self.locked or not detected:
            return
        if probability >= self.confidence:
            self.locked = detected
            logger.info(
                "Meeting language locked to %r (confidence %.2f)", detected, probability
            )


def is_hallucination(text: str) -> bool:
    """True when a segment is Whisper's silence filler rather than real speech."""
    stripped = text.strip()
    if not stripped or _PUNCT_ONLY.match(stripped):
        return True
    return stripped.casefold().strip(" .!?,۔") in _HALLUCINATIONS


class FasterWhisperService:
    """Run faster-whisper without loading its model until first use."""

    def __init__(
        self,
        model_size: str | None = None,
        language: str | None = None,
    ) -> None:
        self.model_size = model_size or os.getenv("WHISPER_MODEL", DEFAULT_MODEL)
        # WHISPER_LANGUAGE="" / "auto" means detect; "ur" or "en" forces it.
        forced = language or os.getenv("WHISPER_LANGUAGE", "").strip().lower()
        self.language = forced if forced and forced != "auto" else None
        self._model = None

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "faster-whisper is not installed. Install it with: "
                "python -m pip install faster-whisper"
            ) from error

        if self._model is not None:
            return self._model

        threads = int(os.getenv("WHISPER_CPU_THREADS", "4"))
        tried: list[str] = []
        size = self.model_size
        while size and size not in tried:
            tried.append(size)
            try:
                logger.info("Loading faster-whisper model %r on CPU...", size)
                self._model = WhisperModel(
                    size, device="cpu", compute_type="int8", cpu_threads=threads
                )
                if size != self.model_size:
                    logger.warning(
                        "Loaded Whisper %r instead of %r (the configured model would "
                        "not load — likely low memory). Transcription quality, "
                        "especially for Urdu, will be lower.",
                        size, self.model_size,
                    )
                self.model_size = size
                return self._model
            except (RuntimeError, MemoryError, OSError) as error:
                fallback = _MODEL_FALLBACKS.get(size)
                if not fallback:
                    raise RuntimeError(
                        f"Could not load any faster-whisper model (last tried {size!r}): "
                        f"{error}"
                    ) from error
                logger.warning(
                    "Whisper model %r failed to load (%s) — trying %r.",
                    size, error, fallback,
                )
                size = fallback
        raise RuntimeError("Could not load a faster-whisper model.")

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> TranscriptResult:
        """Transcribe a file, auto-detecting Urdu vs English unless told.

        Args:
            language: Force a language for this call (e.g. from
                :class:`StickyLanguage`). Falls back to the service-level
                setting, then to Whisper's own detection.
        """
        model = self._load_model()
        target = language or self.language
        raw_segments, info = model.transcribe(
            str(audio_path),
            language=target,
            task="transcribe",  # never translate — Urdu must stay Urdu
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            # Each live window is transcribed independently; carrying context
            # across them makes Whisper loop on its own previous output.
            condition_on_previous_text=False,
            initial_prompt=_URDU_PRIMER if target == "ur" else _ENGLISH_PRIMER,
        )

        segments: list[TranscriptSegment] = []
        texts: list[str] = []
        for seg in raw_segments:
            text = seg.text.strip()
            if not text or is_hallucination(text):
                continue
            segments.append(TranscriptSegment(text=text, start=seg.start, end=seg.end))
            texts.append(text)

        return TranscriptResult(
            full_text=" ".join(texts),
            segments=segments,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", 0.0) or 0.0,
        )
