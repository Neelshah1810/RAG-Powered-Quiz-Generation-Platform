"""
Academix AI — Courses, sections and enrollments.

Single-institute scope (PRD §3.3), so department is a plain text attribute on
the course rather than its own entity — the admin UI offers the values already
in use plus free text.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status

from app.database import get_supabase_admin
from app.utils.helpers import generate_course_color

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Departments (derived, not stored)
# ─────────────────────────────────────────────────────────────────────────────


async def list_departments() -> list[dict]:
    """Distinct departments across the course catalogue."""
    result = get_supabase_admin().table("courses").select("department_name").execute()
    names = sorted(
        {
            (row.get("department_name") or "").strip()
            for row in (result.data or [])
            if (row.get("department_name") or "").strip()
        }
    )
    return [{"id": name, "name": name, "code": name} for name in names]


# ─────────────────────────────────────────────────────────────────────────────
# Courses
# ─────────────────────────────────────────────────────────────────────────────


async def list_courses(
    user_id: Optional[str] = None,
    role: Optional[str] = None,
) -> list[dict]:
    """
    Courses visible to a user: their enrollments, or everything for an admin.

    Enrollment counts and the caller's own role on each course come from a
    single bulk query. The previous version issued one query per course, so a
    catalogue of 40 courses meant 41 round-trips per page load.
    """
    supabase = get_supabase_admin()

    if role == "admin" or not user_id:
        courses = (
            supabase.table("courses").select("*").order("name").execute().data or []
        )
    else:
        enrollments = (
            supabase.table("enrollments")
            .select("course_id, role, section_id")
            .eq("user_id", user_id)
            .execute()
            .data
            or []
        )
        if not enrollments:
            return []
        my_role = {e["course_id"]: e["role"] for e in enrollments}
        courses = (
            supabase.table("courses")
            .select("*")
            .in_("id", list(my_role))
            .order("name")
            .execute()
            .data
            or []
        )
        for course in courses:
            course["my_role"] = my_role.get(course["id"])

    if not courses:
        return []

    course_ids = [c["id"] for c in courses]
    all_enrollments = (
        supabase.table("enrollments")
        .select("course_id, role")
        .in_("course_id", course_ids)
        .execute()
        .data
        or []
    )

    counts: dict[str, dict[str, int]] = {cid: {"teacher": 0, "student": 0} for cid in course_ids}
    for enrollment in all_enrollments:
        bucket = counts.setdefault(enrollment["course_id"], {"teacher": 0, "student": 0})
        if enrollment["role"] in bucket:
            bucket[enrollment["role"]] += 1

    for course in courses:
        bucket = counts.get(course["id"], {})
        course["teacher_count"] = bucket.get("teacher", 0)
        course["student_count"] = bucket.get("student", 0)

    return courses


async def get_course(course_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    supabase = get_supabase_admin()
    rows = (
        supabase.table("courses").select("*").eq("id", course_id).limit(1).execute().data or []
    )
    if not rows:
        return None

    course = rows[0]
    enrollments = (
        supabase.table("enrollments")
        .select("user_id, role")
        .eq("course_id", course_id)
        .execute()
        .data
        or []
    )
    course["teacher_count"] = sum(1 for e in enrollments if e["role"] == "teacher")
    course["student_count"] = sum(1 for e in enrollments if e["role"] == "student")
    if user_id:
        course["my_role"] = next(
            (e["role"] for e in enrollments if e["user_id"] == user_id), None
        )
    return course


async def create_course(data: dict, created_by: str) -> dict:
    supabase = get_supabase_admin()

    code = (data.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Course code is required")

    # `courses.code` is UNIQUE; check first so the user gets a clear message
    # instead of a raw Postgres constraint error.
    existing = supabase.table("courses").select("id").eq("code", code).limit(1).execute()
    if existing.data:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A course with code '{code}' already exists.",
        )

    total = supabase.table("courses").select("id", count="exact").execute()
    colour = data.get("banner_color") or generate_course_color(total.count or 0)

    record = {
        "name": (data.get("name") or "").strip(),
        "code": code,
        "department_name": (data.get("department_name") or data.get("department_id") or None),
        "semester": data.get("semester"),
        "description": data.get("description"),
        "banner_color": colour,
        "created_by": created_by,
    }

    result = supabase.table("courses").insert(record).execute()
    course = (result.data or [{}])[0]
    course["teacher_count"] = 0
    course["student_count"] = 0
    return course


async def update_course(course_id: str, updates: dict) -> dict:
    clean = {k: v for k, v in updates.items() if v is not None}
    if "code" in clean:
        clean["code"] = str(clean["code"]).strip().upper()
    if not clean:
        return await get_course(course_id) or {}

    result = (
        get_supabase_admin().table("courses").update(clean).eq("id", course_id).execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return await get_course(course_id) or result.data[0]


async def delete_course(course_id: str) -> None:
    """
    Delete a course.

    Enrollments, classroom content, calendar events and the RAG corpus all
    cascade from the FK definitions in the schema.
    """
    get_supabase_admin().table("courses").delete().eq("id", course_id).execute()


# ─────────────────────────────────────────────────────────────────────────────
# Sections
# ─────────────────────────────────────────────────────────────────────────────


async def list_sections(course_id: str) -> list[dict]:
    result = (
        get_supabase_admin()
        .table("sections")
        .select("*")
        .eq("course_id", course_id)
        .order("name")
        .execute()
    )
    return result.data or []


async def create_section(course_id: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Section name is required")

    supabase = get_supabase_admin()
    existing = (
        supabase.table("sections")
        .select("*")
        .eq("course_id", course_id)
        .eq("name", name)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]

    result = (
        supabase.table("sections").insert({"course_id": course_id, "name": name}).execute()
    )
    return (result.data or [{}])[0]


async def delete_section(section_id: str) -> None:
    get_supabase_admin().table("sections").delete().eq("id", section_id).execute()


# ─────────────────────────────────────────────────────────────────────────────
# Enrollments
# ─────────────────────────────────────────────────────────────────────────────


async def enroll_user(
    course_id: str,
    user_id: str,
    role: str,
    section_id: Optional[str] = None,
) -> dict:
    if role not in ("teacher", "student"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Enrollment role must be 'teacher' or 'student'",
        )

    supabase = get_supabase_admin()

    profile = (
        supabase.table("profiles")
        .select("id, role, full_name, email")
        .eq("id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # Enrolling a student as a teacher would hand them Paper Style and the PYQ
    # corpus, which PRD §14 forbids. Admins may hold either seat.
    account_role = profile[0]["role"]
    if role == "teacher" and account_role == "student":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{profile[0]['full_name']} has a student account and cannot be "
            f"enrolled as a teacher. Change their account role first.",
        )

    existing = (
        supabase.table("enrollments")
        .select("*")
        .eq("course_id", course_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{profile[0]['full_name']} is already enrolled in this course as "
            f"a {existing[0]['role']}.",
        )

    result = (
        supabase.table("enrollments")
        .insert(
            {
                "course_id": course_id,
                "user_id": user_id,
                "role": role,
                "section_id": section_id,
            }
        )
        .execute()
    )
    enrollment = (result.data or [{}])[0]
    enrollment["user_name"] = profile[0]["full_name"]
    enrollment["user_email"] = profile[0]["email"]
    return enrollment


async def bulk_enroll(
    course_id: str,
    user_ids: list[str],
    role: str,
    section_id: Optional[str] = None,
) -> dict:
    """
    Enroll many users at once (PRD §9, "bulk CSV via Admin").

    Reports per-user outcomes rather than failing the whole batch on one bad
    row — an admin importing a 200-name roster needs to know which three
    entries were rejected, not that "the import failed".
    """
    if role not in ("teacher", "student"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Enrollment role must be 'teacher' or 'student'",
        )

    supabase = get_supabase_admin()
    user_ids = list(dict.fromkeys(uid for uid in user_ids if uid))
    if not user_ids:
        return {"enrolled": 0, "skipped": 0, "errors": [], "enrollments": []}

    profiles = {
        p["id"]: p
        for p in (
            supabase.table("profiles")
            .select("id, role, full_name")
            .in_("id", user_ids)
            .execute()
            .data
            or []
        )
    }
    already = {
        e["user_id"]
        for e in (
            supabase.table("enrollments")
            .select("user_id")
            .eq("course_id", course_id)
            .in_("user_id", user_ids)
            .execute()
            .data
            or []
        )
    }

    records: list[dict] = []
    errors: list[str] = []
    skipped = 0

    for user_id in user_ids:
        profile = profiles.get(user_id)
        if not profile:
            errors.append(f"{user_id}: no such user")
            continue
        if user_id in already:
            skipped += 1
            continue
        if role == "teacher" and profile["role"] == "student":
            errors.append(f"{profile['full_name']}: student account cannot be a course teacher")
            continue
        records.append(
            {
                "course_id": course_id,
                "user_id": user_id,
                "role": role,
                "section_id": section_id,
            }
        )

    enrolled: list[dict] = []
    if records:
        result = supabase.table("enrollments").insert(records).execute()
        enrolled = result.data or []

    return {
        "enrolled": len(enrolled),
        "skipped": skipped,
        "errors": errors,
        "enrollments": enrolled,
    }


async def unenroll_user(course_id: str, user_id: str) -> None:
    get_supabase_admin().table("enrollments").delete().eq("course_id", course_id).eq(
        "user_id", user_id
    ).execute()


async def get_course_enrollments(course_id: str) -> list[dict]:
    """The People tab (PRD §9): teachers first, then students, each A-Z."""
    result = (
        get_supabase_admin()
        .table("enrollments")
        .select("*, profiles(id, full_name, email, avatar_url, department), sections(name)")
        .eq("course_id", course_id)
        .execute()
    )

    enrollments = []
    for row in (result.data or []):
        profile = row.pop("profiles", None) or {}
        section = row.pop("sections", None) or {}
        row["user_name"] = profile.get("full_name")
        row["user_email"] = profile.get("email")
        row["user_avatar"] = profile.get("avatar_url")
        row["user_department"] = profile.get("department")
        row["section_name"] = section.get("name")
        enrollments.append(row)

    return sorted(
        enrollments,
        key=lambda e: (e["role"] != "teacher", (e.get("user_name") or "").lower()),
    )


async def check_enrollment(course_id: str, user_id: str) -> Optional[dict]:
    result = (
        get_supabase_admin()
        .table("enrollments")
        .select("*")
        .eq("course_id", course_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


async def count_course_students(course_id: str) -> int:
    result = (
        get_supabase_admin()
        .table("enrollments")
        .select("id", count="exact")
        .eq("course_id", course_id)
        .eq("role", "student")
        .execute()
    )
    return result.count or 0
