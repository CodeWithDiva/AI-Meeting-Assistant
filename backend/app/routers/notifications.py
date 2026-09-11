"""Router for user in-app notifications."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Notification, User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    meeting_id: int | None
    type: str
    title: str
    body: str | None
    read: bool
    created_at: str | None

    model_config = {"from_attributes": True}


def _serialize(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=n.id,
        user_id=n.user_id,
        meeting_id=n.meeting_id,
        type=n.type,
        title=n.title,
        body=n.body,
        read=n.read,
        created_at=n.created_at.isoformat() if n.created_at else None,
    )


@router.get("", response_model=list[NotificationResponse])
def get_user_notifications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    unread_only: bool = False,
    limit: int = 30,
):
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read == False)  # noqa: E712
    # `created_at` has one-second resolution, so the id breaks ties and the
    # newest notification is reliably first.
    query = query.order_by(desc(Notification.created_at), desc(Notification.id)).limit(
        max(1, min(limit, 100))
    )
    return [_serialize(n) for n in db.scalars(query)]


@router.get("/unread-count")
def unread_count(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read == False  # noqa: E712
        )
    )
    return {"unread": count or 0}


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notif = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found.")

    notif.read = True
    db.commit()
    db.refresh(notif)
    return _serialize(notif)


@router.post("/mark-all-read")
def mark_all_notifications_read(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notifs = list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == user.id, Notification.read == False  # noqa: E712
            )
        )
    )
    for n in notifs:
        n.read = True
    db.commit()
    return {"status": "success", "count": len(notifs)}
