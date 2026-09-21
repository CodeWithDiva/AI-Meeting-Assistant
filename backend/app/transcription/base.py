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

import asyncio
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "small"

# Loaded Whisper models, shared process-wide (see FasterWhisperService._load_model).
_MODEL_CACHE: dict[str, object] = {}
_MODEL_LOCK = threading.Lock()
# When a model last failed to load, and how long to wait before trying it again.
_MODEL_FAILED_AT: dict[str, float] = {}
_RETRY_FAILED_LOAD_AFTER_S = 180.0
# Silero VAD sensitivity. Lower keeps softer speech but lets more background
# noise through to Whisper, which then invents words for it.
try:
    _VAD_THRESHOLD = float(os.getenv("WHISPER_VAD_THRESHOLD", "0.35"))
except ValueError:
    _VAD_THRESHOLD = 0.35
# This many identical segments in a row is a hallucination loop, not speech.
_LOOP_RUN_LENGTH = 4

# Lower = faster, less accurate. 2 is a middle ground for live transcription on
# a modest CPU; raise it (env WHISPER_BEAM_SIZE) if the machine can keep up.
try:
    _BEAM_SIZE = max(1, int(os.getenv("WHISPER_BEAM_SIZE", "2")))
except ValueError:
    _BEAM_SIZE = 2

# Per-segment confidence floor. Whisper reports an average log-probability for
# each segment; real speech lands well above this, while words invented to fit
# noise score below it. Raise it (towards 0) to be stricter about inventions at
# the cost of dropping some genuine quiet speech.
try:
    _MIN_AVG_LOGPROB = float(os.getenv("WHISPER_MIN_LOGPROB", "-0.9"))
except ValueError:
    _MIN_AVG_LOGPROB = -0.9

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
#
# The "this is a business meeting" family is here for a specific reason: an
# earlier version passed a priming sentence as `initial_prompt` to steer
# Whisper towards meeting vocabulary, and on unclear audio Whisper simply
# echoed that prompt back as if it had been spoken. The prompt is gone now
# (see `_transcribe_blocking`), but these stay as a backstop.
_HALLUCINATIONS = {
    "thank you", "thank you.", "thanks for watching", "thanks for watching!",
    "you", "bye", "bye.", ".", "..", "...", "okay", "ok",
    "subtitles by the amara.org community", "amara.org",
    "please subscribe", "subscribe", "music", "applause",
    "this is a business meeting", "this is a business meeting.",
    "the team is discussing the project",
    "شکریہ", "شکریہ۔", "بہت شکریہ", "آپ کا شکریہ",
    "الله", "اللہ", "سبسکرائب",
    "یہ ایک آفس میٹنگ ہے", "یہ ایک آفس میٹنگ ہے۔",
}
_PUNCT_ONLY = re.compile(r"^[\s\W_]+$", re.UNICODE)


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

    # Whisper's language-ID routinely mistakes Urdu for Hindi — spoken
    # Hindustani sounds the same either way, and only the script differs.
    # This app never wants Hindi output, so a "hi" detection gets treated as
    # the Urdu it almost certainly is, before it can lock the rest of the
    # meeting into transcribing in Devanagari.
    _ALIASES = {"hi": "ur"}

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
        detected = self._ALIASES.get(detected, detected)
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


def _is_out_of_memory(error: BaseException) -> bool:
    """True for the various ways CTranslate2/MKL report running out of RAM."""
    if isinstance(error, MemoryError):
        return True
    text = str(error).lower()
    return "allocate memory" in text or "out of memory" in text or "bad_alloc" in text


def _normalized(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


def collapse_repetitions(segments: list["TranscriptSegment"]) -> list["TranscriptSegment"]:
    """Remove Whisper's repetition loops from one window's segments.

    On noise or unclear audio Whisper can get stuck emitting the same sentence
    over and over — seen live: "The globe is on the ground." twenty-one times
    in a row, each a one-second segment, none of it ever spoken. A speaker does
    not say the identical sentence five times running in separate breaths, so
    a run that long is a loop and is dropped entirely (its first copy is as
    invented as the rest); a shorter run of identical lines is collapsed to one.
    """
    result: list[TranscriptSegment] = []
    i = 0
    while i < len(segments):
        j = i
        key = _normalized(segments[i].text)
        while j + 1 < len(segments) and _normalized(segments[j + 1].text) == key:
            j += 1
        run = j - i + 1
        if run < _LOOP_RUN_LENGTH:
            result.append(segments[i])
        else:
            logger.info("Dropped a Whisper repetition loop (%d x %r).", run, segments[i].text[:60])
        i = j + 1
    return result


class FasterWhisperService:
    """Run faster-whisper without loading its model until first use."""

    def __init__(
        self,
        model_size: str | None = None,
        language: str | None = None,
    ) -> None:
        # The model used for Urdu (and anything that isn't English) — the one
        # where size really matters.
        self.model_size = model_size or os.getenv("WHISPER_MODEL", DEFAULT_MODEL)
        # English is transcribed near-perfectly by `base` (measured), and it
        # decodes ~3x faster than `small` — so a bigger Urdu model costs
        # English meetings nothing but speed. Override with WHISPER_MODEL_EN.
        self.english_model_size = os.getenv("WHISPER_MODEL_EN") or (
            "base" if self.model_size in {"small", "medium", "large", "large-v2", "large-v3"}
            else self.model_size
        )
        # WHISPER_LANGUAGE="" / "auto" means detect; "ur" or "en" forces it.
        forced = language or os.getenv("WHISPER_LANGUAGE", "").strip().lower()
        self.language = forced if forced and forced != "auto" else None
        self._last_size_used = self.model_size

    def _load_model(self, requested: str | None = None):
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "faster-whisper is not installed. Install it with: "
                "python -m pip install faster-whisper"
            ) from error

        requested = requested or self.model_size
        # Shared by every service instance and guarded by a lock: each meeting
        # builds its own service, and loading `small` from scratch cost 25-60s
        # (measured, on a RAM-starved machine) — on the first utterance of
        # every single meeting. Loaded once, kept, and warmable ahead of time.
        with _MODEL_LOCK:
            if requested in _MODEL_CACHE:
                return _MODEL_CACHE[requested]

            # Two threads, not four: measured on this 2-core/4-thread CPU, four
            # oversubscribes it (0.65x vs 0.55x real-time for the same audio) and
            # gets far worse the moment the bot's browser and the LLM are also
            # running, which they always are during a meeting.
            threads = int(os.getenv("WHISPER_CPU_THREADS", "2"))
            size = requested
            failed_at = _MODEL_FAILED_AT.get(requested)
            if failed_at is not None and time.monotonic() - failed_at < _RETRY_FAILED_LOAD_AFTER_S:
                # It failed to load moments ago (out of RAM); don't burn
                # another 30s failing again — go straight to the fallback.
                size = _MODEL_FALLBACKS.get(requested, requested)

            tried: list[str] = []
            while size and size not in tried:
                tried.append(size)
                if size != requested and size in _MODEL_CACHE:
                    return _MODEL_CACHE[size]
                try:
                    logger.info("Loading faster-whisper model %r on CPU...", size)
                    model = WhisperModel(
                        size, device="cpu", compute_type="int8", cpu_threads=threads
                    )
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
                    _MODEL_FAILED_AT[requested] = time.monotonic()
                    size = fallback
                    continue

                # Cache under the size that actually loaded. The fallback used
                # to be stored under the *requested* name, so one bad moment of
                # low RAM left the accurate model replaced by the quick one for
                # the life of the server. Now the requested model is retried
                # once the cooldown passes.
                _MODEL_CACHE[size] = model
                if size == requested:
                    _MODEL_FAILED_AT.pop(requested, None)
                else:
                    logger.warning(
                        "Using Whisper %r instead of %r for now (low memory) — "
                        "Urdu accuracy will be lower until %r can load.",
                        size, requested, requested,
                    )
                return model
            raise RuntimeError("Could not load a faster-whisper model.")

    def preload(self) -> None:
        """Load both models and run one throwaway pass, off the critical path.

        Blocking — call it from a worker thread. The bot calls this the moment
        it starts joining a meeting, so the 30-60s of model loading (plus the
        slow first inference) happens while it is still getting through the
        lobby, instead of delaying the transcript of everyone's first words.
        """
        import numpy as np

        started = time.monotonic()
        for size in dict.fromkeys((self.english_model_size, self.model_size)):
            try:
                model = self._load_model(size)
                # A second of faint noise: enough to make the first real call
                # skip the one-off initialisation cost. No VAD, or it would
                # drop the "audio" before the encoder ever ran.
                noise = (np.random.default_rng(0).standard_normal(16000) * 0.01).astype("float32")
                segments, _ = model.transcribe(noise, language="en", beam_size=1, vad_filter=False)
                list(segments)
            except Exception:
                logger.exception("Whisper preload of %r failed — it will load on first use.", size)
        logger.info("Whisper models warmed in %.1fs.", time.monotonic() - started)

    def _choose_language(self, audio_path: Path, prefer: str | None = None) -> tuple[str, float]:
        """Decide Urdu vs English for a window — never anything else.

        Whisper's own auto-detect picks from ~100 languages, and on Urdu
        speech it routinely answers Hindi (measured: 3 of 4 Urdu clips came
        back `hi` at 0.8-0.9 confidence). Hindi output is Devanagari gibberish
        for an Urdu meeting, and it also decodes 3-5x slower (measured 64s vs
        19s for the same 16s clip), which is what made the live transcript
        fall minutes behind. Spoken Hindi and Urdu are the same language, so
        every Urdu-script/Hindustani-family guess counts as Urdu.

        The two mistakes are not equally costly, so the call is biased. Forcing
        `en` onto Urdu speech makes Whisper invent fluent, meaningless English
        ("the globe is on the ground") — measured, and seen in a real meeting —
        whereas forcing `ur` onto English speech just transliterates it into
        Urdu script, which is still readable. So English has to be clearly
        English (`WHISPER_EN_THRESHOLD`, default 0.85) to win; a meeting that
        was English a moment ago keeps it on a lower bar (0.6) so a noisy
        window doesn't flip it.
        """
        from faster_whisper.audio import decode_audio

        detector = self._load_model(self.english_model_size)  # the cheap model
        audio = decode_audio(str(audio_path), sampling_rate=16000)
        _, _, probs = detector.detect_language(audio, language_detection_segments=1)
        p = dict(probs)
        p_en = p.get("en", 0.0)
        # Languages Whisper confuses with Urdu, plus Urdu itself.
        p_ur = sum(p.get(code, 0.0) for code in ("ur", "hi", "pa", "sd", "fa", "ar", "ps"))
        total = (p_en + p_ur) or 1.0
        p_en_norm = p_en / total
        try:
            strong = float(os.getenv("WHISPER_EN_THRESHOLD", "0.85"))
        except ValueError:
            strong = 0.85
        bar = min(strong, 0.6) if prefer == "en" else strong
        if p_en_norm >= bar:
            return "en", p_en_norm
        return "ur", 1.0 - p_en_norm

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        fast: bool = False,
        prefer: str | None = None,
    ) -> TranscriptResult:
        """Transcribe a file, auto-detecting Urdu vs English unless told.

        Args:
            language: Force a language for this call (e.g. from
                :class:`StickyLanguage`). Falls back to the service-level
                setting, then to Whisper's own detection.

        faster-whisper's `model.transcribe()` is a blocking, CPU-bound call —
        `raw_segments` is a lazy generator, so the real decoding work happens
        while iterating it. Doing that inline on the event loop stalls the
        *entire server* for however long Whisper takes (Urdu, with its longer
        initial prompt and RTL script, is exactly when this got bad enough to
        look like the live transcript — and every other request — had hung).
        So the call and the full iteration run together in a worker thread.
        """
        target = language or self.language
        loop = asyncio.get_event_loop()
        start = time.monotonic()
        # Model loading (several seconds, first use) happens inside the worker
        # thread too — done here on the event loop it froze the whole server.
        result = await loop.run_in_executor(None, self._transcribe_blocking, audio_path, target, fast, prefer)
        elapsed = time.monotonic() - start
        if elapsed > 3:
            logger.warning(
                "Whisper took %.1fs for a single window (model=%r, lang=%r) — "
                "live transcription will lag behind real time by roughly that much.",
                elapsed, self._last_size_used, result.language,
            )
        else:
            logger.debug("Whisper transcribed a window in %.2fs (lang=%r).", elapsed, result.language)
        return result

    def _decode(self, model, audio_path: Path, target: str):  # noqa: ANN001
        """Run one Whisper decode and filter the result. Returns (segments, texts, info)."""
        raw_segments, info = model.transcribe(
            str(audio_path),
            language=target,
            task="transcribe",  # never translate — Urdu must stay Urdu
            # Live transcription competes with real time, so beam width trades
            # accuracy for speed here. Override with WHISPER_BEAM_SIZE on a
            # bigger machine.
            beam_size=_BEAM_SIZE,
            vad_filter=True,
            # Keep quiet/soft speech: the VAD's job here is only to drop dead
            # air between utterances, not to gate on loudness. A low speech
            # threshold means a softly-spoken sentence still gets transcribed.
            vad_parameters={
                "min_silence_duration_ms": 400,
                "threshold": _VAD_THRESHOLD,
                "speech_pad_ms": 200,
            },
            # Each live window is transcribed independently; carrying context
            # across them makes Whisper loop on its own previous output.
            condition_on_previous_text=False,
            # NO initial_prompt. Priming Whisper with a "this is a business
            # meeting" sentence made it *echo that sentence back* as transcript
            # whenever the audio was unclear — invented text that looked real.
            # Language locking (StickyLanguage) steers it instead.
            initial_prompt=None,
            # Falls back through higher temperatures only when a decode looks
            # degenerate, which is what catches repeated/looping output.
            temperature=[0.0, 0.2, 0.4, 0.6],
            # A decode that compresses too well is repeating itself; one the
            # model has little confidence in is usually noise fitted to words.
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )

        segments: list[TranscriptSegment] = []
        texts: list[str] = []
        for seg in raw_segments:  # the generator is consumed — and decoded — here
            text = seg.text.strip()
            if not text or is_hallucination(text):
                continue
            # A segment that is itself highly repetitive ("no no no no no ...")
            # is the loop happening inside one segment.
            if getattr(seg, "compression_ratio", 0.0) > 2.4:
                logger.debug("Dropped a repetitive segment: %r", text[:60])
                continue
            # Whisper marks segments it believes are silence; on a live mic
            # those are room noise fitted to plausible words.
            if getattr(seg, "no_speech_prob", 0.0) > 0.75:
                logger.debug("Dropped a likely-silence segment: %r", text)
                continue
            # A confident transcription of real speech scores well above this.
            # Anything this uncertain is the model guessing at noise, and a
            # plausible invented sentence in the notes is worse than a gap.
            avg_logprob = getattr(seg, "avg_logprob", 0.0)
            if avg_logprob < _MIN_AVG_LOGPROB:
                logger.debug(
                    "Dropped a low-confidence segment (avg_logprob=%.2f): %r",
                    avg_logprob, text,
                )
                continue
            segments.append(TranscriptSegment(text=text, start=seg.start, end=seg.end))
        segments = collapse_repetitions(segments)
        texts = [segment.text for segment in segments]
        return segments, texts, info

    def _transcribe_blocking(
        self, audio_path: Path, target: str | None, fast: bool = False, prefer: str | None = None
    ) -> TranscriptResult:
        """The actual CPU-bound work — always call this off the event loop.

        `fast` uses the small/quick model even for Urdu. The live pipeline sets
        it while the transcript is running behind the meeting: on this CPU the
        accurate Urdu model runs at roughly real time at best, so a backlog
        never clears on its own — the quick model drains it ~3x faster, and
        the accurate one takes over again as soon as it has caught up.
        """
        detected_confidence: float | None = None
        if target is None:
            target, detected_confidence = self._choose_language(audio_path, prefer)
        size = self.english_model_size if (target == "en" or fast) else self.model_size
        model = self._load_model(size)
        self._last_size_used = size

        try:
            segments, texts, info = self._decode(model, audio_path, target)
        except (RuntimeError, MemoryError) as error:
            # This machine can be genuinely out of RAM mid-meeting (Ollama's
            # 7B model alone holds ~5 GB). Whisper then dies with
            # `mkl_malloc: failed to allocate memory` and, before this, that
            # utterance was simply lost. The quick model needs a fraction of
            # the memory, so answer with it instead of dropping the words.
            quick = self.english_model_size
            if not _is_out_of_memory(error) or size == quick:
                raise
            logger.warning(
                "Whisper %r ran out of memory on a window — retrying it with %r: %s",
                size, quick, error,
            )
            size = quick
            model = self._load_model(size)
            self._last_size_used = size
            segments, texts, info = self._decode(model, audio_path, target)

        # When we picked the language ourselves the decode was *told* it, so
        # Whisper's own confidence is a meaningless 1.0 — report how sure the
        # Urdu-vs-English decision actually was, so StickyLanguage only locks
        # the meeting on a genuinely confident window.
        return TranscriptResult(
            full_text=" ".join(texts),
            segments=segments,
            language=target,
            language_probability=(
                detected_confidence
                if detected_confidence is not None
                else (getattr(info, "language_probability", 0.0) or 0.0)
            ),
        )
