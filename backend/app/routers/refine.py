"""Kick off and check on a meeting's high-accuracy re-transcription.

See `app.services.refine` for what this actually does. Only the meeting's
owner can trigger it, and only when a recording (opt-in, see `recording.py`)
exists to refine.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, Recording, User
from app.services import refine as refine_service

router = APIRouter(prefix="/api/meetings/{meeting_id}/refine", tags=["refine"])


def _get_owned_meeting(meeting_id: int, user: User, db: Session) -> Meeting:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


@router.post("")
async def start_refine(
    meeting_id: int,
    regenerate_notes: bool = True,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_owned_meeting(meeting_id, user, db)
    rec = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
    if not rec or not rec.enabled or not rec.file_path:
        raise HTTPException(
            status_code=409,
            detail="No recording was saved for this meeting — turn on recording "
            "before the meeting to use this.",
        )
    job = refine_service.start_refine(meeting_id, regenerate_notes=regenerate_notes)
    return job.public()


@router.get("")
def get_refine_status(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_owned_meeting(meeting_id, user, db)
    job = refine_service.get_job(meeting_id)
    if not job:
        return {"meeting_id": meeting_id, "status": "idle", "progress": 0.0, "model": "", "message": "", "segments": 0}
    return job.public()
