"""The meeting agent's public API — paste a link, the assistant shows up.

`POST /api/agent/join` is the whole product in one call: it creates the meeting
record, sets consent for recording, and dispatches the browser bot. It returns
as soon as the meeting exists rather than waiting out the join, because getting
admitted can take a minute (lobbies, host admission, web-client loading) and the
frontend needs a meeting page to show immediately. Progress arrives over the
meeting's WebSocket channel as `agent_state` events.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import bot_runtime
from app.agents.browser_bot import BrowserMeetingBot
from app.agents.meeting_link import UnsupportedMeetingLinkError, parse_meeting_link
from app.auth import get_current_user
from app.database import SessionLocal, get_db
from app.models import Meeting, Recording, User
from app.schemas.agent import (
    AgentJoinRequest,
    AgentJoinResponse,
    AgentLeaveResponse,
    AgentStatusResponse,
)
from app.services.ws_manager import ws_manager

router = APIRouter(prefix="/api/agent", tags=["agent"])
logger = logging.getLogger(__name__)

# Live bots keyed by meeting_id. In-memory on purpose: a bot owns a browser
# process belonging to this worker, so it cannot outlive it or be shared.
_active_bots: dict[int, BrowserMeetingBot] = {}
# Join failures, kept so /status can explain a bot that never appeared.
_join_errors: dict[int, str] = {}


def _owned_meeting(meeting_id: int, user: User, db: Session) -> Meeting:
    query = select(Meeting).where(Meeting.id == meeting_id)
    if user.role != "admin":
        query = query.where(Meeting.owner_id == user.id)
    meeting = db.scalar(query)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


async def _broadcast(meeting_id: int, state: str, extra: dict | None = None) -> None:
    payload = {"state": state}
    if extra:
        payload.update(extra)
    try:
        await ws_manager.broadcast(meeting_id, "agent_state", payload)
    except Exception as exc:
        logger.warning("WS broadcast failed for meeting %d: %s", meeting_id, exc)


@router.post("/join", response_model=AgentJoinResponse, status_code=202)
async def join_meeting(
    request: AgentJoinRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentJoinResponse:
    """Create a meeting from a pasted link and send the assistant into it."""
    try:
        link = parse_meeting_link(request.link)
    except UnsupportedMeetingLinkError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    title = (request.title or "").strip() or link.display_title
    meeting = Meeting(
        owner_id=user.id,
        title=title,
        platform=link.platform,
        scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(meeting)
    db.flush()  # assign meeting.id before the Recording row references it

    # Recording is opt-in and consent is stamped at the moment it is turned on.
    db.add(Recording(
        meeting_id=meeting.id,
        enabled=request.record,
        consent_given_at=(
            datetime.now(timezone.utc).replace(tzinfo=None) if request.record else None
        ),
    ))
    db.commit()
    db.refresh(meeting)

    _join_errors.pop(meeting.id, None)
    bot = BrowserMeetingBot(meeting_id=meeting.id, user_id=user.id)
    _active_bots[meeting.id] = bot
    asyncio.create_task(_join_in_background(bot, link.join_url))

    return AgentJoinResponse(
        meeting_id=meeting.id,
        platform=link.platform,
        state="JOINING",
        title=title,
        recording_enabled=request.record,
        message=f"Assistant is joining the {link.platform.replace('_', ' ')} meeting.",
    )


@router.post("/join/{meeting_id}", response_model=AgentJoinResponse, status_code=202)
async def join_existing_meeting(
    meeting_id: int,
    request: AgentJoinRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentJoinResponse:
    """Send the assistant into a meeting that already exists in the app.

    Same behaviour as :func:`join_meeting`, but it attaches to a meeting the
    user created earlier instead of making a new one — so its transcript,
    tasks and history stay in one place.
    """
    meeting = _owned_meeting(meeting_id, user, db)

    try:
        link = parse_meeting_link(request.link)
    except UnsupportedMeetingLinkError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    existing = _active_bots.get(meeting_id)
    if existing and existing.status in {"joining", "listening"}:
        raise HTTPException(
            status_code=409,
            detail="The assistant is already in this meeting.",
        )

    meeting.platform = link.platform
    recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
    if request.record:
        stamp = datetime.now(timezone.utc).replace(tzinfo=None)
        if recording:
            recording.enabled = True
            recording.consent_given_at = recording.consent_given_at or stamp
        else:
            db.add(Recording(meeting_id=meeting_id, enabled=True, consent_given_at=stamp))
    db.commit()

    _join_errors.pop(meeting_id, None)
    bot = BrowserMeetingBot(meeting_id=meeting_id, user_id=user.id)
    _active_bots[meeting_id] = bot
    asyncio.create_task(_join_in_background(bot, link.join_url))

    return AgentJoinResponse(
        meeting_id=meeting_id,
        platform=link.platform,
        state="JOINING",
        title=meeting.title,
        recording_enabled=bool(request.record or (recording and recording.enabled)),
        message=f"Assistant is joining the {link.platform.replace('_', ' ')} meeting.",
    )


async def _join_in_background(bot: BrowserMeetingBot, join_url: str) -> None:
    """Run the slow join and report the outcome over the meeting's WS channel."""
    meeting_id = bot.meeting_id
    await _broadcast(meeting_id, "JOINING")
    try:
        # The bot drives Chromium via subprocess, which on Windows needs a
        # Proactor loop that uvicorn's --reload mode does not provide — so it
        # runs on its own loop thread.
        result = await bot_runtime.run(bot.join_meeting(join_url))
        await _broadcast(meeting_id, "IN_MEETING", {"simulated": result.get("simulated", False)})
        logger.info("Assistant is in meeting %d (%s).", meeting_id, result.get("platform"))
    except Exception as exc:
        message = str(exc)
        _join_errors[meeting_id] = message
        logger.error("Assistant failed to join meeting %d: %s", meeting_id, message)
        await _broadcast(meeting_id, "FAILED_JOIN", {"error": message})


@router.post("/leave/{meeting_id}", response_model=AgentLeaveResponse)
async def leave_meeting(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentLeaveResponse:
    """Leave the meeting and generate its notes, decisions and assigned tasks."""
    _owned_meeting(meeting_id, user, db)

    bot = _active_bots.pop(meeting_id, None)
    if not bot:
        return AgentLeaveResponse(
            meeting_id=meeting_id,
            state="DISCONNECTED",
            message="No assistant is currently in this meeting.",
        )

    await _broadcast(meeting_id, "PROCESSING")
    result = await bot_runtime.run(bot.leave_meeting())
    await _broadcast(meeting_id, "COMPLETE", result.get("notes") or {})
    return AgentLeaveResponse(
        meeting_id=meeting_id,
        state="COMPLETE",
        message=result.get("message", "Assistant left the meeting."),
        notes=result.get("notes") or {},
    )


@router.get("/status/{meeting_id}", response_model=AgentStatusResponse)
def agent_status(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentStatusResponse:
    """Report where the assistant is in the join → listen → notes lifecycle."""
    meeting = _owned_meeting(meeting_id, user, db)

    bot = _active_bots.get(meeting_id)
    if not bot:
        error = _join_errors.get(meeting_id)
        return AgentStatusResponse(
            meeting_id=meeting_id,
            state="FAILED_JOIN" if error else ("COMPLETE" if meeting.ended_at else "idle"),
            platform=meeting.platform,
            error=error,
        )

    status = bot.get_status()
    return AgentStatusResponse(
        meeting_id=meeting_id,
        state=_BOT_STATE_TO_API.get(status["status"], "idle"),
        platform=status.get("platform") or meeting.platform,
        is_connected=status["is_connected"],
        simulated=status.get("simulated", False),
        active_speaker=status.get("active_speaker"),
        participants=status.get("participants") or [],
        error=_join_errors.get(meeting_id),
    )


# The bot tracks its own lifecycle in lowercase; the API exposes the states the
# frontend renders.
_BOT_STATE_TO_API = {
    "idle": "idle",
    "joining": "JOINING",
    "listening": "IN_MEETING",
    "leaving": "PROCESSING",
    "left": "COMPLETE",
    "FAILED_JOIN": "FAILED_JOIN",
}


@router.get("/sessions", response_model=list[AgentStatusResponse])
def active_sessions(user: User = Depends(get_current_user)) -> list[AgentStatusResponse]:
    """Every meeting this assistant instance is currently sitting in."""
    sessions = []
    with SessionLocal() as db:
        for meeting_id, bot in _active_bots.items():
            meeting = db.get(Meeting, meeting_id)
            if not meeting or (user.role != "admin" and meeting.owner_id != user.id):
                continue
            status = bot.get_status()
            sessions.append(AgentStatusResponse(
                meeting_id=meeting_id,
                state=_BOT_STATE_TO_API.get(status["status"], "idle"),
                platform=status.get("platform"),
                is_connected=status["is_connected"],
                simulated=status.get("simulated", False),
                active_speaker=status.get("active_speaker"),
                participants=status.get("participants") or [],
            ))
    return sessions
