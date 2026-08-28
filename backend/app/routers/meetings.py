from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, User
from app.ai.service import analyze_meeting
from app.schemas.analysis import MeetingNotesResponse
from app.schemas.meeting import MeetingCreate, MeetingResponse, MeetingUpdate

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _owned(meeting_id: int, user: User, db: Session) -> Meeting:
    meeting = db.scalar(select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id))
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


@router.get("", response_model=list[MeetingResponse])
def list_meetings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Meeting]:
    return list(db.scalars(select(Meeting).where(Meeting.owner_id == user.id).order_by(Meeting.created_at.desc())))


@router.post("", response_model=MeetingResponse, status_code=201)
def create_meeting(request: MeetingCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Meeting:
    meeting = Meeting(owner_id=user.id, title=request.title, platform=request.platform)
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(meeting_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Meeting:
    return _owned(meeting_id, user, db)


@router.patch("/{meeting_id}", response_model=MeetingResponse)
def update_meeting(meeting_id: int, request: MeetingUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Meeting:
    meeting = _owned(meeting_id, user, db)
    for key, value in request.model_dump(exclude_unset=True).items():
        setattr(meeting, key, value)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    meeting = _owned(meeting_id, user, db)
    db.delete(meeting)
    db.commit()


@router.post("/{meeting_id}/analyze", response_model=MeetingNotesResponse)
async def analyze_saved_meeting(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeetingNotesResponse:
    """Analyze a meeting's saved transcript and persist its summary."""
    meeting = _owned(meeting_id, user, db)
    if not meeting.transcript:
        raise HTTPException(status_code=400, detail="Meeting has no transcript to analyze.")
    result = await analyze_meeting(meeting.transcript)
    notes = MeetingNotesResponse.model_validate(result)
    meeting.summary = notes.summary
    db.commit()
    return notes
