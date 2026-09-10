"""Persist structured AI notes for a meeting."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.service import analyze_meeting
from app.models import Meeting, Participant
from app.services.action_items import persist_meeting_notes


async def analyze_and_persist(meeting_id: int, db: Session) -> dict:
    meeting = db.get(Meeting, meeting_id)
    if not meeting or not meeting.transcript:
        return {"summary": "", "decisions": [], "action_items": []}

    participants = [
        p.name for p in db.scalars(
            select(Participant).where(
                Participant.meeting_id == meeting_id,
                Participant.role == "human",
            )
        )
    ]
    notes = await analyze_meeting(meeting.transcript, participants)
    persist_meeting_notes(meeting_id, notes, db)
    db.commit()
    return notes
