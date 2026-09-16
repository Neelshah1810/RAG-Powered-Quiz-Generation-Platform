"""Academix AI — Course, section and enrollment schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

EnrollmentRole = Literal["teacher", "student"]


# ── Department (derived from courses, not a stored entity) ────────────────────

class DepartmentResponse(BaseModel):
    id: str
    name: str
    code: Optional[str] = None


# ── Courses ──────────────────────────────────────────────────────────────────

class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=40)
    department_name: Optional[str] = None
    semester: Optional[int] = Field(default=None, ge=1, le=12)
    description: Optional[str] = None
    banner_color: Optional[str] = None

    @field_validator("code")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()


class CourseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, min_length=1, max_length=40)
    department_name: Optional[str] = None
    description: Optional[str] = None
    semester: Optional[int] = Field(default=None, ge=1, le=12)
    banner_color: Optional[str] = None


class CourseResponse(BaseModel):
    id: str
    name: str
    code: str
    department_name: Optional[str] = None
    semester: Optional[int] = None
    description: Optional[str] = None
    banner_color: str = "#4285F4"
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    teacher_count: Optional[int] = None
    student_count: Optional[int] = None
    # The requesting user's enrollment role on this course, if any.
    my_role: Optional[str] = None


# ── Sections ─────────────────────────────────────────────────────────────────

class SectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class SectionResponse(BaseModel):
    id: str
    course_id: str
    name: str
    created_at: Optional[datetime] = None


# ── Enrollments ──────────────────────────────────────────────────────────────

class EnrollmentCreate(BaseModel):
    user_id: str
    role: EnrollmentRole
    section_id: Optional[str] = None


class BulkEnrollmentCreate(BaseModel):
    user_ids: list[str] = Field(min_length=1)
    role: EnrollmentRole
    section_id: Optional[str] = None


class BulkEnrollmentResult(BaseModel):
    enrolled: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class EnrollmentResponse(BaseModel):
    id: Optional[str] = None
    course_id: str
    user_id: str
    role: str
    section_id: Optional[str] = None
    section_name: Optional[str] = None
    enrolled_at: Optional[datetime] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_avatar: Optional[str] = None
    user_department: Optional[str] = None
    course_name: Optional[str] = None
