"""Schemas for meeting endpoints — v3 expanded."""

from datetime import datetime

from pydantic import BaseModel, Field


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    platform: str | None = None
    scheduled_at: datetime | None = None


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    platform: str | None = None
    transcript: str | None = None
    scheduled_at: datetime | None = None


# ── Nested response helpers ─────────────────────────────────────────────

class SegmentBrief(BaseModel):
    id: int
    speaker_label: str | None
    text: str
    start_time: float
    end_time: float

    model_config = {"from_attributes": True}


class DecisionBrief(BaseModel):
    id: int
    text: str

    model_config = {"from_attributes": True}


class ActionItemBrief(BaseModel):
    id: int
    meeting_id: int
    assignee: str | None
    assignee_user_id: int | None = None
    assigned_by: str | None
    task: str
    deadline: str | None
    due_at: datetime | None = None
    priority: str | None = "medium"
    status: str

    model_config = {"from_attributes": True}


class SummaryBrief(BaseModel):
    id: int
    text: str
    provider: str
    generated_at: datetime | None

    model_config = {"from_attributes": True}


# ── Main response ───────────────────────────────────────────────────────

class MeetingResponse(BaseModel):
    id: int
    title: str
    platform: str | None
    transcript: str | None
    scheduled_at: datetime | None
    ended_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class MeetingDetailResponse(MeetingResponse):
    """Extended response with nested analysis data for the detail view."""

    summary: SummaryBrief | None = None
    decisions: list[DecisionBrief] = []
    action_items: list[ActionItemBrief] = []
    segments: list[SegmentBrief] = []

    model_config = {"from_attributes": True}
