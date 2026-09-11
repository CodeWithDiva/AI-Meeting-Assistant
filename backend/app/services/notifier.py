"""Tell people about their tasks — in the app, and by email when configured.

Every path that assigns a task (the meeting bot's notes, "Generate notes",
the task form, reassigning on the board) calls :func:`notify_task_assigned`,
so the assignee always hears about it the same way:

* an in-app notification (the bell in the top bar), always;
* an email with the task, its deadline and a calendar invite, when
  ``SMTP_HOST`` is set in ``.env``.

Emails are queued on the database session and only sent after that session
commits — a task that fails to save never produces an email about itself.
Sending happens on a background thread so a slow mail server cannot stall a
request.

:func:`run_deadline_sweep` is the other half: run periodically by the server,
it reminds assignees shortly before a deadline and flags overdue tasks to both
the assignee and the meeting owner, each exactly once.
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import event, select
from sqlalchemy.orm import Session, selectinload

from app.models import ActionItem, Meeting, Notification, User
from app.services.deadlines import format_due

logger = logging.getLogger(__name__)

_PENDING_EMAILS = "pending_task_emails"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def reminder_window() -> timedelta:
    return timedelta(hours=float(os.getenv("TASK_REMINDER_HOURS", "24")))


def email_enabled() -> bool:
    return bool(os.getenv("SMTP_HOST", "").strip())


def due_label(item: ActionItem) -> str | None:
    """The deadline as people said it, plus the resolved date when that adds something."""
    pretty = format_due(item.due_at)
    spoken = (item.deadline or "").strip()
    if spoken and pretty and spoken.casefold() not in pretty.casefold():
        return f"{spoken} ({pretty})"
    return spoken or pretty


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

_TITLES = {
    "task_assigned": "New task from: {meeting}",
    "deadline_changed": "Deadline changed: {meeting}",
}


def notify_task_assigned(
    db: Session,
    item: ActionItem,
    meeting: Meeting,
    *,
    actor_id: int | None = None,
    kind: str = "task_assigned",
) -> Notification | None:
    """Notify a task's assignee. Returns the notification, or None if nobody to tell.

    `actor_id` is whoever made the change; people are not notified about
    tasks they assigned to themselves. The caller owns the transaction.
    """
    if not item.assignee_user_id or item.assignee_user_id == actor_id:
        return None
    assignee = db.get(User, item.assignee_user_id)
    if assignee is None:
        return None

    due = due_label(item)
    notification = Notification(
        user_id=assignee.id,
        meeting_id=meeting.id,
        type=kind,
        title=_TITLES.get(kind, _TITLES["task_assigned"]).format(meeting=meeting.title),
        body=item.task + (f" · Due {due}" if due else ""),
        read=False,
    )
    db.add(notification)

    heading = "You have a new task" if kind == "task_assigned" else "A deadline on your task changed"
    _queue_email(
        db,
        to=assignee.email,
        subject=f"{'Task' if kind == 'task_assigned' else 'Deadline changed'}: {_shorten(item.task)}",
        text=_task_email_text(heading, item, meeting, assignee),
        ics=build_task_ics(item, meeting) if item.due_at else None,
    )
    return notification


def notify_task_completed(db: Session, item: ActionItem, meeting: Meeting, actor: User) -> None:
    """Tell the meeting owner someone finished a task from their meeting."""
    if meeting.owner_id == actor.id:
        return
    who = actor.full_name or actor.email.split("@")[0]
    db.add(Notification(
        user_id=meeting.owner_id,
        meeting_id=meeting.id,
        type="task_completed",
        title=f"Task completed: {meeting.title}",
        body=f"{who} finished: {item.task}",
        read=False,
    ))


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


def run_deadline_sweep(
    db: Session,
    now: datetime | None = None,
    *,
    task_ids: list[int] | None = None,
) -> dict[str, int]:
    """Send due-soon reminders and overdue alerts that have not gone out yet.

    Tasks without a registered assignee are reported to the meeting owner, so
    an unassigned task still cannot slip past its deadline unnoticed.
    `task_ids` limits the sweep to specific tasks.
    """
    now = now or _utcnow()
    window = reminder_window()
    counts = {"reminders": 0, "overdue": 0}

    query = (
        select(ActionItem)
        .options(selectinload(ActionItem.meeting), selectinload(ActionItem.assignee_user))
        .where(ActionItem.status != "done", ActionItem.due_at.is_not(None))
    )
    if task_ids is not None:
        query = query.where(ActionItem.id.in_(task_ids))
    for item in db.scalars(query):
        meeting = item.meeting
        if meeting is None:
            continue
        recipient = item.assignee_user or db.get(User, meeting.owner_id)
        if recipient is None:
            continue
        due = due_label(item)

        if item.due_at <= now:
            if item.overdue_notified_at is not None:
                continue
            db.add(Notification(
                user_id=recipient.id,
                meeting_id=meeting.id,
                type="task_overdue",
                title=f"Overdue: {_shorten(item.task, 70)}",
                body=f"This task from {meeting.title} was due {due}.",
                read=False,
            ))
            _queue_email(
                db,
                to=recipient.email,
                subject=f"Overdue: {_shorten(item.task)}",
                text=_task_email_text("This task is past its deadline", item, meeting, recipient),
            )
            if item.assignee_user and item.assignee_user.id != meeting.owner_id:
                db.add(Notification(
                    user_id=meeting.owner_id,
                    meeting_id=meeting.id,
                    type="task_overdue",
                    title=f"Overdue task for {item.assignee or recipient.email}",
                    body=f"{item.task} · was due {due}",
                    read=False,
                ))
            item.overdue_notified_at = now
            counts["overdue"] += 1
        elif item.due_at - now <= window and item.reminder_sent_at is None:
            db.add(Notification(
                user_id=recipient.id,
                meeting_id=meeting.id,
                type="deadline_approaching",
                title=f"Due soon: {_shorten(item.task, 70)}",
                body=f"Due {due} · from {meeting.title}",
                read=False,
            ))
            _queue_email(
                db,
                to=recipient.email,
                subject=f"Reminder — due {format_due(item.due_at)}: {_shorten(item.task)}",
                text=_task_email_text("Reminder: this task is due soon", item, meeting, recipient),
                ics=build_task_ics(item, meeting),
            )
            item.reminder_sent_at = now
            counts["reminders"] += 1

    db.commit()
    if counts["reminders"] or counts["overdue"]:
        logger.info("Deadline sweep: %s", counts)
    return counts


async def deadline_reminder_loop(interval_seconds: float) -> None:
    """Run :func:`run_deadline_sweep` forever; started by the server at startup."""
    from app.database import SessionLocal

    def _sweep() -> None:
        with SessionLocal() as db:
            run_deadline_sweep(db)

    while True:
        try:
            await asyncio.to_thread(_sweep)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Deadline reminder sweep failed; will retry.")
        await asyncio.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# Calendar invite
# ---------------------------------------------------------------------------


def build_task_ics(item: ActionItem, meeting: Meeting) -> str:
    """A one-event iCalendar file for a task's deadline."""
    due = item.due_at or _utcnow()
    stamp = _utcnow().strftime("%Y%m%dT%H%M%SZ")
    uid = f"task-{item.id or uuid.uuid4().hex}@ai-meeting-assistant"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AI Meeting Assistant//Tasks//EN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{(due - timedelta(minutes=30)).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{due.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_ics_escape('Due: ' + item.task)}",
        f"DESCRIPTION:{_ics_escape(f'From the meeting: {meeting.title}')}",
        "BEGIN:VALARM",
        "TRIGGER:-PT1H",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_ics_escape(item.task)}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    )


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------


def _task_email_text(heading: str, item: ActionItem, meeting: Meeting, recipient: User) -> str:
    app_url = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    name = recipient.full_name or recipient.email.split("@")[0]
    lines = [
        f"Hi {name},",
        "",
        f"{heading}:",
        "",
        f"  {item.task}",
        "",
        f"Meeting:   {meeting.title}",
    ]
    if item.assigned_by:
        lines.append(f"Assigned by: {item.assigned_by}")
    lines.append(f"Deadline:  {due_label(item) or 'No deadline'}")
    lines.append(f"Priority:  {(item.priority or 'medium').title()}")
    lines += ["", f"Open your tasks: {app_url}/tasks", "", "— AI Meeting Assistant"]
    return "\n".join(lines)


def _shorten(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _queue_email(db: Session, *, to: str, subject: str, text: str, ics: str | None = None) -> None:
    if not email_enabled() or not to:
        return
    message = EmailMessage()
    message["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USERNAME") or "assistant@localhost"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if ics:
        message.add_attachment(
            ics.encode("utf-8"), maintype="text", subtype="calendar", filename="task.ics"
        )
    db.info.setdefault(_PENDING_EMAILS, []).append(message)


@event.listens_for(Session, "after_commit")
def _send_queued_emails(session: Session) -> None:
    messages = session.info.pop(_PENDING_EMAILS, None)
    if messages:
        threading.Thread(target=_deliver, args=(messages,), daemon=True).start()


@event.listens_for(Session, "after_rollback")
def _drop_queued_emails(session: Session) -> None:
    session.info.pop(_PENDING_EMAILS, None)


def _deliver(messages: list[EmailMessage]) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME") or None
    password = os.getenv("SMTP_PASSWORD") or None
    use_ssl = port == 465 or os.getenv("SMTP_USE_SSL", "").lower() in {"1", "true", "yes"}
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.ehlo()
            if os.getenv("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}:
                server.starttls()
                server.ehlo()
        with server:
            if username:
                server.login(username, password or "")
            for message in messages:
                server.send_message(message)
        logger.info("Sent %d task email(s) via %s.", len(messages), host)
    except Exception as exc:
        logger.warning("Could not send %d task email(s) via %s: %s", len(messages), host, exc)
