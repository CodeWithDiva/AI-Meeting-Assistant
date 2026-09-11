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
    """Send the assistant into a meeting.

    ``mode="agent"`` — the browser bot joins the meeting itself; needs `link`.
    ``mode="attach"`` — you join the meeting in your own client and the
    assistant only listens through the capture device; `link` is optional
    (used just for the title), so `title` is required when it is omitted.
    """

    mode: Literal["agent", "attach"] = "agent"
    link: str | None = Field(
        default=None,
        description="Zoom or Google Meet link, or a bare Zoom ID / Meet code. "
        "Required for mode='agent'.",
    )
    title: str | None = Field(
        default=None,
        max_length=200,
        description="Meeting title. Derived from the link when omitted; required "
        "for mode='attach' without a link.",
    )
    record: bool = Field(
        default=False,
        description="Store the meeting audio to disk. Requires participant consent.",
    )
    display_name: str | None = Field(
        default=None,
        max_length=100,
        description="mode='attach' only: your name, used to label your own voice "
        "in the transcript (the other participants can't be named — attach mode "
        "never reads the meeting UI). Defaults to your account name.",
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
    # Attach mode only: whether the user's own microphone is being captured
    # (loopback alone only carries the other participants). None outside
    # attach mode, where the field does not apply.
    mic_captured: bool | None = None


class AgentLeaveResponse(BaseModel):
    meeting_id: int
    state: AgentState
    message: str
    notes: dict = Field(default_factory=dict)
