"""Meeting recording management router."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, Recording, User
from app.schemas.recording import RecordingResponse, RecordingToggleRequest

router = APIRouter(prefix="/api/meetings/{meeting_id}/recording", tags=["recording"])


def _get_owned_meeting(meeting_id: int, user: User, db: Session) -> Meeting:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


@router.get("", response_model=RecordingResponse)
def get_recording_settings(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Recording:
    _get_owned_meeting(meeting_id, user, db)
    rec = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
    if not rec:
        rec = Recording(meeting_id=meeting_id, enabled=False)
        db.add(rec)
        db.commit()
        db.refresh(rec)
    return rec


@router.patch("", response_model=RecordingResponse)
def toggle_recording(
    meeting_id: int,
    request: RecordingToggleRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Recording:
    _get_owned_meeting(meeting_id, user, db)
    rec = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
    if not rec:
        rec = Recording(
            meeting_id=meeting_id,
            enabled=request.enabled,
            consent_given_at=datetime.now(timezone.utc) if request.enabled else None,
        )
        db.add(rec)
    else:
        rec.enabled = request.enabled
        if request.enabled and not rec.consent_given_at:
            rec.consent_given_at = datetime.now(timezone.utc)
        elif not request.enabled:
            rec.consent_given_at = None
    db.commit()
    db.refresh(rec)
    return rec
