from datetime import datetime

from pydantic import BaseModel, Field


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    platform: str | None = None


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    platform: str | None = None
    transcript: str | None = None
    summary: str | None = None


class MeetingResponse(BaseModel):
    id: int
    title: str
    platform: str | None
    transcript: str | None
    summary: str | None
    created_at: datetime | None

    model_config = {"from_attributes": True}
