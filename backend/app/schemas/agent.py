"""Schemas for the simulated meeting agent."""

from typing import Literal

from pydantic import BaseModel

AgentState = Literal["idle", "joining", "listening", "processing", "leaving", "stopped"]


class AgentStatusResponse(BaseModel):
    state: AgentState
    mode: Literal["simulated"]
    meeting_id: int | None = None


class AgentStartRequest(BaseModel):
    meeting_id: int | None = None
