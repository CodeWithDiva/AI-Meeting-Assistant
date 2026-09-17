"""Direct messaging between workspace users.

Plain person-to-person chat — admin<->employee or employee<->employee,
about anything ("what's the project status?", "can you send me the file?")
— separate from the per-meeting "Ask Alina" Q&A in `chat.py`/`workspace.py`.
A conversation is just every Message between two user ids; there is no
separate Conversation table.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_user_from_token
from app.database import SessionLocal, get_db
from app.models import Message, Notification, User
from app.services.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/messages", tags=["messages"])

# Keyed by user_id rather than meeting_id — the same broadcast/connect
# machinery as the per-meeting channel, just a separate namespace, since a
# DM isn't scoped to any one meeting.
dm_ws_manager = ConnectionManager()


class UserBrief(BaseModel):
    id: int
    full_name: str | None
    email: str
    role: str

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    sender_id: int
    recipient_id: int
    body: str
    read_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    user: UserBrief
    last_message: MessageOut | None
    unread_count: int


class SendMessageRequest(BaseModel):
    recipient_id: int
    body: str = Field(min_length=1, max_length=4000)


def _serialize(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        sender_id=m.sender_id,
        recipient_id=m.recipient_id,
        body=m.body,
        read_at=m.read_at.isoformat() if m.read_at else None,
        created_at=m.created_at.isoformat() if m.created_at else "",
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationOut]:
    """Everyone the current user has exchanged a message with, most recent first."""
    rows = list(
        db.scalars(
            select(Message)
            .where(or_(Message.sender_id == user.id, Message.recipient_id == user.id))
            .order_by(desc(Message.created_at), desc(Message.id))
        )
    )
    by_counterpart: dict[int, list[Message]] = {}
    for m in rows:
        counterpart_id = m.recipient_id if m.sender_id == user.id else m.sender_id
        by_counterpart.setdefault(counterpart_id, []).append(m)

    conversations: list[ConversationOut] = []
    for counterpart_id, messages in by_counterpart.items():
        counterpart = db.get(User, counterpart_id)
        if not counterpart:
            continue
        unread = sum(
            1 for m in messages if m.recipient_id == user.id and m.read_at is None
        )
        conversations.append(
            ConversationOut(
                user=UserBrief.model_validate(counterpart),
                last_message=_serialize(messages[0]),
                unread_count=unread,
            )
        )
    # `messages` within each group is already newest-first (query order), and
    # groups themselves need the same ordering by their own newest message.
    conversations.sort(key=lambda c: c.last_message.created_at if c.last_message else "", reverse=True)
    return conversations


@router.get("/unread-count")
def unread_count(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    count = db.scalar(
        select(func.count(Message.id)).where(
            Message.recipient_id == user.id, Message.read_at.is_(None)
        )
    )
    return {"unread": count or 0}


@router.get("/thread/{other_user_id}", response_model=list[MessageOut])
def get_thread(
    other_user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    other = db.get(User, other_user_id)
    if not other:
        raise HTTPException(status_code=404, detail="User not found.")

    messages = list(
        db.scalars(
            select(Message)
            .where(
                or_(
                    and_(Message.sender_id == user.id, Message.recipient_id == other_user_id),
                    and_(Message.sender_id == other_user_id, Message.recipient_id == user.id),
                )
            )
            .order_by(Message.created_at, Message.id)
        )
    )

    # Opening the thread reads whatever the other person sent me.
    now = datetime.utcnow()
    changed = False
    for m in messages:
        if m.recipient_id == user.id and m.read_at is None:
            m.read_at = now
            changed = True
    if changed:
        db.commit()

    return [_serialize(m) for m in messages]


@router.post("", response_model=MessageOut)
async def send_message(
    request: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    if request.recipient_id == user.id:
        raise HTTPException(status_code=400, detail="Can't message yourself.")
    recipient = db.get(User, request.recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found.")

    message = Message(sender_id=user.id, recipient_id=recipient.id, body=request.body.strip())
    db.add(message)

    sender_name = user.full_name or user.email
    preview = request.body.strip()
    notif = Notification(
        user_id=recipient.id,
        type="direct_message",
        title=f"New message from {sender_name}",
        body=preview[:280],
    )
    db.add(notif)
    db.commit()
    db.refresh(message)

    out = _serialize(message)
    payload = out.model_dump()
    # Push to both sides: the recipient (new message) and the sender's other
    # open tabs/devices (so it appears without a manual refresh there too).
    await dm_ws_manager.broadcast(recipient.id, "new_message", payload)
    await dm_ws_manager.broadcast(user.id, "new_message", payload)
    return out


@router.websocket("/ws")
async def messages_ws(websocket: WebSocket) -> None:
    """Per-user realtime channel — pushes `new_message` events as they arrive."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    with SessionLocal() as db:
        user = get_user_from_token(token, db)
    if not user:
        await websocket.close(code=4401)
        return

    await dm_ws_manager.connect(user.id, websocket)
    try:
        while True:
            # No client->server messages expected on this channel; just keep
            # the connection open and notice a disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("DM websocket error for user %d", user.id)
    finally:
        await dm_ws_manager.disconnect(user.id, websocket)
