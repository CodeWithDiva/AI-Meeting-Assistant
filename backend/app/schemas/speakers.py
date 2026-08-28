"""Schemas for speaker identification endpoints."""

from pydantic import BaseModel, Field


class SpeakerMapRequest(BaseModel):
    """Assign a display name to a raw diarisation label."""

    display_name: str = Field(min_length=1, max_length=200)


class SpeakerResponse(BaseModel):
    id: int
    meeting_id: int
    speaker_label: str
    display_name: str | None

    model_config = {"from_attributes": True}
