"""Router for managing our own browser-based Zoom bot join/leave sessions,
with real-time agent state broadcasting. Uses BrowserMeetingBot (Playwright +
virtual audio cable) instead of Zoom RTMS — no Zoom Marketplace app needed."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.browser_bot import BrowserMeetingBot
from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, User
from app.services.ws_manager import ws_manager

router = APIRouter(prefix="/api/zoom", tags=["zoom"])
logger = logging.getLogger(__name__)

# In-memory active meeting bots keyed by meeting_id.
# BrowserMeetingBot joins the Zoom Web Client directly (no Zoom Marketplace
# app, no RTMS) — see app/agents/browser_bot.py.
_active_zoom_bots: dict[int, BrowserMeetingBot] = {}

# Valid agent states (ordered lifecycle)
AGENT_STATES = (
    "idle",
    "SCHEDULED",
    "JOINING",
    "IN_MEETING",
    "PROCESSING",
    "COMPLETE",
    "FAILED_JOIN",
    "DISCONNECTED",
)


class ZoomJoinRequest(BaseModel):
    zoom_url_or_id: str


async def _broadcast_state(meeting_id: int, state: str, extra: dict | None = None) -> None:
    """Helper: broadcast agent state change to all WS clients for a meeting."""
    data: dict[str, Any] = {"state": state}
    if extra:
        data.update(extra)
    try:
        await ws_manager.broadcast(meeting_id, "agent_state", data)
    except Exception as exc:
        logger.warning("WS broadcast failed for meeting %d: %s", meeting_id, exc)


@router.post("/join/{meeting_id}")
async def join_zoom_meeting(
    meeting_id: int,
    request: ZoomJoinRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role == "admin":
        meeting = db.scalar(select(Meeting).where(Meeting.id == meeting_id))
    else:
        meeting = db.scalar(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
        )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    bot = _active_zoom_bots.get(meeting_id)
    if not bot or bot.status in ("left", "idle", "DISCONNECTED", "COMPLETE", "FAILED_JOIN"):
        bot = BrowserMeetingBot(meeting_id=meeting_id, user_id=user.id)
        _active_zoom_bots[meeting_id] = bot

    # Announce JOINING state immediately
    await _broadcast_state(meeting_id, "JOINING")

    try:
        result = await bot.join_meeting(request.zoom_url_or_id)
        await _broadcast_state(meeting_id, "IN_MEETING")
        return result
    except Exception as exc:
        logger.error("Zoom join failed for meeting %d: %s", meeting_id, exc)
        await _broadcast_state(meeting_id, "FAILED_JOIN", {"error": str(exc)})
        raise HTTPException(status_code=502, detail=f"Zoom join failed: {exc}") from exc


@router.post("/leave/{meeting_id}")
async def leave_zoom_meeting(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role == "admin":
        meeting = db.scalar(select(Meeting).where(Meeting.id == meeting_id))
    else:
        meeting = db.scalar(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
        )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    bot = _active_zoom_bots.get(meeting_id)
    if not bot:
        return {"status": "DISCONNECTED", "message": "No active Zoom bot found for this meeting."}

    await _broadcast_state(meeting_id, "PROCESSING")
    result = await bot.leave_meeting()
    await _broadcast_state(meeting_id, "COMPLETE")
    return result


@router.get("/status/{meeting_id}")
def get_zoom_bot_status(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role == "admin":
        meeting = db.scalar(select(Meeting).where(Meeting.id == meeting_id))
    else:
        meeting = db.scalar(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
        )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    bot = _active_zoom_bots.get(meeting_id)
    if not bot:
        return {"meeting_id": meeting_id, "status": "idle", "is_connected": False}
    return bot.get_status()
