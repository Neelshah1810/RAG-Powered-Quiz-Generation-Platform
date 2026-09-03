"""
Academix AI — Classroom (PRD §9, full Google Classroom parity).

Stream, Materials, Assignments, Submissions, Grades and the People roster.

Authorization is *not* handled here — routers call `app/services/authz.py`
first. This module assumes the caller is already entitled to the course.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.database import get_supabase_admin

logger = logging.getLogger(__name__)

# PostgREST needs the FK constraint name to disambiguate when a table joins
# `profiles` more than once, or when the column name differs from the table.
_ANNOUNCEMENT_AUTHOR = "profiles!announcements_posted_by_fkey"
_MATERIAL_UPLOADER = "profiles!materials_uploaded_by_fkey"
_ASSIGNMENT_AUTHOR = "profiles!assignments_created_by_fkey"
_SUBMISSION_STUDENT = "profiles!submissions_student_id_fkey"
# `enrollments` has a single FK to profiles, so the bare table name is
# unambiguous here.
_ROSTER_PROFILE = "profiles"


def _flatten(row: dict, key: str, mapping: dict[str, str]) -> dict:
    """Lift a nested join object onto the parent row, then drop the nesting."""
    nested = row.pop(key, None) or {}
    for source, target in mapping.items():
        row[target] = nested.get(source)
    return row


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse a PostgREST timestamp into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        logger.debug("Unparseable timestamp %r", value)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Announcements
# ─────────────────────────────────────────────────────────────────────────────


async def create_announcement(
    course_id: str,
    posted_by: str,
    text: str,
    attachment_urls: Optional[list[str]] = None,
) -> dict:
    result = (
        get_supabase_admin()
        .table("announcements")
        .insert(
            {
                "course_id": course_id,
                "posted_by": posted_by,
                "text": text,
                "attachment_urls": attachment_urls or [],
            }
        )
        .execute()
    )
    return (result.data or [{}])[0]


async def list_announcements(course_id: str, limit: int = 50) -> list[dict]:
    result = (
        get_supabase_admin()
        .table("announcements")
        .select(f"*, {_ANNOUNCEMENT_AUTHOR}(full_name, avatar_url)")
        .eq("course_id", course_id)
        .order("posted_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [
        _flatten(row, _ANNOUNCEMENT_AUTHOR, {"full_name": "author_name", "avatar_url": "author_avatar"})
        for row in (result.data or [])
    ]


async def delete_announcement(announcement_id: str) -> None:
    get_supabase_admin().table("announcements").delete().eq("id", announcement_id).execute()


# ─────────────────────────────────────────────────────────────────────────────
# Materials
# ─────────────────────────────────────────────────────────────────────────────


async def create_material(
    course_id: str,
    uploaded_by: str,
    title: str,
    file_url: str,
    file_name: str,
    file_size: Optional[int] = None,
    description: Optional[str] = None,
    topic_tag: Optional[str] = None,
    document_id: Optional[str] = None,
) -> dict:
    result = (
        get_supabase_admin()
        .table("materials")
        .insert(
            {
                "course_id": course_id,
                "uploaded_by": uploaded_by,
                "title": title,
                "file_url": file_url,
                "file_name": file_name,
                "file_size": file_size,
                "description": description,
                "topic_tag": topic_tag,
                "document_id": document_id,
            }
        )
        .execute()
    )
    return (result.data or [{}])[0]


async def list_materials(course_id: str, topic_tag: Optional[str] = None) -> list[dict]:
    """
    Materials for a course, each carrying its live RAG ingestion status.

    The status comes from the joined `content_documents` row, so the Classwork
    list can show "indexed" / "processing" / "failed" (with the reason) instead
    of the previous hard-coded "pending" that never changed.
    """
    query = (
        get_supabase_admin()
        .table("materials")
        .select(
            f"*, {_MATERIAL_UPLOADER}(full_name), "
            # Disambiguate: materials.document_id → content_documents (not the reverse material_id FK)
            "content_documents!materials_document_id_fkey(id, status, chunk_count, source_type, exam_type, year, error_message)"
        )
        .eq("course_id", course_id)
        .order("created_at", desc=True)
    )
    if topic_tag:
        query = query.eq("topic_tag", topic_tag)

    materials = []
    for row in (query.execute().data or []):
        _flatten(row, _MATERIAL_UPLOADER, {"full_name": "uploader_name"})
        document = (
            row.pop("content_documents", None)
            or row.pop("content_documents!materials_document_id_fkey", None)
            or {}
        )
        # Prefer the FK on materials; fall back to the joined document id.
        if not row.get("document_id") and document.get("id"):
            row["document_id"] = document["id"]
        row["ingestion_status"] = document.get("status") or (
            "pending" if row.get("document_id") else "not_indexed"
        )
        row["chunk_count"] = document.get("chunk_count") or 0
        row["source_type"] = document.get("source_type") or row.get("source_type")
        row["exam_type"] = document.get("exam_type")
        row["year"] = document.get("year")
        row["ingestion_error"] = document.get("error_message")
        materials.append(row)
    return materials


async def get_material(material_id: str, course_id: str) -> Optional[dict]:
    result = (
        get_supabase_admin()
        .table("materials")
        .select("*")
        .eq("id", material_id)
        .eq("course_id", course_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


async def delete_material(material_id: str) -> Optional[dict]:
    """
    Delete a material and return the row, so the caller can clean up storage.

    The `content_documents` row cascades from `materials.document_id`, which in
    turn cascades its chunks — so removing a material also removes it from the
    RAG index, which is what a teacher expects.
    """
    supabase = get_supabase_admin()
    existing = supabase.table("materials").select("*").eq("id", material_id).limit(1).execute()
    rows = existing.data or []
    if not rows:
        return None

    material = rows[0]
    if material.get("document_id"):
        supabase.table("content_documents").delete().eq("id", material["document_id"]).execute()
    supabase.table("materials").delete().eq("id", material_id).execute()
    return material


async def list_topics(course_id: str) -> list[str]:
    """Distinct topic tags in use on a course, for the topic filter."""
    result = (
        get_supabase_admin()
        .table("materials")
        .select("topic_tag")
        .eq("course_id", course_id)
        .execute()
    )
    topics = {
        (row.get("topic_tag") or "").strip()
        for row in (result.data or [])
    }
    return sorted(t for t in topics if t)


# ─────────────────────────────────────────────────────────────────────────────
# Assignments
# ─────────────────────────────────────────────────────────────────────────────


async def create_assignment(
    course_id: str,
    created_by: str,
    title: str,
    instructions: Optional[str] = None,
    attachment_urls: Optional[list[str]] = None,
    due_at: Optional[str] = None,
    max_points: int = 100,
    topic_tag: Optional[str] = None,
) -> dict:
    result = (
        get_supabase_admin()
        .table("assignments")
        .insert(
            {
                "course_id": course_id,
                "created_by": created_by,
                "title": title,
                "instructions": instructions,
                "attachment_urls": attachment_urls or [],
                "due_at": due_at,
                "max_points": max_points,
                "topic_tag": topic_tag,
            }
        )
        .execute()
    )
    return (result.data or [{}])[0]


async def list_assignments(
    course_id: str,
    student_id: Optional[str] = None,
    expected_student_count: Optional[int] = None,
) -> list[dict]:
    """
    Assignments for a course.

    Pass `student_id` for the student view: each assignment then carries that
    student's own submission state. Otherwise the teacher view is returned,
    with submission and graded counts.

    Counts are computed from one bulk query over all submissions for the
    course rather than two queries per assignment — the previous
    implementation issued 2N round-trips for N assignments.
    """
    supabase = get_supabase_admin()

    result = (
        supabase.table("assignments")
        .select(f"*, {_ASSIGNMENT_AUTHOR}(full_name)")
        .eq("course_id", course_id)
        .order("created_at", desc=True)
        .execute()
    )
    assignments = result.data or []
    if not assignments:
        return []

    assignment_ids = [a["id"] for a in assignments]

    submissions = (
        supabase.table("submissions")
        .select("id, assignment_id, student_id, status, submitted_at, grades(points_awarded, feedback_text, graded_at)")
        .in_("assignment_id", assignment_ids)
        .execute()
    ).data or []

    by_assignment: dict[str, list[dict]] = {}
    for submission in submissions:
        by_assignment.setdefault(submission["assignment_id"], []).append(submission)

    now = _utcnow()

    for assignment in assignments:
        _flatten(assignment, _ASSIGNMENT_AUTHOR, {"full_name": "author_name"})
        rows = by_assignment.get(assignment["id"], [])

        assignment["submission_count"] = len(rows)
        assignment["graded_count"] = sum(1 for r in rows if r.get("status") == "graded")
        if expected_student_count is not None:
            assignment["expected_submission_count"] = expected_student_count

        due = _parse_timestamp(assignment.get("due_at"))
        assignment["is_overdue"] = bool(due and due < now)

        if student_id is not None:
            mine = next((r for r in rows if r["student_id"] == student_id), None)
            if mine:
                grade = (mine.get("grades") or [None])[0] if isinstance(mine.get("grades"), list) else mine.get("grades")
                assignment["my_status"] = mine.get("status")
                assignment["my_submitted_at"] = mine.get("submitted_at")
                assignment["my_points"] = (grade or {}).get("points_awarded")
                assignment["my_feedback"] = (grade or {}).get("feedback_text")
            else:
                # An unsubmitted assignment past its due date reads as "missing",
                # which is what Google Classroom shows the student.
                assignment["my_status"] = "missing" if assignment["is_overdue"] else "not_submitted"
                assignment["my_submitted_at"] = None
                assignment["my_points"] = None
                assignment["my_feedback"] = None

    return assignments


async def get_assignment(assignment_id: str) -> Optional[dict]:
    result = (
        get_supabase_admin()
        .table("assignments")
        .select(f"*, {_ASSIGNMENT_AUTHOR}(full_name), courses(name, code, banner_color)")
        .eq("id", assignment_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None

    assignment = _flatten(rows[0], _ASSIGNMENT_AUTHOR, {"full_name": "author_name"})
    course = assignment.pop("courses", None) or {}
    assignment["course_name"] = course.get("name")
    assignment["course_code"] = course.get("code")
    assignment["course_color"] = course.get("banner_color")

    due = _parse_timestamp(assignment.get("due_at"))
    assignment["is_overdue"] = bool(due and due < _utcnow())
    return assignment


async def update_assignment(assignment_id: str, updates: dict) -> dict:
    clean = {k: v for k, v in updates.items() if v is not None}
    if not clean:
        return await get_assignment(assignment_id) or {}
    if "due_at" in clean and isinstance(clean["due_at"], datetime):
        clean["due_at"] = clean["due_at"].isoformat()
    result = (
        get_supabase_admin()
        .table("assignments")
        .update(clean)
        .eq("id", assignment_id)
        .execute()
    )
    return (result.data or [{}])[0]


async def delete_assignment(assignment_id: str) -> None:
    """Submissions, grades and the auto-created due-date event all cascade."""
    get_supabase_admin().table("assignments").delete().eq("id", assignment_id).execute()


async def list_student_assignments(student_id: str, course_ids: list[str]) -> list[dict]:
    """
    Every assignment across a student's courses, for the dashboard.

    Ordered by due date with undated ones last, so "what's next" is the top of
    the list.
    """
    if not course_ids:
        return []

    supabase = get_supabase_admin()

    assignments = (
        supabase.table("assignments")
        .select("*, courses(name, code, banner_color)")
        .in_("course_id", course_ids)
        .order("due_at", desc=False)
        .execute()
    ).data or []
    if not assignments:
        return []

    submissions = (
        supabase.table("submissions")
        .select("assignment_id, status, submitted_at, grades(points_awarded)")
        .in_("assignment_id", [a["id"] for a in assignments])
        .eq("student_id", student_id)
        .execute()
    ).data or []
    mine = {s["assignment_id"]: s for s in submissions}

    now = _utcnow()
    for assignment in assignments:
        course = assignment.pop("courses", None) or {}
        assignment["course_name"] = course.get("name")
        assignment["course_code"] = course.get("code")
        assignment["course_color"] = course.get("banner_color")

        due = _parse_timestamp(assignment.get("due_at"))
        assignment["is_overdue"] = bool(due and due < now)

        submission = mine.get(assignment["id"])
        if submission:
            grades = submission.get("grades")
            grade = (grades or [None])[0] if isinstance(grades, list) else grades
            assignment["my_status"] = submission.get("status")
            assignment["my_points"] = (grade or {}).get("points_awarded")
        else:
            assignment["my_status"] = "missing" if assignment["is_overdue"] else "not_submitted"
            assignment["my_points"] = None

    # Undated assignments sort after dated ones.
    return sorted(
        assignments,
        key=lambda a: (a.get("due_at") is None, a.get("due_at") or ""),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Submissions
# ─────────────────────────────────────────────────────────────────────────────


async def create_submission(
    assignment_id: str,
    student_id: str,
    file_url: Optional[str] = None,
    file_name: Optional[str] = None,
    text_response: Optional[str] = None,
) -> dict:
    """
    Create or replace a student's submission.

    A late submission is flagged rather than refused (PRD §9: "late submissions
    are flagly marked"). Re-submitting before grading replaces the previous
    attempt; the unique (assignment_id, student_id) constraint makes that an
    upsert.
    """
    supabase = get_supabase_admin()

    assignment = (
        supabase.table("assignments")
        .select("due_at")
        .eq("id", assignment_id)
        .limit(1)
        .execute()
    ).data or []

    status = "submitted"
    if assignment:
        due = _parse_timestamp(assignment[0].get("due_at"))
        if due and _utcnow() > due:
            status = "late"

    record = {
        "assignment_id": assignment_id,
        "student_id": student_id,
        "text_response": text_response,
        "status": status,
        "submitted_at": _utcnow().isoformat(),
    }
    # Only overwrite the stored file when a new one was actually uploaded, so
    # editing a text response does not silently detach an existing attachment.
    if file_url is not None:
        record["file_url"] = file_url
        record["file_name"] = file_name

    result = (
        supabase.table("submissions")
        .upsert(record, on_conflict="assignment_id,student_id")
        .execute()
    )
    return (result.data or [{}])[0]


async def unsubmit(assignment_id: str, student_id: str) -> bool:
    """
    Withdraw a submission so the student can redo it.

    Refused once graded — un-submitting would orphan the teacher's mark.
    """
    supabase = get_supabase_admin()
    existing = (
        supabase.table("submissions")
        .select("id, status")
        .eq("assignment_id", assignment_id)
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    ).data or []

    if not existing or existing[0]["status"] == "graded":
        return False

    supabase.table("submissions").delete().eq("id", existing[0]["id"]).execute()
    return True


async def list_submissions(assignment_id: str, course_id: str) -> list[dict]:
    """
    The teacher's grading list for one assignment.

    Includes every enrolled student, not only those who submitted — a teacher
    needs to see who is missing, which is exactly what Google Classroom shows.
    """
    supabase = get_supabase_admin()

    submitted = (
        supabase.table("submissions")
        .select(f"*, {_SUBMISSION_STUDENT}(full_name, email, avatar_url), grades(*)")
        .eq("assignment_id", assignment_id)
        .execute()
    ).data or []

    rows: list[dict] = []
    seen_students: set[str] = set()

    for submission in submitted:
        _flatten(
            submission,
            _SUBMISSION_STUDENT,
            {"full_name": "student_name", "email": "student_email", "avatar_url": "student_avatar"},
        )
        grades = submission.pop("grades", None)
        if isinstance(grades, list):
            submission["grade"] = grades[0] if grades else None
        else:
            submission["grade"] = grades
        seen_students.add(submission["student_id"])
        rows.append(submission)

    roster = (
        supabase.table("enrollments")
        .select(f"user_id, {_ROSTER_PROFILE}(full_name, email, avatar_url)")
        .eq("course_id", course_id)
        .eq("role", "student")
        .execute()
    ).data or []

    for enrollment in roster:
        if enrollment["user_id"] in seen_students:
            continue
        profile = enrollment.get(_ROSTER_PROFILE) or {}
        rows.append(
            {
                "id": None,
                "assignment_id": assignment_id,
                "student_id": enrollment["user_id"],
                "file_url": None,
                "file_name": None,
                "text_response": None,
                "submitted_at": None,
                "status": "not_submitted",
                "student_name": profile.get("full_name"),
                "student_email": profile.get("email"),
                "student_avatar": profile.get("avatar_url"),
                "grade": None,
            }
        )

    # Submitted-and-ungraded first: that is the teacher's actual work queue.
    order = {"submitted": 0, "late": 1, "graded": 2, "not_submitted": 3}
    return sorted(rows, key=lambda r: (order.get(r["status"], 4), r.get("student_name") or ""))



async def get_student_submission(assignment_id: str, student_id: str) -> Optional[dict]:
    result = (
        get_supabase_admin()
        .table("submissions")
        .select("*, grades(*)")
        .eq("assignment_id", assignment_id)
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None

    submission = rows[0]
    grades = submission.pop("grades", None)
    if isinstance(grades, list):
        submission["grade"] = grades[0] if grades else None
    else:
        submission["grade"] = grades
    return submission


# ─────────────────────────────────────────────────────────────────────────────
# Grades
# ─────────────────────────────────────────────────────────────────────────────


async def grade_submission(
    submission_id: str,
    graded_by: str,
    points_awarded: float,
    feedback_text: Optional[str] = None,
) -> dict:
    """Record or revise a grade and flip the submission to 'graded'."""
    supabase = get_supabase_admin()

    result = (
        supabase.table("grades")
        .upsert(
            {
                "submission_id": submission_id,
                "points_awarded": points_awarded,
                "feedback_text": feedback_text,
                "graded_by": graded_by,
                "graded_at": _utcnow().isoformat(),
            },
            on_conflict="submission_id",
        )
        .execute()
    )

    supabase.table("submissions").update({"status": "graded"}).eq("id", submission_id).execute()
    return (result.data or [{}])[0]


async def get_grade(submission_id: str) -> Optional[dict]:
    result = (
        get_supabase_admin()
        .table("grades")
        .select("*")
        .eq("submission_id", submission_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


async def count_pending_grading(course_ids: list[str]) -> int:
    """
    Submissions awaiting a mark across a teacher's courses.

    Backs the "pending submissions to grade" figure on the teacher dashboard
    (PRD §12.2), which previously displayed a placeholder.
    """
    if not course_ids:
        return 0

    supabase = get_supabase_admin()
    assignments = (
        supabase.table("assignments").select("id").in_("course_id", course_ids).execute()
    ).data or []
    if not assignments:
        return 0

    result = (
        supabase.table("submissions")
        .select("id", count="exact")
        .in_("assignment_id", [a["id"] for a in assignments])
        .in_("status", ["submitted", "late"])
        .execute()
    )
    return result.count or 0


# ─────────────────────────────────────────────────────────────────────────────
# Stream
# ─────────────────────────────────────────────────────────────────────────────


async def get_course_stream(course_id: str, limit: int = 50) -> list[dict]:
    """
    The course home feed (PRD §9, "Stream").

    Announcements, new material and new assignments merged into one
    reverse-chronological list.
    """
    supabase = get_supabase_admin()

    announcements = (
        supabase.table("announcements")
        .select(f"id, text, attachment_urls, posted_at, posted_by, {_ANNOUNCEMENT_AUTHOR}(full_name, avatar_url)")
        .eq("course_id", course_id)
        .order("posted_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []

    materials = (
        supabase.table("materials")
        .select(f"id, title, description, file_url, file_name, topic_tag, created_at, uploaded_by, {_MATERIAL_UPLOADER}(full_name, avatar_url)")
        .eq("course_id", course_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []

    assignments = (
        supabase.table("assignments")
        .select(f"id, title, instructions, due_at, max_points, created_at, created_by, {_ASSIGNMENT_AUTHOR}(full_name, avatar_url)")
        .eq("course_id", course_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []

    stream: list[dict] = []

    for row in announcements:
        author = row.get(_ANNOUNCEMENT_AUTHOR) or {}
        stream.append(
            {
                "id": row["id"],
                "type": "announcement",
                "text": row["text"],
                "attachment_urls": row.get("attachment_urls") or [],
                "author_name": author.get("full_name"),
                "author_avatar": author.get("avatar_url"),
                "created_at": row["posted_at"],
            }
        )

    for row in materials:
        author = row.get(_MATERIAL_UPLOADER) or {}
        stream.append(
            {
                "id": row["id"],
                "type": "material",
                "title": row["title"],
                "text": row.get("description"),
                "file_url": row.get("file_url"),
                "file_name": row.get("file_name"),
                "topic_tag": row.get("topic_tag"),
                "author_name": author.get("full_name"),
                "author_avatar": author.get("avatar_url"),
                "created_at": row["created_at"],
            }
        )

    for row in assignments:
        author = row.get(_ASSIGNMENT_AUTHOR) or {}
        stream.append(
            {
                "id": row["id"],
                "type": "assignment",
                "title": row["title"],
                "text": row.get("instructions"),
                "due_at": row.get("due_at"),
                "max_points": row.get("max_points"),
                "author_name": author.get("full_name"),
                "author_avatar": author.get("avatar_url"),
                "created_at": row["created_at"],
            }
        )

    stream.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return stream[:limit]
