"""Meeting CRUD and AI analysis routes — v3."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, User
from app.services.meeting_analysis import analyze_and_persist
from app.schemas.analysis import MeetingNotesResponse
from app.schemas.meeting import (
    MeetingCreate,
    MeetingDetailResponse,
    MeetingResponse,
    MeetingUpdate,
)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _owned(meeting_id: int, user: User, db: Session) -> Meeting:
    query = select(Meeting).where(Meeting.id == meeting_id)
    if user.role != "admin":
        query = query.where(Meeting.owner_id == user.id)
    meeting = db.scalar(query)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


@router.get("", response_model=list[MeetingResponse])
def list_meetings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Meeting]:
    return list(
        db.scalars(
            select(Meeting)
            .where(Meeting.owner_id == user.id if user.role != "admin" else True)
            .order_by(Meeting.created_at.desc())
        )
    )


@router.post("", response_model=MeetingResponse, status_code=201)
def create_meeting(
    request: MeetingCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Meeting:
    meeting = Meeting(
        owner_id=user.id,
        title=request.title,
        platform=request.platform,
        scheduled_at=request.scheduled_at,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.get("/{meeting_id}/insights")
def get_meeting_insights(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return transparent talk-time and engagement metrics from transcript segments."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Insights are available to admins only.")
    meeting = _owned(meeting_id, user, db)
    totals: dict[str, float] = {}
    for segment in meeting.segments:
        speaker = segment.speaker_label or "Unknown speaker"
        totals[speaker] = totals.get(speaker, 0.0) + max(0.0, segment.end_time - segment.start_time)
    total_seconds = sum(totals.values())
    participants = []
    for speaker, seconds in sorted(totals.items(), key=lambda item: item[1], reverse=True):
        share = seconds / total_seconds if total_seconds else 0.0
        participants.append({
            "speaker": speaker,
            "talk_time_seconds": round(seconds, 2),
            "talk_time_percent": round(share * 100, 1),
            "engagement_score": round(min(100.0, share * 100 + min(30.0, len([s for s in meeting.segments if s.speaker_label == speaker]) * 2)), 1),
            "coaching_tip": "Invite more voices into the discussion." if share > 0.55 else "Good balance. Keep contributing concise, clear updates.",
        })
    return {"meeting_id": meeting.id, "participants": participants, "sentiment": None}


@router.get("/{meeting_id}", response_model=MeetingDetailResponse)
def get_meeting(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Meeting:
    """Return full meeting detail with nested summary, decisions, action items, segments."""
    meeting = db.scalar(
        select(Meeting)
        .options(
            joinedload(Meeting.summary),
            joinedload(Meeting.decisions),
            joinedload(Meeting.action_items),
            joinedload(Meeting.segments),
        )
        .where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


@router.patch("/{meeting_id}", response_model=MeetingResponse)
def update_meeting(
    meeting_id: int,
    request: MeetingUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Meeting:
    meeting = _owned(meeting_id, user, db)
    for key, value in request.model_dump(exclude_unset=True).items():
        setattr(meeting, key, value)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    meeting = _owned(meeting_id, user, db)
    db.delete(meeting)
    db.commit()


@router.post("/{meeting_id}/analyze", response_model=MeetingNotesResponse)
async def analyze_saved_meeting(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeetingNotesResponse:
    """Analyze transcript, then persist summary, decisions, and action items to DB."""
    meeting = _owned(meeting_id, user, db)
    if not meeting.transcript:
        raise HTTPException(status_code=400, detail="Meeting has no transcript to analyze.")

    result = await analyze_and_persist(meeting_id, db)
    notes = MeetingNotesResponse.model_validate(result)

    # ── Create in-app notification ──────────────────────────────────
    from app.models import Notification
    db.add(
        Notification(
            user_id=user.id,
            meeting_id=meeting_id,
            type="summary_ready",
            title=f"Summary Ready: {meeting.title}",
            body=f"Generated executive summary with {len(notes.decisions)} decisions and {len(notes.action_items)} action items.",
            read=False,
        )
    )

    db.commit()

    return notes
