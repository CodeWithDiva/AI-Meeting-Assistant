"""Small dependency-free password and JWT implementation for the MVP."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_text, digest_text = stored.split("$", 1)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return hmac.compare_digest(actual, expected)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def create_access_token(user_id: int, role: str = "employee") -> str:
    secret = os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY is not configured.")
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64(json.dumps({"sub": str(user_id), "role": role, "exp": int(time.time()) + 1800}, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = _b64(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def get_user_from_token(token: str, db: Session) -> User | None:
    secret = os.getenv("SECRET_KEY")
    if not secret or not token:
        return None
    try:
        header, payload, signature = token.split(".")
        expected = _b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if int(data["exp"]) < int(time.time()):
            return None
        return db.get(User, int(data["sub"]))
    except Exception:
        return None


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    user = get_user_from_token(token, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    return user
