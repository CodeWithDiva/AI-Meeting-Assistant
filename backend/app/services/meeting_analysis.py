"""Persist structured AI notes for a meeting."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.service import analyze_meeting
from app.models import Meeting, Participant, User
from app.services.action_items import persist_meeting_notes


def build_roster(meeting_id: int, db: Session) -> list[str]:
    """Names the analysis should resolve spoken names against.

    The people the bot saw on the call, then every registered team member —
    someone often hands work to a person who wasn't in the meeting ("send it
    to Bilal"), and the Zoom display names alone ("Um-e- Kalsoom") are not the
    names the team is registered under. Giving the model the real spelling up
    front means it extracts "Bilal Khan", not a mis-heard "Bilaal" that then
    fails to match. A user with no full name is listed by the start of their
    email, which is what the rest of the app matches on too.
    """
    attendees = [
        p.name for p in db.scalars(
            select(Participant).where(
                Participant.meeting_id == meeting_id,
                Participant.role == "human",
            )
        )
    ]
    team_names = [
        user.full_name or (user.email or "").split("@")[0]
        for user in db.scalars(select(User))
    ]
    roster = [name.strip() for name in attendees + team_names if name and name.strip()]
    return list(dict.fromkeys(roster))  # de-duplicate, attendees first


async def analyze_and_persist(meeting_id: int, db: Session) -> dict:
    meeting = db.get(Meeting, meeting_id)
    if not meeting or not meeting.transcript:
        return {"summary": "", "decisions": [], "action_items": []}

    notes = await analyze_meeting(meeting.transcript, build_roster(meeting_id, db))
    persist_meeting_notes(meeting_id, notes, db)
    db.commit()
    return notes
