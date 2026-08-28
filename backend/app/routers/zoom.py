"""Router for managing Zoom Bot join/leave sessions."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.integrations.zoom.agent import ZoomBotAgent
from app.models import Meeting, User

router = APIRouter(prefix="/api/zoom", tags=["zoom"])

# In-memory active zoom bots keyed by meeting_id
_active_zoom_bots: dict[int, ZoomBotAgent] = {}


class ZoomJoinRequest(BaseModel):
    zoom_url_or_id: str


@router.post("/join/{meeting_id}")
async def join_zoom_meeting(
    meeting_id: int,
    request: ZoomJoinRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    bot = _active_zoom_bots.get(meeting_id)
    if not bot or bot.status in ("left", "idle"):
        bot = ZoomBotAgent(meeting_id=meeting_id, user_id=user.id)
        _active_zoom_bots[meeting_id] = bot

    result = await bot.join_meeting(request.zoom_url_or_id)
    return result


@router.post("/leave/{meeting_id}")
async def leave_zoom_meeting(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    bot = _active_zoom_bots.get(meeting_id)
    if not bot:
        return {"status": "left", "message": "No active Zoom bot found for this meeting."}

    result = await bot.leave_meeting()
    return result


@router.get("/status/{meeting_id}")
def get_zoom_bot_status(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    bot = _active_zoom_bots.get(meeting_id)
    if not bot:
        return {"meeting_id": meeting_id, "status": "idle", "is_connected": False}
    return bot.get_status()
