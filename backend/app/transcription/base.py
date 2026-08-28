"""Provider contract and faster-whisper implementation for transcription.

v3: Returns individual segments with timestamps instead of just flat text.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


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


class TranscriptionService(Protocol):
    async def transcribe(self, audio_path: Path) -> TranscriptResult:
        """Return a transcript for an audio file."""


class FasterWhisperService:
    """Run faster-whisper without loading its model until first use."""

    def __init__(self, model_size: str | None = None) -> None:
        self.model_size = model_size or os.getenv("WHISPER_MODEL", "base")
        self._model = None

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "faster-whisper is not installed. Install it with: "
                "python -m pip install faster-whisper"
            ) from error

        if self._model is None:
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=int(os.getenv("WHISPER_CPU_THREADS", "4")),
            )
        return self._model

    async def transcribe(self, audio_path: Path) -> TranscriptResult:
        model = self._load_model()
        raw_segments, _ = model.transcribe(str(audio_path), vad_filter=True)

        segments: list[TranscriptSegment] = []
        texts: list[str] = []
        for seg in raw_segments:
            text = seg.text.strip()
            if text:
                segments.append(
                    TranscriptSegment(text=text, start=seg.start, end=seg.end)
                )
                texts.append(text)

        return TranscriptResult(
            full_text=" ".join(texts),
            segments=segments,
        )
