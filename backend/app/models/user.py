"""Academix AI — User and auth schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

Role = Literal["admin", "teacher", "student"]


# ── Requests ─────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    """Provision an account (admin only)."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    department: Optional[str] = None
    phone: Optional[str] = None


class SignUpRequest(UserCreate):
    """Alias kept because the frontend posts to /auth/signup."""

    role: Role = "student"


class UserUpdate(BaseModel):
    """Fields a user may change on their own profile."""

    full_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    department: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None


class UserRoleUpdate(BaseModel):
    role: Role


class PasswordResetRequest(BaseModel):
    """Admin-set password."""

    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()


class RefreshRequest(BaseModel):
    """Body-carried refresh token.

    The previous handler took it as a query parameter, which put a credential
    in the URL — and therefore in access logs and browser history.
    """

    refresh_token: str


# ── Responses ────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    department: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: Optional[int] = None


class LoginResponse(TokenResponse):
    user: UserResponse


class UserStats(BaseModel):
    total: int = 0
    admins: int = 0
    teachers: int = 0
    students: int = 0
