"""Schemas for action-item / task endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal["low", "medium", "high"]
Status = Literal["pending", "in_progress", "done"]


class ActionItemCreate(BaseModel):
    """Manually create a task for a meeting."""

    task: str = Field(min_length=1)
    # Either pick a registered team member, or type a name to match.
    assignee_user_id: int | None = None
    assignee: str | None = None
    assigned_by: str | None = None
    # Free text ("Friday 5 PM", "kal tak") and/or an exact moment from a date picker.
    deadline: str | None = None
    due_at: datetime | None = None
    priority: Priority = "medium"


class ActionItemUpdate(BaseModel):
    """Update a task. Assignees may change only `status`."""

    task: str | None = Field(default=None, min_length=1)
    assignee_user_id: int | None = None
    assignee: str | None = None
    assigned_by: str | None = None
    deadline: str | None = None
    due_at: datetime | None = None
    priority: Priority | None = None
    status: Status | None = None


class ActionItemResponse(BaseModel):
    id: int
    meeting_id: int
    meeting_title: str | None = None
    assignee: str | None
    assignee_user_id: int | None = None
    assignee_email: str | None = None
    assigned_by: str | None
    task: str
    deadline: str | None
    due_at: datetime | None = None
    priority: str = "medium"
    status: str
    is_overdue: bool = False
    completed_at: datetime | None = None
    created_at: datetime | None
    updated_at: datetime | None


class DashboardStatsResponse(BaseModel):
    """Aggregate stats for the dashboard."""

    total_meetings: int = 0
    total_tasks: int = 0
    pending_tasks: int = 0
    in_progress_tasks: int = 0
    done_tasks: int = 0
    recent_meetings: int = 0
    overdue_tasks: int = 0
    due_soon_tasks: int = 0
    my_open_tasks: int = 0
    completion_rate: float = 0.0
