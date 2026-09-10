"""Schemas for meeting analysis."""

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    # Null when the transcript assigned a task without naming an owner. The
    # analyzer deliberately reports that rather than guessing a person.
    assignee: str | None = None
    assigned_by: str | None = None
    task: str
    deadline: str | None = None


class MeetingNotesRequest(BaseModel):
    transcript: str = Field(min_length=1)


class MeetingNotesResponse(BaseModel):
    summary: str
    decisions: list[str]
    action_items: list[ActionItem]
