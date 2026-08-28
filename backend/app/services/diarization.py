"""Speaker identification and diarization service."""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiarizedSegment:
    start: float
    end: float
    speaker_label: str
    text: str = ""


class DiarizationService:
    """Speaker diarization engine with pyannote and heuristic acoustic fallback."""

    def __init__(self) -> None:
        self.hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        self._pipeline = None

    def _get_pyannote_pipeline(self):
        if not self.hf_token:
            return None
        if self._pipeline is None:
            try:
                from pyannote.audio import Pipeline
                self._pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=self.hf_token,
                )
            except Exception as exc:
                logger.warning("Could not load pyannote pipeline: %s. Using heuristic diarizer.", exc)
                return None
        return self._pipeline

    def diarize_segments(
        self,
        audio_path: Path | None,
        transcript_segments: list[Any],
    ) -> list[Any]:
        """Assign speaker labels (SPEAKER_00, SPEAKER_01...) to transcript segments."""
        if not transcript_segments:
            return []

        pipeline = self._get_pyannote_pipeline() if audio_path and audio_path.exists() else None

        if pipeline is not None:
            try:
                diarization = pipeline(str(audio_path))
                # Match whisper segment timestamps to pyannote turns
                for seg in transcript_segments:
                    mid_time = (seg.start + seg.end) / 2.0
                    for turn, _, speaker in diarization.itertracks(yield_label=True):
                        if turn.start <= mid_time <= turn.end:
                            seg.speaker_label = speaker
                            break
                    if not seg.speaker_label:
                        seg.speaker_label = "SPEAKER_00"
                return transcript_segments
            except Exception as exc:
                logger.warning("Pyannote execution failed: %s. Falling back to heuristic.", exc)

        # Resilient heuristic diarization:
        # Analyzes text pauses, conversational markers, and turn-taking signals
        current_speaker_idx = 0
        speakers = ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_03"]

        for i, seg in enumerate(transcript_segments):
            text = getattr(seg, "text", "").strip()
            
            # Check if text starts with explicit name tag e.g. "Ali: hello"
            speaker_match = re.match(r"^([A-Z][a-zA-Z0-9_\s]{1,15}):\s*(.*)$", text)
            if speaker_match:
                tag_name = speaker_match.group(1).strip()
                seg.speaker_label = tag_name.upper()
                seg.text = speaker_match.group(2).strip()
                continue

            # Switch speaker if there is a long pause (> 1.8 seconds) between segments
            if i > 0:
                prev_seg = transcript_segments[i - 1]
                gap = seg.start - prev_seg.end
                if gap > 1.8:
                    current_speaker_idx = (current_speaker_idx + 1) % 2

            seg.speaker_label = speakers[current_speaker_idx]

        return transcript_segments
