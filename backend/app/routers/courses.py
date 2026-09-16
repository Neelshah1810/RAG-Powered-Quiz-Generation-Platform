"""
Academix AI — Courses, sections and enrollments.

Every course-scoped read passes through `authz.assert_course_member`, so a
student can only ever see courses they are enrolled in (PRD §14).
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.database import get_supabase_admin
from app.dependencies import CurrentUser, get_current_user, require_role
from app.models.course import (
    BulkEnrollmentCreate,
    BulkEnrollmentResult,
    CourseCreate,
    CourseResponse,
    CourseUpdate,
    DepartmentResponse,
    EnrollmentCreate,
    EnrollmentResponse,
    SectionCreate,
    SectionResponse,
)
from app.services import authz, course_service

router = APIRouter()


# ─── Departments ─────────────────────────────────────────────────────────────


@router.get("/departments", response_model=list[DepartmentResponse])
async def list_departments(_: CurrentUser = Depends(get_current_user)):
    """Departments currently in use across the catalogue."""
    return await course_service.list_departments()


# ─── Courses ─────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[CourseResponse])
async def list_courses(current_user: CurrentUser = Depends(get_current_user)):
    """Courses the caller is enrolled in — or all of them, for an admin."""
    return await course_service.list_courses(
        user_id=current_user.id, role=current_user.role
    )


@router.post("/", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    data: CourseCreate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    return await course_service.create_course(data.model_dump(), created_by=current_user.id)


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    authz.assert_course_member(course_id, current_user)
    course = await course_service.get_course(course_id, user_id=current_user.id)
    if not course:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return course


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: str,
    data: CourseUpdate,
    _: CurrentUser = Depends(require_role("admin")),
):
    return await course_service.update_course(course_id, data.model_dump(exclude_none=True))


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: str,
    _: CurrentUser = Depends(require_role("admin")),
):
    """
    Delete a course and everything under it — material, assignments,
    submissions, grades, calendar events and its RAG corpus.
    """
    authz.assert_course_exists(course_id)
    await course_service.delete_course(course_id)


# ─── Sections ────────────────────────────────────────────────────────────────


@router.get("/{course_id}/sections", response_model=list[SectionResponse])
async def list_sections(
    course_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    authz.assert_course_member(course_id, current_user)
    return await course_service.list_sections(course_id)


@router.post(
    "/{course_id}/sections",
    response_model=SectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_section(
    course_id: str,
    data: SectionCreate,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    authz.assert_course_staff(course_id, current_user)
    return await course_service.create_section(course_id, data.name)


@router.delete("/{course_id}/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_section(
    course_id: str,
    section_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    authz.assert_course_staff(course_id, current_user)
    await course_service.delete_section(section_id)


# ─── Enrollments (the People tab) ────────────────────────────────────────────


@router.get("/{course_id}/enrollments", response_model=list[EnrollmentResponse])
async def list_enrollments(
    course_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    The People tab (PRD §9).

    Any enrolled member can see the roster — that is how Google Classroom
    behaves, and classmates knowing each other is not a privacy leak. Phone
    numbers are excluded (PRD §13).
    """
    authz.assert_course_member(course_id, current_user)
    return await course_service.get_course_enrollments(course_id)


@router.post(
    "/{course_id}/enroll",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def enroll_user(
    course_id: str,
    data: EnrollmentCreate,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """
    Enroll one user.

    Admins may enroll anyone anywhere. A teacher may only add students to a
    course they themselves teach, and may not appoint other teachers.
    """
    if current_user.role == "teacher":
        authz.assert_course_staff(course_id, current_user)
        if data.role == "teacher":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only an admin can add a teacher to a course.",
            )
    else:
        authz.assert_course_exists(course_id)

    return await course_service.enroll_user(
        course_id, data.user_id, data.role, data.section_id
    )


@router.post("/{course_id}/enroll/bulk", response_model=BulkEnrollmentResult)
async def bulk_enroll(
    course_id: str,
    data: BulkEnrollmentCreate,
    _: CurrentUser = Depends(require_role("admin")),
):
    authz.assert_course_exists(course_id)
    result = await course_service.bulk_enroll(
        course_id, data.user_ids, data.role, data.section_id
    )
    return BulkEnrollmentResult(**{k: result[k] for k in ("enrolled", "skipped", "errors")})


@router.post("/{course_id}/enroll/csv", response_model=BulkEnrollmentResult)
async def enroll_from_csv(
    course_id: str,
    file: UploadFile = File(...),
    _: CurrentUser = Depends(require_role("admin")),
):
    """
    Roster import from CSV (PRD §9: "bulk CSV via Admin").

    Expects a header row with an `email` column; an optional `role` column
    overrides the default of `student`. Rows whose email has no account are
    reported back rather than silently skipped.
    """
    authz.assert_course_exists(course_id)

    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The CSV file is empty")
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Roster CSV must be under 2 MB"
        )

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The CSV has no header row")

    columns = {(name or "").strip().lower(): name for name in reader.fieldnames}
    if "email" not in columns:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"The CSV needs an 'email' column. Found: {', '.join(reader.fieldnames)}",
        )

    wanted: dict[str, str] = {}
    errors: list[str] = []
    for line_number, row in enumerate(reader, start=2):
        email = (row.get(columns["email"]) or "").strip().lower()
        if not email:
            continue
        role = "student"
        if "role" in columns:
            candidate = (row.get(columns["role"]) or "").strip().lower()
            if candidate in ("teacher", "student"):
                role = candidate
            elif candidate:
                errors.append(f"Row {line_number}: unknown role {candidate!r}, used 'student'")
        wanted[email] = role

    if not wanted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No email addresses found in the CSV")

    profiles = (
        get_supabase_admin()
        .table("profiles")
        .select("id, email")
        .in_("email", list(wanted))
        .execute()
        .data
        or []
    )
    by_email = {p["email"].lower(): p["id"] for p in profiles}

    for email in wanted:
        if email not in by_email:
            errors.append(f"{email}: no account on the platform")

    enrolled = 0
    skipped = 0
    # Group by role so each role is one bulk insert.
    for role in ("teacher", "student"):
        ids = [by_email[e] for e, r in wanted.items() if r == role and e in by_email]
        if not ids:
            continue
        outcome = await course_service.bulk_enroll(course_id, ids, role)
        enrolled += outcome["enrolled"]
        skipped += outcome["skipped"]
        errors.extend(outcome["errors"])

    return BulkEnrollmentResult(enrolled=enrolled, skipped=skipped, errors=errors)


@router.delete("/{course_id}/enroll/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unenroll_user(
    course_id: str,
    user_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """Remove someone from a course. Teachers may only remove students."""
    if current_user.role == "teacher":
        authz.assert_course_staff(course_id, current_user)
        enrollment = authz.get_enrollment(course_id, user_id)
        if enrollment and enrollment["role"] == "teacher":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only an admin can remove a teacher from a course.",
            )
    await course_service.unenroll_user(course_id, user_id)
