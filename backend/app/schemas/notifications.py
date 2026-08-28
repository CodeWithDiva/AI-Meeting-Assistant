"""Schemas for notification endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: int
    meeting_id: int | None
    type: str
    title: str
    body: str | None
    read: bool
    created_at: datetime | None

    model_config = {"from_attributes": True}


class NotificationMarkRead(BaseModel):
    read: bool = True
