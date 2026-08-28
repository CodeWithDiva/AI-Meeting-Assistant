"""Schemas for transcription endpoints — v3 with segments."""

from datetime import datetime

from pydantic import BaseModel


class SegmentResponse(BaseModel):
    """One timed piece of transcript text."""

    id: int | None = None
    speaker_label: str | None = None
    text: str
    start_time: float = 0.0
    end_time: float = 0.0
    source: str = "upload"
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TranscriptResponse(BaseModel):
    """Single-string & segment count response for audio upload."""

    filename: str
    status: str
    transcript: str
    segment_count: int | None = None


class TranscriptDetailResponse(BaseModel):
    """Full segmented transcript for a meeting."""

    meeting_id: int
    total_segments: int
    segments: list[SegmentResponse]
