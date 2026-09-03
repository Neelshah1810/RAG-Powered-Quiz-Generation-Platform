"""Academix AI — Notice Board schemas (PRD §11)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

NoticeType = Literal[
    "announcement", "assignment", "grade", "event", "material", "system", "admin"
]


class NoticeCreate(BaseModel):
    course_id: Optional[str] = None  # None = institute-wide
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)
    notice_type: NoticeType = "announcement"
    # Narrow an institute-wide notice to particular roles.
    target_roles: Optional[list[Literal["admin", "teacher", "student"]]] = None
    send_email: bool = False


class NoticeResponse(BaseModel):
    id: str
    course_id: Optional[str] = None
    author_id: Optional[str] = None
    title: str
    body: str
    notice_type: str
    target_roles: list[str] = Field(default_factory=lambda: ["admin", "teacher", "student"])
    target_user_id: Optional[str] = None
    created_at: Optional[datetime] = None
    is_read: bool = False
    # Joined
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None
    course_name: Optional[str] = None
    course_code: Optional[str] = None


class NoticeListResponse(BaseModel):
    notices: list[NoticeResponse]
    total: int
    unread_count: int


class MarkReadRequest(BaseModel):
    notice_ids: list[str] = Field(default_factory=list)
