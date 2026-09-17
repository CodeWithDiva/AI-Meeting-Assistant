import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.database import get_db
from app.models import ActionItem, Meeting, User
from app.schemas.auth import (
    AcceptInviteRequest,
    AdminUserInvite,
    AdminUserInviteResponse,
    AdminUserUpdate,
    InviteDetails,
    LoginRequest,
    ProfileUpdate,
    RegisterRequest,
    TeamMember,
    TokenResponse,
    UserResponse,
)
from app.services.notifier import email_enabled, send_invite_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

_INVITE_LIFETIME = timedelta(days=7)


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _invite_link(token: str) -> str:
    base = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/accept-invite?token={token}"


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)) -> dict[str, bool]:
    """True on a brand-new install — the users table is completely empty.

    Distinct from "zero admins": a workspace that already has employees but
    lost its admins must never let a stranger register their way into admin
    (see `register` below). This only ever fires once, on the very first
    screen a fresh deployment shows, before anyone at all has an account.
    """
    has_any_user = db.scalar(select(User.id).limit(1)) is not None
    return {"needs_setup": not has_any_user}


@router.post("/setup", response_model=TokenResponse, status_code=201)
def setup_first_admin(request: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Create the very first account — as admin — on a brand-new install.

    Only works while the users table is empty. Once this workspace has an
    owner, every later account goes through the normal `register`
    (employee-by-default) or invite flow; this endpoint then refuses
    permanently, so it can never be replayed to mint a second free admin.
    """
    if db.scalar(select(User.id).limit(1)) is not None:
        raise HTTPException(status_code=409, detail="This workspace is already set up.")

    user = User(
        email=request.email.lower(),
        password_hash=hash_password(request.password),
        full_name=(request.full_name or "").strip() or None,
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user, from_attributes=True))


@router.post("/register", response_model=UserResponse, status_code=201)
def register(request: RegisterRequest, db: Session = Depends(get_db)) -> User:
    email = request.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email is already registered.")
    # Admin is granted only by explicit action — matching ADMIN_EMAILS in
    # .env, or an existing admin promoting someone from the Team page. A new
    # registration is never trusted to grant itself admin access, even when
    # the workspace currently has no admin at all.
    admin_emails = {
        item.strip().lower()
        for item in os.getenv("ADMIN_EMAILS", "").split(",")
        if item.strip()
    }
    role = "admin" if email in admin_emails else "employee"
    user = User(
        email=email,
        password_hash=hash_password(request.password),
        full_name=(request.full_name or "").strip() or None,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == request.email.lower()))
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")
    if user.invite_token is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account hasn't been set up yet — use the invite link that was sent to set a password.",
        )
    try:
        token = create_access_token(user.id, user.role)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user, from_attributes=True))


@router.post("/token", include_in_schema=False)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> dict[str, str]:
    """OAuth2-compatible form endpoint used by Swagger's Authorize dialog."""
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")
    try:
        access_token = create_access_token(user.id, user.role)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=UserResponse)
def update_profile(
    request: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Set your display name — the name the assistant matches spoken task owners to."""
    user.full_name = request.full_name.strip()
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[TeamMember])
def list_team_members(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    """Everyone a task can be assigned to (invited-but-not-yet-active people included)."""
    return list(db.scalars(select(User).order_by(func.lower(func.coalesce(User.full_name, User.email)))))


# ---------------------------------------------------------------------------
# Invites — accepted by the invited person, no auth required
# ---------------------------------------------------------------------------


@router.get("/invite/{token}", response_model=InviteDetails)
def get_invite(token: str, db: Session = Depends(get_db)) -> InviteDetails:
    """What the accept-invite page shows before asking for a password."""
    user = db.scalar(select(User).where(User.invite_token == token))
    if not user or not user.invite_expires_at or user.invite_expires_at < _now():
        raise HTTPException(status_code=404, detail="This invite link is invalid or has expired.")
    return InviteDetails(email=user.email, full_name=user.full_name)


@router.post("/accept-invite", response_model=TokenResponse)
def accept_invite(request: AcceptInviteRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Set a password for an admin-invited account and sign them straight in."""
    user = db.scalar(select(User).where(User.invite_token == request.token))
    if not user or not user.invite_expires_at or user.invite_expires_at < _now():
        raise HTTPException(status_code=404, detail="This invite link is invalid or has expired.")

    user.password_hash = hash_password(request.password)
    user.invite_token = None
    user.invite_expires_at = None
    db.commit()
    db.refresh(user)

    try:
        access_token = create_access_token(user.id, user.role)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return TokenResponse(access_token=access_token, user=UserResponse.model_validate(user, from_attributes=True))


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@router.get("/admin/users", tags=["admin"])
def list_all_users(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Admin-only: return all registered users with activity stats."""
    _require_admin(user)
    now = _now()

    users = list(db.scalars(select(User).order_by(User.created_at.desc())))
    result = []
    for u in users:
        meeting_count = db.scalar(
            select(func.count(Meeting.id)).where(Meeting.owner_id == u.id)
        ) or 0
        tasks = list(db.scalars(select(ActionItem).where(ActionItem.assignee_user_id == u.id)))
        open_tasks = [t for t in tasks if t.status != "done"]
        result.append({
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "status": "invited" if u.invite_token else "active",
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "meeting_count": meeting_count,
            "task_count": len(tasks),
            "open_tasks": len(open_tasks),
            "overdue_tasks": sum(1 for t in open_tasks if t.due_at and t.due_at < now),
            "done_tasks": len(tasks) - len(open_tasks),
        })
    return result


@router.post("/admin/users", response_model=AdminUserInviteResponse, status_code=201, tags=["admin"])
def admin_invite_user(
    request: AdminUserInvite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AdminUserInviteResponse:
    """Admin-only: add a team member by name and email — no password to hand out.

    They get a link that lets them set their own password. It's emailed when
    SMTP is configured; either way it's returned here so the admin can send
    it themselves (chat, WhatsApp, in person).
    """
    _require_admin(user)
    email = request.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email is already registered.")

    invite_token = secrets.token_urlsafe(32)
    member = User(
        email=email,
        full_name=request.full_name.strip(),
        # Unusable placeholder — no plaintext password can ever hash to this,
        # so the account cannot be logged into until the invite is accepted.
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role=request.role,
        invite_token=invite_token,
        invite_expires_at=_now() + _INVITE_LIFETIME,
    )
    db.add(member)
    db.flush()

    link = _invite_link(invite_token)
    send_invite_email(db, to=member.email, full_name=member.full_name or "", invite_link=link)
    db.commit()
    db.refresh(member)

    return AdminUserInviteResponse(
        user=UserResponse.model_validate(member, from_attributes=True),
        invite_link=link,
        email_sent=email_enabled(),
    )


@router.post("/admin/users/{user_id}/resend-invite", response_model=AdminUserInviteResponse, tags=["admin"])
def admin_resend_invite(
    user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AdminUserInviteResponse:
    """Admin-only: issue a fresh link for someone who never finished setup."""
    _require_admin(user)
    member = db.get(User, user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if member.invite_token is None:
        raise HTTPException(status_code=400, detail="This person has already set up their account.")

    member.invite_token = secrets.token_urlsafe(32)
    member.invite_expires_at = _now() + _INVITE_LIFETIME
    link = _invite_link(member.invite_token)
    send_invite_email(db, to=member.email, full_name=member.full_name or "", invite_link=link)
    db.commit()
    db.refresh(member)

    return AdminUserInviteResponse(
        user=UserResponse.model_validate(member, from_attributes=True),
        invite_link=link,
        email_sent=email_enabled(),
    )


@router.patch("/admin/users/{user_id}", response_model=UserResponse, tags=["admin"])
def admin_update_user(
    user_id: int,
    request: AdminUserUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Admin-only: rename a member or change their role."""
    _require_admin(user)
    member = db.get(User, user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if request.role and member.id == user.id and request.role != "admin":
        raise HTTPException(status_code=400, detail="You can't remove your own admin role.")
    if request.full_name is not None:
        member.full_name = request.full_name.strip()
    if request.role:
        member.role = request.role
    db.commit()
    db.refresh(member)
    return member


@router.delete("/admin/users/{user_id}", status_code=204, tags=["admin"])
def admin_delete_user(
    user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Admin-only: remove someone who never accepted their invite (or has left)."""
    _require_admin(user)
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="You can't remove your own account.")
    member = db.get(User, user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="User not found.")
    db.delete(member)
    db.commit()
