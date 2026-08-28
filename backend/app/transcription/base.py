"""Provider contract for upload and live transcription sources."""

from pathlib import Path
import os
from typing import Protocol


class TranscriptionService(Protocol):
    async def transcribe(self, audio_path: Path) -> str:
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

    async def transcribe(self, audio_path: Path) -> str:
        model = self._load_model()
        segments, _ = model.transcribe(str(audio_path), vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()
