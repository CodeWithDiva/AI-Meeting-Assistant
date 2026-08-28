"""Meeting CRUD and AI analysis routes — v3."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import ActionItem, Decision, Meeting, Summary, User
from app.ai.service import analyze_meeting
from app.schemas.analysis import MeetingNotesResponse
from app.schemas.meeting import (
    MeetingCreate,
    MeetingDetailResponse,
    MeetingResponse,
    MeetingUpdate,
)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _owned(meeting_id: int, user: User, db: Session) -> Meeting:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
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
            .where(Meeting.owner_id == user.id)
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

    result = await analyze_meeting(meeting.transcript)
    notes = MeetingNotesResponse.model_validate(result)

    # ── Persist summary ──────────────────────────────────────────────
    existing_summary = db.scalar(
        select(Summary).where(Summary.meeting_id == meeting_id)
    )
    if existing_summary:
        existing_summary.text = notes.summary
        existing_summary.provider = "ollama"
    else:
        existing_summary = Summary(meeting_id=meeting_id, text=notes.summary, provider="ollama")
        db.add(existing_summary)
        meeting.summary = existing_summary

    # ── Persist decisions (replace) ──────────────────────────────────
    db.execute(
        Decision.__table__.delete().where(Decision.meeting_id == meeting_id)
    )
    for decision_text in notes.decisions:
        db.add(Decision(meeting_id=meeting_id, text=decision_text))

    # ── Persist action items (replace) ───────────────────────────────
    db.execute(
        ActionItem.__table__.delete().where(ActionItem.meeting_id == meeting_id)
    )
    for item in notes.action_items:
        db.add(
            ActionItem(
                meeting_id=meeting_id,
                assignee=item.assignee,
                assigned_by=item.assigned_by,
                task=item.task,
                deadline=item.deadline,
            )
        )

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
