"""Turn extracted action items into real, assigned, notified tasks.

Previously the live meeting pipeline wrote `ActionItem` rows with a free-text
`assignee` string and stopped there: nothing linked the task to a `User`, so it
never appeared on that person's task list and they were never notified. Every
path that produces action items now goes through :func:`persist_meeting_notes`
so "the agent assigns the task to Ali" actually reaches Ali.

Name resolution is deliberately conservative — a task assigned to the wrong
person is worse than an unassigned one — so a candidate must match a user's
email, full name, or a whole name token. It never guesses on a partial match,
and it refuses ambiguous first names shared by two users.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActionItem, Decision, Meeting, Notification, Summary, User

logger = logging.getLogger(__name__)

# Titles and fillers that show up in speech ("sir Ali", "Ali sahab") and would
# otherwise stop a name from matching a registered user.
_HONORIFICS = {
    "mr", "mrs", "ms", "miss", "dr", "sir", "madam", "engr",
    "sahab", "sahib", "saab", "bhai", "baji", "apa", "janab",
    "صاحب", "جناب", "سر", "بھائی", "باجی",
}
_TOKEN_SPLIT = re.compile(r"[\s.,_-]+", re.UNICODE)

# Words the LLM sometimes returns instead of a person, when nobody was named.
_NON_PERSON = {
    "team", "everyone", "all", "everybody", "unassigned", "n/a", "na",
    "none", "null", "tbd", "someone", "nobody", "the team",
    "ٹیم", "سب", "سب لوگ",
}


def normalize_person_name(raw: str | None) -> str | None:
    """Strip honorifics and punctuation; return None if it names no person."""
    if not raw:
        return None
    cleaned = raw.strip().strip("\"'()[]")
    if not cleaned or cleaned.casefold() in _NON_PERSON:
        return None
    tokens = [t for t in _TOKEN_SPLIT.split(cleaned) if t]
    kept = [t for t in tokens if t.casefold().strip(".") not in _HONORIFICS]
    result = " ".join(kept or tokens).strip()
    return result or None


def resolve_assignee(name: str | None, db: Session) -> User | None:
    """Best-effort map a spoken name to a registered user.

    Tries, in order: exact email, exact full name, then a unique whole-token
    match (so "Ali" finds "Ali Khan", but not if two users are named Ali).
    Returns None rather than risk assigning to the wrong person.
    """
    normalized = normalize_person_name(name)
    if not normalized:
        return None

    exact = db.scalar(
        select(User).where(
            (User.email.ilike(normalized)) | (User.full_name.ilike(normalized))
        )
    )
    if exact:
        return exact

    # "Ali" → "Ali Khan". Compare whole tokens so "Ali" never matches "Alina".
    wanted = {t.casefold() for t in _TOKEN_SPLIT.split(normalized) if t}
    if not wanted:
        return None

    matches = []
    for user in db.scalars(select(User)):
        candidates = set()
        if user.full_name:
            candidates |= {t.casefold() for t in _TOKEN_SPLIT.split(user.full_name) if t}
        if user.email:
            candidates.add(user.email.split("@")[0].casefold())
        if wanted & candidates:
            matches.append(user)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logger.info(
            "Assignee %r is ambiguous across %d users — leaving it unlinked.",
            normalized, len(matches),
        )
    return None


def persist_meeting_notes(
    meeting_id: int,
    notes: dict,
    db: Session,
    *,
    notify_summary: bool = False,
) -> dict:
    """Replace a meeting's summary, decisions and action items with `notes`.

    Resolves each action item's assignee to a real user and raises a
    `task_assigned` notification for them. Returns a small report of what was
    written, so callers can log or surface "3 tasks assigned, 1 unassigned".

    The caller owns the transaction; this function does not commit.
    """
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        return {"decisions": 0, "action_items": 0, "assigned": 0, "unassigned": 0}

    summary_text = (notes.get("summary") or "").strip()
    provider = notes.get("provider", "ollama")
    if summary_text:
        summary = db.scalar(select(Summary).where(Summary.meeting_id == meeting_id))
        if summary:
            summary.text = summary_text
            summary.provider = provider
        else:
            db.add(Summary(meeting_id=meeting_id, text=summary_text, provider=provider))

    db.query(Decision).filter(Decision.meeting_id == meeting_id).delete()
    db.query(ActionItem).filter(ActionItem.meeting_id == meeting_id).delete()

    decisions = [d for d in (notes.get("decisions") or []) if isinstance(d, str) and d.strip()]
    for decision in decisions:
        db.add(Decision(meeting_id=meeting_id, text=decision.strip()))

    assigned = unassigned = 0
    for raw_item in notes.get("action_items") or []:
        task = (raw_item.get("task") or "").strip()
        if not task:
            continue

        assignee_name = normalize_person_name(raw_item.get("assignee"))
        assignee_user = resolve_assignee(assignee_name, db)
        deadline = raw_item.get("deadline") or None

        db.add(ActionItem(
            meeting_id=meeting_id,
            assignee=assignee_name,
            assignee_user_id=assignee_user.id if assignee_user else None,
            assigned_by=normalize_person_name(raw_item.get("assigned_by")),
            task=task,
            deadline=deadline,
        ))

        if assignee_user:
            assigned += 1
            # Don't ping the owner about their own meeting's tasks — they get
            # the summary notification instead.
            if assignee_user.id != meeting.owner_id:
                db.add(Notification(
                    user_id=assignee_user.id,
                    meeting_id=meeting_id,
                    type="task_assigned",
                    title=f"New task from: {meeting.title}",
                    body=task + (f" · Due {deadline}" if deadline else ""),
                    read=False,
                ))
        else:
            unassigned += 1

    if notify_summary:
        db.add(Notification(
            user_id=meeting.owner_id,
            meeting_id=meeting_id,
            type="summary_ready",
            title=f"Notes ready: {meeting.title}",
            body=(
                f"{len(decisions)} decision(s), {assigned + unassigned} task(s) "
                f"— {assigned} assigned automatically."
            ),
            read=False,
        ))
        meeting.ended_at = meeting.ended_at or datetime.now(timezone.utc).replace(tzinfo=None)

    report = {
        "decisions": len(decisions),
        "action_items": assigned + unassigned,
        "assigned": assigned,
        "unassigned": unassigned,
    }
    logger.info("Persisted notes for meeting %d: %s", meeting_id, report)
    return report
