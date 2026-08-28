"""Transcript segment retrieval routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, TranscriptSegment, User
from app.schemas.transcription import SegmentResponse, TranscriptDetailResponse

router = APIRouter(prefix="/api/transcript", tags=["transcript"])


@router.get("/{meeting_id}", response_model=TranscriptDetailResponse)
def get_transcript(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranscriptDetailResponse:
    """Return all transcript segments for a meeting, ordered by time."""
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    segments = list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_time)
        )
    )
    return TranscriptDetailResponse(
        meeting_id=meeting_id,
        total_segments=len(segments),
        segments=[SegmentResponse.model_validate(s, from_attributes=True) for s in segments],
    )
