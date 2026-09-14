"""Persist structured AI notes for a meeting."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.service import analyze_meeting
from app.models import Meeting, Participant, User
from app.services.action_items import persist_meeting_notes


async def analyze_and_persist(meeting_id: int, db: Session) -> dict:
    meeting = db.get(Meeting, meeting_id)
    if not meeting or not meeting.transcript:
        return {"summary": "", "decisions": [], "action_items": []}

    attendees = [
        p.name for p in db.scalars(
            select(Participant).where(
                Participant.meeting_id == meeting_id,
                Participant.role == "human",
            )
        )
    ]
    # Registered team members, even ones not on the call — someone often
    # hands work to a person who wasn't in the meeting ("send it to Bilal").
    # resolve_assignee() would still match the name afterwards either way,
    # but giving the model the real spelling up front means it extracts
    # "Bilal Khan", not a mis-heard "Bilaal" that then fails to match.
    team_names = [
        name for name in db.scalars(select(User.full_name).where(User.full_name.is_not(None)))
        if name
    ]
    roster = list(dict.fromkeys(attendees + team_names))  # de-duplicate, attendees first

    notes = await analyze_meeting(meeting.transcript, roster)
    persist_meeting_notes(meeting_id, notes, db)
    db.commit()
    return notes
