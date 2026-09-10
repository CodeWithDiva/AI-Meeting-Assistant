"""Schemas for the meeting agent — the link-first join flow."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Lifecycle the frontend renders. SCHEDULED is reserved for a future
# join-at-start-time feature; the rest are emitted today.
AgentState = Literal[
    "idle",
    "SCHEDULED",
    "JOINING",
    "IN_MEETING",
    "PROCESSING",
    "COMPLETE",
    "FAILED_JOIN",
    "DISCONNECTED",
]


class AgentJoinRequest(BaseModel):
    """Everything needed to send the assistant into a meeting: a link."""

    link: str = Field(
        ...,
        min_length=4,
        description="Zoom or Google Meet link, or a bare Zoom ID / Meet code.",
    )
    title: str | None = Field(
        default=None,
        max_length=200,
        description="Meeting title. Derived from the link when omitted.",
    )
    record: bool = Field(
        default=False,
        description="Store the meeting audio to disk. Requires participant consent.",
    )


class AgentJoinResponse(BaseModel):
    """Returned immediately; the join itself continues in the background."""

    meeting_id: int
    platform: str
    state: AgentState
    title: str
    recording_enabled: bool
    message: str


class AgentStatusResponse(BaseModel):
    meeting_id: int | None = None
    state: AgentState
    platform: str | None = None
    is_connected: bool = False
    simulated: bool = False
    active_speaker: str | None = None
    participants: list[str] = Field(default_factory=list)
    error: str | None = None


class AgentLeaveResponse(BaseModel):
    meeting_id: int
    state: AgentState
    message: str
    notes: dict = Field(default_factory=dict)
