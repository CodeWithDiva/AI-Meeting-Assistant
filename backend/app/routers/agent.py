"""Simulated meeting agent routes."""

from fastapi import APIRouter, HTTPException

from app.agents.simulated import SimulatedAgent
from app.schemas.agent import AgentStartRequest, AgentStatusResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])
_agent = SimulatedAgent()


def _status() -> AgentStatusResponse:
    state, meeting_id = _agent.status()
    return AgentStatusResponse(state=state, mode="simulated", meeting_id=meeting_id)


@router.get("/status", response_model=AgentStatusResponse)
async def agent_status() -> AgentStatusResponse:
    return _status()


@router.post("/start", response_model=AgentStatusResponse)
async def start_agent(request: AgentStartRequest) -> AgentStatusResponse:
    try:
        _agent.start(request.meeting_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _status()


@router.post("/stop", response_model=AgentStatusResponse)
async def stop_agent() -> AgentStatusResponse:
    _agent.stop()
    return _status()
