"""Action-item / task management routes.

Who can do what:

* the meeting owner and admins manage a meeting's tasks fully;
* the person a task is assigned to can see it — even when the meeting belongs
  to someone else — and move it between pending / in progress / done.

Assigning (or reassigning) a task, or changing its deadline, notifies the
assignee through :mod:`app.services.notifier`.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import ActionItem, Meeting, User
from app.schemas.tasks import (
    ActionItemCreate,
    ActionItemResponse,
    ActionItemUpdate,
    DashboardStatsResponse,
)
from app.services.action_items import normalize_person_name, resolve_assignee
from app.services.deadlines import format_due, parse_deadline
from app.services.notifier import (
    build_task_ics,
    notify_task_assigned,
    notify_task_completed,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

DUE_SOON = timedelta(hours=48)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _owned_meeting(meeting_id: int, user: User, db: Session) -> Meeting:
    query = select(Meeting).where(Meeting.id == meeting_id)
    if user.role != "admin":
        query = query.where(Meeting.owner_id == user.id)
    meeting = db.scalar(query)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


def _task_for(task_id: int, user: User, db: Session) -> tuple[ActionItem, bool]:
    """Load a task the user may see. Returns (task, user_manages_it)."""
    item = db.get(ActionItem, task_id)
    if not item:
        raise HTTPException(status_code=404, detail="Task not found.")
    manages = user.role == "admin" or item.meeting.owner_id == user.id
    if not manages and item.assignee_user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found.")
    return item, manages


def _assigned_to(user: User):
    """SQL filter for tasks assigned to `user`, including older name-only rows."""
    names = [value for value in (user.full_name, user.email) if value]
    return or_(
        ActionItem.assignee_user_id == user.id,
        ActionItem.assignee_user_id.is_(None) & ActionItem.assignee.in_(names),
    )


def _visible_tasks_query(user: User, scope: str = "all"):
    query = (
        select(ActionItem)
        .join(Meeting, ActionItem.meeting_id == Meeting.id)
        .options(selectinload(ActionItem.meeting), selectinload(ActionItem.assignee_user))
        .order_by(ActionItem.created_at.desc(), ActionItem.id.desc())
    )
    if scope == "assigned":
        return query.where(_assigned_to(user))
    if scope == "created":
        return query.where(Meeting.owner_id == user.id)
    if user.role == "admin":
        return query
    return query.where(or_(Meeting.owner_id == user.id, _assigned_to(user)))


def serialize_task(item: ActionItem, now: datetime | None = None) -> ActionItemResponse:
    now = now or _utcnow()
    return ActionItemResponse(
        id=item.id,
        meeting_id=item.meeting_id,
        meeting_title=item.meeting.title if item.meeting else None,
        assignee=item.assignee,
        assignee_user_id=item.assignee_user_id,
        assignee_email=item.assignee_user.email if item.assignee_user else None,
        assigned_by=item.assigned_by,
        task=item.task,
        deadline=item.deadline,
        due_at=item.due_at,
        priority=item.priority or "medium",
        status=item.status,
        is_overdue=bool(item.due_at and item.status != "done" and item.due_at < now),
        completed_at=item.completed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _set_assignee(item: ActionItem, name: str | None, user_id: int | None, db: Session) -> None:
    if user_id is not None:
        member = db.get(User, user_id)
        if member is None:
            raise HTTPException(status_code=400, detail="That team member does not exist.")
        item.assignee_user_id = member.id
        item.assignee = (name or "").strip() or member.full_name or member.email.split("@")[0]
        return
    cleaned = normalize_person_name(name)
    match = resolve_assignee(cleaned, db) if cleaned else None
    item.assignee = cleaned
    item.assignee_user_id = match.id if match else None


def _set_due(item: ActionItem, deadline: str | None, due_at: datetime | None) -> None:
    text = (deadline or "").strip() or None
    if due_at is not None:
        if due_at.tzinfo is not None:
            due_at = due_at.astimezone(timezone.utc).replace(tzinfo=None)
        item.due_at = due_at
        item.deadline = text or format_due(due_at)
    else:
        item.deadline = text
        item.due_at = parse_deadline(text)
    # A new deadline deserves fresh reminders.
    item.reminder_sent_at = None
    item.overdue_notified_at = None


# ── Per-meeting tasks ────────────────────────────────────────────────────


@router.get("/meeting/{meeting_id}", response_model=list[ActionItemResponse])
def list_meeting_tasks(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ActionItemResponse]:
    _owned_meeting(meeting_id, user, db)
    items = db.scalars(
        select(ActionItem)
        .options(selectinload(ActionItem.meeting), selectinload(ActionItem.assignee_user))
        .where(ActionItem.meeting_id == meeting_id)
        .order_by(ActionItem.created_at.desc(), ActionItem.id.desc())
    )
    now = _utcnow()
    return [serialize_task(item, now) for item in items]


@router.post("/meeting/{meeting_id}", response_model=ActionItemResponse, status_code=201)
def create_task(
    meeting_id: int,
    request: ActionItemCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActionItemResponse:
    meeting = _owned_meeting(meeting_id, user, db)
    item = ActionItem(
        meeting_id=meeting.id,
        task=request.task.strip(),
        assigned_by=(request.assigned_by or "").strip()
        or user.full_name
        or user.email.split("@")[0],
        priority=request.priority,
        status="pending",
    )
    _set_assignee(item, request.assignee, request.assignee_user_id, db)
    _set_due(item, request.deadline, request.due_at)
    db.add(item)
    db.flush()
    notify_task_assigned(db, item, meeting, actor_id=user.id)
    db.commit()
    db.refresh(item)
    return serialize_task(item)


# ── All tasks for the current user ──────────────────────────────────────


@router.get("", response_model=list[ActionItemResponse])
def list_all_tasks(
    status: str | None = None,
    scope: str = "all",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ActionItemResponse]:
    """Tasks the user can see.

    scope=all (default) — your meetings' tasks plus anything assigned to you
    (admins: every task); scope=assigned — only tasks assigned to you;
    scope=created — only tasks from meetings you own.
    """
    query = _visible_tasks_query(user, scope)
    if status:
        query = query.where(ActionItem.status == status)
    now = _utcnow()
    return [serialize_task(item, now) for item in db.scalars(query)]


# ── Dashboard stats ─────────────────────────────────────────────────────


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
def dashboard_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardStatsResponse:
    now = _utcnow()
    meeting_query = select(Meeting)
    if user.role != "admin":
        meeting_query = meeting_query.where(Meeting.owner_id == user.id)
    meetings = list(db.scalars(meeting_query))
    tasks = list(db.scalars(_visible_tasks_query(user)))

    open_tasks = [t for t in tasks if t.status != "done"]
    done = sum(1 for t in tasks if t.status == "done")
    return DashboardStatsResponse(
        total_meetings=len(meetings),
        total_tasks=len(tasks),
        pending_tasks=sum(1 for t in tasks if t.status == "pending"),
        in_progress_tasks=sum(1 for t in tasks if t.status == "in_progress"),
        done_tasks=done,
        recent_meetings=sum(
            1 for m in meetings if m.created_at and m.created_at >= now - timedelta(days=7)
        ),
        overdue_tasks=sum(1 for t in open_tasks if t.due_at and t.due_at < now),
        due_soon_tasks=sum(1 for t in open_tasks if t.due_at and now <= t.due_at <= now + DUE_SOON),
        my_open_tasks=sum(1 for t in open_tasks if t.assignee_user_id == user.id),
        completion_rate=round(done / len(tasks) * 100, 1) if tasks else 0.0,
    )


# ── Single task CRUD ────────────────────────────────────────────────────


@router.get("/{task_id}", response_model=ActionItemResponse)
def get_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActionItemResponse:
    item, _ = _task_for(task_id, user, db)
    return serialize_task(item)


@router.patch("/{task_id}", response_model=ActionItemResponse)
def update_task(
    task_id: int,
    request: ActionItemUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActionItemResponse:
    item, manages = _task_for(task_id, user, db)
    changes = request.model_dump(exclude_unset=True)
    if not manages and set(changes) - {"status"}:
        raise HTTPException(
            status_code=403,
            detail="You can update the status of your task; only the meeting owner can edit its details.",
        )

    meeting = item.meeting
    previous_assignee = item.assignee_user_id
    previous_due = item.due_at
    previous_status = item.status

    if changes.get("task"):
        item.task = changes["task"].strip()
    if "assigned_by" in changes:
        item.assigned_by = (changes["assigned_by"] or "").strip() or None
    if changes.get("priority"):
        item.priority = changes["priority"]
    if "assignee" in changes or "assignee_user_id" in changes:
        _set_assignee(item, changes.get("assignee"), changes.get("assignee_user_id"), db)
    if "deadline" in changes or "due_at" in changes:
        _set_due(item, changes.get("deadline"), changes.get("due_at"))
    if changes.get("status"):
        item.status = changes["status"]
        item.completed_at = _utcnow() if item.status == "done" else None

    db.flush()
    if item.assignee_user_id and item.assignee_user_id != previous_assignee:
        notify_task_assigned(db, item, meeting, actor_id=user.id)
    elif item.assignee_user_id and item.due_at != previous_due:
        notify_task_assigned(db, item, meeting, actor_id=user.id, kind="deadline_changed")
    if item.status == "done" and previous_status != "done":
        notify_task_completed(db, item, meeting, user)

    db.commit()
    db.refresh(item)
    return serialize_task(item)


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    item, manages = _task_for(task_id, user, db)
    if not manages:
        raise HTTPException(status_code=403, detail="Only the meeting owner can delete this task.")
    db.delete(item)
    db.commit()


@router.get("/{task_id}/calendar.ics")
def task_calendar_invite(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Download the task's deadline as a calendar event."""
    item, _ = _task_for(task_id, user, db)
    if item.due_at is None:
        raise HTTPException(status_code=400, detail="This task has no deadline to add to a calendar.")
    return Response(
        content=build_task_ics(item, item.meeting),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="task-{item.id}.ics"'},
    )
