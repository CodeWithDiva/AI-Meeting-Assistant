"""
Voice Reply Router
===================
Provides two things:

1. WebSocket endpoint  GET /api/meetings/{meeting_id}/ws
   - Frontend yahan connect karta hai aur real-time events receive karta hai:
     - ava_reply       → Ava ka voice answer (text + audio/wav base64)
     - agent_state     → bot ka current state (JOINING, IN_MEETING, etc.)
     - transcript_live → live Whisper segments as they come in
     - ping            → keepalive every 30s

2. REST endpoint       GET /api/meetings/{meeting_id}/voice-reply/latest
   - Last Ava reply fetch karo (polling fallback if WebSocket not available)

3. REST endpoint       POST /api/meetings/{meeting_id}/voice-reply/test
   - Manually test karo Ava pipeline bina Zoom ke (dev/debug)
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, User
from app.services.voice_assistant import AvaVoiceAssistant
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])

# In-memory last-reply cache keyed by meeting_id
_last_replies: dict[int, dict] = {}


# ---------------------------------------------------------------------------
# 1. WebSocket endpoint — real-time events
# ---------------------------------------------------------------------------

@router.websocket("/api/meetings/{meeting_id}/ws")
async def meeting_websocket(meeting_id: int, websocket: WebSocket):
    """
    Real-time WebSocket channel for a meeting.
    Connects the frontend to all backend events without polling.
    """
    await ws_manager.connect(meeting_id, websocket)
    logger.info("Frontend connected to meeting %d WS channel", meeting_id)

    try:
        # Keepalive loop — also handle any client messages (e.g. ping)
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text('{"event":"pong","data":{}}')
            except asyncio.TimeoutError:
                # Send a server-side ping to keep connection alive
                await websocket.send_text('{"event":"ping","data":{}}')
    except WebSocketDisconnect:
        logger.info("Frontend disconnected from meeting %d WS channel", meeting_id)
    finally:
        await ws_manager.disconnect(meeting_id, websocket)


# ---------------------------------------------------------------------------
# 2. REST — get latest Ava reply (polling fallback)
# ---------------------------------------------------------------------------

@router.get("/api/meetings/{meeting_id}/voice-reply/latest")
async def get_latest_voice_reply(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the most recent Ava voice reply for a meeting."""
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    reply = _last_replies.get(meeting_id)
    if not reply:
        return {"meeting_id": meeting_id, "reply": None}

    # Strip audio bytes from REST response (too large — use WS for audio)
    safe_reply = {k: v for k, v in reply.items() if k != "audio_base64"}
    safe_reply["has_audio"] = "audio_base64" in reply
    return {"meeting_id": meeting_id, "reply": safe_reply}


# ---------------------------------------------------------------------------
# 3. REST — manual test endpoint (dev/debug)
# ---------------------------------------------------------------------------

class VoiceTestRequest(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=1000,
        description="Simulate a spoken sentence e.g. 'Ava, deployment kab hai?'"
    )


@router.post("/api/meetings/{meeting_id}/voice-reply/test")
async def test_voice_reply(
    meeting_id: int,
    request: VoiceTestRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Manually trigger the full Ava voice pipeline for testing.
    Simulates a spoken utterance — useful before Zoom RTMS is wired.
    """
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    assistant = AvaVoiceAssistant(meeting_id=meeting_id)
    reply = await assistant.handle_transcript(request.text)

    if not reply:
        return {
            "triggered": False,
            "message": "Wake-word 'Ava' not detected in the provided text.",
            "tip": "Include 'Ava' in your text, e.g. 'Ava, what was decided?'",
        }

    # Cache for polling endpoint
    _last_replies[meeting_id] = {
        "question": reply.question,
        "answer": reply.answer,
        "audio_base64": reply.audio_base64,
        "content_type": "audio/wav",
        "timestamp": reply.timestamp,
    }

    return {
        "triggered": True,
        "question": reply.question,
        "answer": reply.answer,
        "audio_base64": reply.audio_base64,
        "content_type": "audio/wav",
        "timestamp": reply.timestamp,
        "ws_clients_notified": ws_manager.connection_count(meeting_id),
    }
