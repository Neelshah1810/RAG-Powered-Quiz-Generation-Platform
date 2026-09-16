"""
Academix AI — Classroom schemas (PRD §9 / §9.1).

Announcements, Materials, Assignments, Submissions, Grades, Stream.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

SourceType = Literal["notes", "textbook", "pyq"]
ExamType = Literal["internal", "external"]
SubmissionStatus = Literal["not_submitted", "missing", "submitted", "late", "graded"]


# ── Announcements ────────────────────────────────────────────────────────────

class AnnouncementCreate(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    attachment_urls: list[str] = Field(default_factory=list)


class AnnouncementResponse(BaseModel):
    id: str
    course_id: str
    posted_by: str
    text: str
    attachment_urls: list[str] = Field(default_factory=list)
    posted_at: Optional[datetime] = None
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None


# ── Materials ────────────────────────────────────────────────────────────────

class MaterialResponse(BaseModel):
    id: str
    course_id: str
    uploaded_by: str
    title: str
    description: Optional[str] = None
    file_url: str
    file_name: str
    file_size: Optional[int] = None
    topic_tag: Optional[str] = None
    document_id: Optional[str] = None
    created_at: Optional[datetime] = None
    uploader_name: Optional[str] = None
    # RAG ingestion state, joined from content_documents
    source_type: Optional[str] = None
    exam_type: Optional[str] = None
    year: Optional[int] = None
    ingestion_status: Optional[str] = None
    ingestion_error: Optional[str] = None
    chunk_count: int = 0


class DownloadResponse(BaseModel):
    download_url: str
    file_name: str
    expires_in_seconds: int


# ── Assignments ──────────────────────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    instructions: Optional[str] = None
    attachment_urls: list[str] = Field(default_factory=list)
    due_at: Optional[datetime] = None
    max_points: int = Field(default=100, ge=1, le=1000)
    topic_tag: Optional[str] = None


class AssignmentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    instructions: Optional[str] = None
    attachment_urls: Optional[list[str]] = None
    due_at: Optional[datetime] = None
    max_points: Optional[int] = Field(default=None, ge=1, le=1000)
    topic_tag: Optional[str] = None
    # Explicitly clear a due date — `due_at: None` alone is indistinguishable
    # from "not supplied" once optional fields are stripped.
    clear_due_date: bool = False


class AssignmentResponse(BaseModel):
    id: str
    course_id: str
    created_by: str
    title: str
    instructions: Optional[str] = None
    attachment_urls: list[str] = Field(default_factory=list)
    due_at: Optional[datetime] = None
    max_points: int = 100
    topic_tag: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    author_name: Optional[str] = None
    is_overdue: bool = False
    # Teacher view
    submission_count: Optional[int] = None
    graded_count: Optional[int] = None
    expected_submission_count: Optional[int] = None
    # Student view
    my_status: Optional[str] = None
    my_submitted_at: Optional[datetime] = None
    my_points: Optional[float] = None
    my_feedback: Optional[str] = None
    # Joined when listed across courses (dashboard)
    course_name: Optional[str] = None
    course_code: Optional[str] = None
    course_color: Optional[str] = None


# ── Submissions & grades ─────────────────────────────────────────────────────

class GradeResponse(BaseModel):
    id: str
    submission_id: str
    points_awarded: float
    feedback_text: Optional[str] = None
    graded_by: str
    graded_at: Optional[datetime] = None


class SubmissionResponse(BaseModel):
    # None for a roster entry representing a student who has not submitted.
    id: Optional[str] = None
    assignment_id: str
    student_id: str
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    text_response: Optional[str] = None
    submitted_at: Optional[datetime] = None
    status: str = "submitted"
    student_name: Optional[str] = None
    student_email: Optional[str] = None
    student_avatar: Optional[str] = None
    grade: Optional[GradeResponse] = None


class GradeCreate(BaseModel):
    submission_id: str
    points_awarded: float = Field(ge=0)
    feedback_text: Optional[str] = None

    @field_validator("points_awarded")
    @classmethod
    def _round_half_marks(cls, value: float) -> float:
        # Teachers award half marks; anything finer is noise in a point-based
        # scheme (PRD §9: "simple point-based grading only").
        return round(value * 2) / 2


# ── Stream ───────────────────────────────────────────────────────────────────

class StreamItem(BaseModel):
    """One entry in the course home feed."""

    id: str
    type: Literal["announcement", "material", "assignment"]
    title: Optional[str] = None
    text: Optional[str] = None
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None
    created_at: Optional[datetime] = None
    # Type-specific
    due_at: Optional[datetime] = None
    max_points: Optional[int] = None
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    topic_tag: Optional[str] = None
    attachment_urls: list[str] = Field(default_factory=list)


# ── Dashboards ───────────────────────────────────────────────────────────────

class StudentDashboard(BaseModel):
    course_count: int = 0
    pending_assignments: list[AssignmentResponse] = Field(default_factory=list)
    pending_count: int = 0
    overdue_count: int = 0
    upcoming_events: list[dict[str, Any]] = Field(default_factory=list)
    recent_attempts: list[dict[str, Any]] = Field(default_factory=list)
    unread_notices: int = 0


class TeacherDashboard(BaseModel):
    course_count: int = 0
    student_count: int = 0
    pending_grading: int = 0
    todays_events: list[dict[str, Any]] = Field(default_factory=list)
    upcoming_events: list[dict[str, Any]] = Field(default_factory=list)
    recent_drafts: list[dict[str, Any]] = Field(default_factory=list)
    unread_notices: int = 0


class AdminDashboard(BaseModel):
    total_users: int = 0
    admins: int = 0
    teachers: int = 0
    students: int = 0
    course_count: int = 0
    document_count: int = 0
    indexed_documents: int = 0
    generated_set_count: int = 0
    quiz_attempt_count: int = 0
    upcoming_events: list[dict[str, Any]] = Field(default_factory=list)
