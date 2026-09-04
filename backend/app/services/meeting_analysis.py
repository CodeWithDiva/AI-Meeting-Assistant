"""Persist structured AI notes for a meeting."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.service import analyze_meeting
from app.models import ActionItem, Decision, Meeting, Notification, Summary, User


async def analyze_and_persist(meeting_id: int, db: Session) -> dict:
    meeting = db.get(Meeting, meeting_id)
    if not meeting or not meeting.transcript:
        return {"summary": "", "decisions": [], "action_items": []}

    notes = await analyze_meeting(meeting.transcript)
    summary = db.scalar(select(Summary).where(Summary.meeting_id == meeting_id))
    if summary:
        summary.text = notes["summary"]
        summary.provider = notes.get("provider", summary.provider)
    else:
        db.add(Summary(
            meeting_id=meeting_id,
            text=notes["summary"],
            provider=notes.get("provider", "ollama"),
        ))

    db.query(Decision).filter(Decision.meeting_id == meeting_id).delete()
    db.query(ActionItem).filter(ActionItem.meeting_id == meeting_id).delete()
    for decision in notes.get("decisions", []):
        db.add(Decision(meeting_id=meeting_id, text=decision))

    for raw_item in notes.get("action_items", []):
        assignee = raw_item.get("assignee")
        assignee_user = None
        if assignee:
            assignee_user = db.scalar(
                select(User).where(
                    (User.email.ilike(assignee))
                    | (User.full_name.ilike(assignee))
                )
            )
        item = ActionItem(
            meeting_id=meeting_id,
            assignee=assignee,
            assignee_user_id=assignee_user.id if assignee_user else None,
            assigned_by=raw_item.get("assigned_by"),
            task=raw_item["task"],
            deadline=raw_item.get("deadline"),
        )
        db.add(item)
        if assignee_user and assignee_user.id != meeting.owner_id:
            db.add(Notification(
                user_id=assignee_user.id,
                meeting_id=meeting_id,
                type="task_assigned",
                title=f"Task assigned: {meeting.title}",
                body=f"{raw_item['task']}" + (f" · Due {raw_item['deadline']}" if raw_item.get("deadline") else ""),
                read=False,
            ))

    db.commit()
    return notes
