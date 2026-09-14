from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # The name people say in meetings — what task assignment matches against.
    full_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None = None
    role: str = "employee"
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)


class TeamMember(BaseModel):
    """The minimum needed to pick someone as a task assignee."""

    id: int
    email: EmailStr
    full_name: str | None = None
    role: str = "employee"


class AdminUserInvite(BaseModel):
    """Add an employee by name and email only — no password.

    They get a link (emailed when SMTP is configured, always also returned
    here so the admin can share it directly) that lets them set their own
    password. Nobody but the employee ever has it.
    """

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "employee"] = "employee"


class AdminUserInviteResponse(BaseModel):
    user: UserResponse
    invite_link: str
    email_sent: bool


class AdminUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Literal["admin", "employee"] | None = None


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


class InviteDetails(BaseModel):
    """What the accept-invite page shows before the person sets a password."""

    email: EmailStr
    full_name: str | None = None
    workspace_name: str | None = None
