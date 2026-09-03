import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.database import get_db
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
    user = User(email=email, password_hash=hash_password(request.password), role=role)
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
