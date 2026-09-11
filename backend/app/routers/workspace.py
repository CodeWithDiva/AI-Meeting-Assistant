"""Workspace-wide features: search across meetings, note export, team analytics."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    ActionItem,
    Decision,
    Meeting,
    Participant,
    Speaker,
    TranscriptSegment,
    User,
)
from app.routers.tasks import _visible_tasks_query, serialize_task
from app.services.deadlines import format_due

router = APIRouter(tags=["workspace"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _meeting_scope(user: User):
    return True if user.role == "admin" else Meeting.owner_id == user.id


# ── Search ──────────────────────────────────────────────────────────────


@router.get("/api/workspace/search")
def search_workspace(
    q: str,
    limit: int = 8,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Find meetings, transcript lines, decisions and tasks matching `q`."""
    term = q.strip()
    empty = {"query": term, "meetings": [], "transcript": [], "decisions": [], "tasks": []}
    if len(term) < 2:
        return empty
    like = f"%{term}%"
    limit = max(1, min(limit, 25))
    scope = _meeting_scope(user)

    meetings = db.scalars(
        select(Meeting)
        .where(scope, Meeting.title.ilike(like))
        .order_by(Meeting.created_at.desc())
        .limit(limit)
    )
    segments = db.execute(
        select(TranscriptSegment, Meeting.title)
        .join(Meeting, TranscriptSegment.meeting_id == Meeting.id)
        .where(scope, TranscriptSegment.text.ilike(like))
        .order_by(TranscriptSegment.created_at.desc())
        .limit(limit)
    )
    decisions = db.execute(
        select(Decision, Meeting.title)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .where(scope, Decision.text.ilike(like))
        .order_by(Decision.created_at.desc())
        .limit(limit)
    )
    tasks = db.scalars(
        _visible_tasks_query(user)
        .where(ActionItem.task.ilike(like) | ActionItem.assignee.ilike(like))
        .limit(limit)
    )

    return {
        "query": term,
        "meetings": [
            {
                "id": m.id,
                "title": m.title,
                "platform": m.platform,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in meetings
        ],
        "transcript": [
            {
                "meeting_id": seg.meeting_id,
                "meeting_title": title,
                "speaker": seg.speaker_label,
                "text": seg.text,
                "start_time": seg.start_time,
            }
            for seg, title in segments
        ],
        "decisions": [
            {"meeting_id": d.meeting_id, "meeting_title": title, "text": d.text}
            for d, title in decisions
        ],
        "tasks": [serialize_task(t).model_dump(mode="json") for t in tasks],
    }


# ── Export ──────────────────────────────────────────────────────────────


@router.get("/api/meetings/{meeting_id}/export.md")
def export_meeting_markdown(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """The meeting's notes, decisions, tasks and transcript as a Markdown file."""
    meeting = db.scalar(
        select(Meeting)
        .options(
            selectinload(Meeting.summary),
            selectinload(Meeting.decisions),
            selectinload(Meeting.action_items),
            selectinload(Meeting.segments),
        )
        .where(Meeting.id == meeting_id, _meeting_scope(user))
    )
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    names = {
        s.speaker_label: s.display_name
        for s in db.scalars(select(Speaker).where(Speaker.meeting_id == meeting_id))
        if s.display_name
    }
    attendees = [
        p.name
        for p in db.scalars(select(Participant).where(Participant.meeting_id == meeting_id))
        if p.role == "human"
    ]

    held = meeting.scheduled_at or meeting.created_at
    platform = (meeting.platform or "direct").replace("_", " ").title()
    lines = [f"# {meeting.title}", ""]
    lines.append(f"**Platform:** {platform}  ")
    if held:
        lines.append(f"**Date:** {held.strftime('%d %b %Y, %H:%M')} UTC  ")
    if attendees:
        lines.append(f"**Attendees:** {', '.join(attendees)}  ")
    lines += ["", "## Summary", "", (meeting.summary.text.strip() if meeting.summary else "_No summary yet._"), ""]

    lines += ["## Decisions", ""]
    if meeting.decisions:
        lines += [f"{i}. {d.text}" for i, d in enumerate(meeting.decisions, 1)]
    else:
        lines.append("_No decisions recorded._")
    lines.append("")

    lines += ["## Action items", ""]
    if meeting.action_items:
        lines += ["| Task | Owner | Deadline | Priority | Status |", "| --- | --- | --- | --- | --- |"]
        for item in meeting.action_items:
            deadline = item.deadline or format_due(item.due_at) or "—"
            cells = [
                item.task,
                item.assignee or "Unassigned",
                deadline,
                (item.priority or "medium").title(),
                item.status.replace("_", " ").title(),
            ]
            lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    else:
        lines.append("_No action items._")
    lines.append("")

    lines += ["## Transcript", ""]
    if meeting.segments:
        for seg in meeting.segments:
            minutes, seconds = divmod(int(seg.start_time or 0), 60)
            speaker = names.get(seg.speaker_label, seg.speaker_label or "Speaker")
            lines.append(f"**[{minutes:02d}:{seconds:02d}] {speaker}:** {seg.text}  ")
    elif meeting.transcript:
        lines.append(meeting.transcript)
    else:
        lines.append("_No transcript._")

    slug = re.sub(r"[^a-z0-9]+", "-", meeting.title.lower()).strip("-") or f"meeting-{meeting.id}"
    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
    )


# ── Admin analytics ─────────────────────────────────────────────────────


@router.get("/api/admin/analytics", tags=["admin"])
def team_analytics(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Admin-only: meeting volume, task health and each member's workload."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    now = _utcnow()

    meetings = list(db.scalars(select(Meeting)))
    tasks = list(
        db.scalars(
            select(ActionItem).options(
                selectinload(ActionItem.meeting), selectinload(ActionItem.assignee_user)
            )
        )
    )
    members = list(db.scalars(select(User)))

    # Eight weeks, oldest first, each starting on Monday.
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    weeks = []
    for offset in range(7, -1, -1):
        start = this_monday - timedelta(weeks=offset)
        end = start + timedelta(weeks=1)
        weeks.append({
            "week_start": start.date().isoformat(),
            "meetings": sum(1 for m in meetings if m.created_at and start <= m.created_at < end),
            "tasks_created": sum(1 for t in tasks if t.created_at and start <= t.created_at < end),
            "tasks_completed": sum(1 for t in tasks if t.completed_at and start <= t.completed_at < end),
        })

    open_tasks = [t for t in tasks if t.status != "done"]
    overdue = [t for t in open_tasks if t.due_at and t.due_at < now]
    status_counts = Counter(t.status for t in tasks)

    workload = []
    for member in members:
        assigned = [t for t in tasks if t.assignee_user_id == member.id]
        done = sum(1 for t in assigned if t.status == "done")
        member_open = [t for t in assigned if t.status != "done"]
        workload.append({
            "user_id": member.id,
            "name": member.full_name or member.email.split("@")[0],
            "email": member.email,
            "role": member.role,
            "meetings_owned": sum(1 for m in meetings if m.owner_id == member.id),
            "assigned": len(assigned),
            "open": len(member_open),
            "overdue": sum(1 for t in member_open if t.due_at and t.due_at < now),
            "done": done,
            "completion_rate": round(done / len(assigned) * 100, 1) if assigned else None,
        })
    workload.sort(key=lambda row: (-row["open"], -row["assigned"], row["name"].lower()))

    return {
        "totals": {
            "members": len(members),
            "meetings": len(meetings),
            "meetings_this_week": weeks[-1]["meetings"],
            "tasks": len(tasks),
            "open_tasks": len(open_tasks),
            "overdue_tasks": len(overdue),
            "unassigned_open_tasks": sum(1 for t in open_tasks if not t.assignee_user_id),
            "completion_rate": round(status_counts.get("done", 0) / len(tasks) * 100, 1) if tasks else 0.0,
        },
        "status_counts": {
            "pending": status_counts.get("pending", 0),
            "in_progress": status_counts.get("in_progress", 0),
            "done": status_counts.get("done", 0),
        },
        "weeks": weeks,
        "workload": workload,
        "overdue": [
            serialize_task(t, now).model_dump(mode="json")
            for t in sorted(overdue, key=lambda t: t.due_at)[:10]
        ],
    }
