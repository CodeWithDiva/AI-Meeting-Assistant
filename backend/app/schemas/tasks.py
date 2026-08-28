"""Schemas for action-item / task endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ActionItemCreate(BaseModel):
    """Manually create a task for a meeting."""

    assignee: str | None = None
    assigned_by: str | None = None
    task: str = Field(min_length=1)
    deadline: str | None = None


class ActionItemUpdate(BaseModel):
    """Update task status, assignee, or deadline."""

    assignee: str | None = None
    assigned_by: str | None = None
    task: str | None = None
    deadline: str | None = None
    status: Literal["pending", "in_progress", "done"] | None = None


class ActionItemResponse(BaseModel):
    id: int
    meeting_id: int
    assignee: str | None
    assigned_by: str | None
    task: str
    deadline: str | None
    status: str
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class DashboardStatsResponse(BaseModel):
    """Aggregate stats for the dashboard."""

    total_meetings: int = 0
    total_tasks: int = 0
    pending_tasks: int = 0
    done_tasks: int = 0
    recent_meetings: int = 0
