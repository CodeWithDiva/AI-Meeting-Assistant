"""Speaker management and display name mapping routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, Speaker, TranscriptSegment, User
from app.schemas.speakers import SpeakerMapRequest, SpeakerResponse

router = APIRouter(prefix="/api/meetings/{meeting_id}/speakers", tags=["speakers"])


def _owned_meeting(meeting_id: int, user: User, db: Session) -> Meeting:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


@router.get("", response_model=list[SpeakerResponse])
def list_meeting_speakers(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Speaker]:
    _owned_meeting(meeting_id, user, db)
    speakers = list(
        db.scalars(
            select(Speaker)
            .where(Speaker.meeting_id == meeting_id)
            .order_by(Speaker.speaker_label)
        )
    )
    # If no speakers table rows exist yet, populate from transcript segments
    if not speakers:
        distinct_labels = db.scalars(
            select(TranscriptSegment.speaker_label)
            .where(
                TranscriptSegment.meeting_id == meeting_id,
                TranscriptSegment.speaker_label.isnot(None),
            )
            .distinct()
        ).all()

        for label in distinct_labels:
            if label:
                spk = Speaker(meeting_id=meeting_id, speaker_label=label, display_name=label)
                db.add(spk)
                speakers.append(spk)
        if speakers:
            db.commit()
            for s in speakers:
                db.refresh(s)

    return speakers


@router.patch("/{speaker_id}", response_model=SpeakerResponse)
def update_speaker_name(
    meeting_id: int,
    speaker_id: int,
    request: SpeakerMapRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Speaker:
    _owned_meeting(meeting_id, user, db)
    speaker = db.scalar(
        select(Speaker).where(
            Speaker.id == speaker_id, Speaker.meeting_id == meeting_id
        )
    )
    if not speaker:
        raise HTTPException(status_code=404, detail="Speaker not found.")

    speaker.display_name = request.display_name.strip()
    db.commit()
    db.refresh(speaker)
    return speaker
