"""Action-item / task management routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import ActionItem, Meeting, User
from app.schemas.tasks import (
    ActionItemCreate,
    ActionItemResponse,
    ActionItemUpdate,
    DashboardStatsResponse,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _owned_meeting(meeting_id: int, user: User, db: Session) -> Meeting:
    query = select(Meeting).where(Meeting.id == meeting_id)
    if user.role != "admin":
        query = query.where(Meeting.owner_id == user.id)
    meeting = db.scalar(query)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


# ── Per-meeting tasks ────────────────────────────────────────────────────


@router.get("/meeting/{meeting_id}", response_model=list[ActionItemResponse])
def list_meeting_tasks(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ActionItem]:
    _owned_meeting(meeting_id, user, db)
    return list(
        db.scalars(
            select(ActionItem)
            .where(ActionItem.meeting_id == meeting_id)
            .order_by(ActionItem.created_at.desc())
        )
    )


@router.post("/meeting/{meeting_id}", response_model=ActionItemResponse, status_code=201)
def create_task(
    meeting_id: int,
    request: ActionItemCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActionItem:
    _owned_meeting(meeting_id, user, db)
    assignee_user = None
    if request.assignee:
        assignee_user = db.scalar(
            select(User).where(
                (User.email.ilike(request.assignee))
                | (User.full_name.ilike(request.assignee))
            )
        )
    item = ActionItem(
        meeting_id=meeting_id,
        assignee=request.assignee,
        assignee_user_id=assignee_user.id if assignee_user else None,
        assigned_by=request.assigned_by,
        task=request.task,
        deadline=request.deadline,
    )
    db.add(item)
    if assignee_user and assignee_user.id != user.id:
        from app.models import Notification

        db.add(Notification(
            user_id=assignee_user.id,
            meeting_id=meeting_id,
            type="task_assigned",
            title="New task assigned",
            body=request.task + (f" · Due {request.deadline}" if request.deadline else ""),
            read=False,
        ))
    db.commit()
    db.refresh(item)
    return item


# ── All tasks for the current user ──────────────────────────────────────


@router.get("", response_model=list[ActionItemResponse])
def list_all_tasks(
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ActionItem]:
    """All action items across all meetings owned by the current user."""
    query = (
        select(ActionItem)
        .join(Meeting, ActionItem.meeting_id == Meeting.id)
        .where(Meeting.owner_id == user.id if user.role != "admin" else True)
        .order_by(ActionItem.created_at.desc())
    )
    if user.role != "admin":
        query = query.where(
            (ActionItem.assignee_user_id == user.id)
            | (ActionItem.assignee == user.full_name)
            | (ActionItem.assignee == user.email)
        )
    if status:
        query = query.where(ActionItem.status == status)
    return list(db.scalars(query))


# ── Single task CRUD ────────────────────────────────────────────────────


@router.get("/{task_id}", response_model=ActionItemResponse)
def get_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActionItem:
    item = db.get(ActionItem, task_id)
    if not item:
        raise HTTPException(status_code=404, detail="Task not found.")
    _owned_meeting(item.meeting_id, user, db)
    return item


@router.patch("/{task_id}", response_model=ActionItemResponse)
def update_task(
    task_id: int,
    request: ActionItemUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActionItem:
    item = db.get(ActionItem, task_id)
    if not item:
        raise HTTPException(status_code=404, detail="Task not found.")
    _owned_meeting(item.meeting_id, user, db)
    for key, value in request.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    item = db.get(ActionItem, task_id)
    if not item:
        raise HTTPException(status_code=404, detail="Task not found.")
    _owned_meeting(item.meeting_id, user, db)
    db.delete(item)
    db.commit()


# ── Dashboard stats ─────────────────────────────────────────────────────


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
def dashboard_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardStatsResponse:
    meetings = list(
        db.scalars(select(Meeting).where(Meeting.owner_id == user.id))
    )
    meeting_ids = [m.id for m in meetings]
    if not meeting_ids:
        return DashboardStatsResponse()

    all_tasks = list(
        db.scalars(select(ActionItem).where(ActionItem.meeting_id.in_(meeting_ids)))
    )
    return DashboardStatsResponse(
        total_meetings=len(meetings),
        total_tasks=len(all_tasks),
        pending_tasks=sum(1 for t in all_tasks if t.status == "pending"),
        done_tasks=sum(1 for t in all_tasks if t.status == "done"),
        recent_meetings=min(len(meetings), 5),
    )
