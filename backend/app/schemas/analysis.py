"""Schemas for meeting analysis."""

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    assignee: str = "Unassigned"
    task: str
    deadline: str | None = None


class MeetingNotesRequest(BaseModel):
    transcript: str = Field(min_length=1)


class MeetingNotesResponse(BaseModel):
    summary: str
    decisions: list[str]
    action_items: list[ActionItem]
