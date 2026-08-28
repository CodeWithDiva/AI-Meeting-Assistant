"""Schemas for meeting recording settings."""

from datetime import datetime

from pydantic import BaseModel


class RecordingToggleRequest(BaseModel):
    """Toggle recording on/off for a meeting."""

    enabled: bool


class RecordingConsentRequest(BaseModel):
    """Explicitly give consent to record (required when enabling)."""

    consent_given: bool = True


class RecordingResponse(BaseModel):
    id: int
    meeting_id: int
    enabled: bool
    consent_given_at: datetime | None
    file_path: str | None
    file_size_bytes: int | None
    created_at: datetime | None

    model_config = {"from_attributes": True}
