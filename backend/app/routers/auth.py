import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.database import get_db
from app.models import ActionItem, Meeting, User
from app.schemas.auth import (
    AdminUserCreate,
    AdminUserUpdate,
    LoginRequest,
    ProfileUpdate,
    RegisterRequest,
    TeamMember,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")


@router.post("/register", response_model=UserResponse, status_code=201)
def register(request: RegisterRequest, db: Session = Depends(get_db)) -> User:
    email = request.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email is already registered.")
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
    """Everyone a task can be assigned to."""
    return list(db.scalars(select(User).order_by(func.lower(func.coalesce(User.full_name, User.email)))))


@router.get("/admin/users", tags=["admin"])
def list_all_users(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Admin-only: return all registered users with activity stats."""
    _require_admin(user)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

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
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "meeting_count": meeting_count,
            "task_count": len(tasks),
            "open_tasks": len(open_tasks),
            "overdue_tasks": sum(1 for t in open_tasks if t.due_at and t.due_at < now),
            "done_tasks": len(tasks) - len(open_tasks),
        })
    return result


@router.post("/admin/users", response_model=UserResponse, status_code=201, tags=["admin"])
def admin_create_user(
    request: AdminUserCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Admin-only: add a team member with a starting password."""
    _require_admin(user)
    email = request.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email is already registered.")
    member = User(
        email=email,
        full_name=request.full_name.strip(),
        password_hash=hash_password(request.password),
        role=request.role,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


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
