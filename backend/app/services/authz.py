"""
Academix AI — Authorization service.

The backend talks to Postgres with the service_role key, which bypasses RLS,
so *every* access rule the PRD asks for has to be enforced here. This module is
the single place those rules live.

Rules implemented (PRD §14 "Role-based data isolation", §13 Data Privacy):

  * A student sees only courses they are enrolled in, and only that course's
    material, assignments, grades and roster.
  * A teacher sees only courses they teach.
  * An admin has institute-wide visibility.
  * Students can never reach Paper Style output or the raw PYQ corpus
    (PRD §14 first bullet) — enforced on both the mode and the corpus.
  * A student can read only their own submission; a teacher only submissions
    for assignments in a course they teach.
  * A generated set is readable by the person who requested it, plus admins;
    a Paper Style set is additionally readable by teachers of that course.

Every helper raises `fastapi.HTTPException` directly, so routers can call them
as a guard without writing branching logic.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.database import get_supabase_admin
from app.dependencies import CurrentUser

# ─────────────────────────────────────────────────────────────────────────────
# Enrollment lookups
# ─────────────────────────────────────────────────────────────────────────────


def get_enrollment(course_id: str, user_id: str) -> dict | None:
    """The user's enrollment row for a course, or None."""
    result = (
        get_supabase_admin()
        .table("enrollments")
        .select("id, role, section_id")
        .eq("course_id", course_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_user_course_ids(user: CurrentUser, role: str | None = None) -> list[str]:
    """
    Course ids the user may see.

    Admins get every course. Others get their enrollments, optionally narrowed
    to a specific enrollment role ("teacher" / "student").
    """
    supabase = get_supabase_admin()

    if user.role == "admin":
        result = supabase.table("courses").select("id").execute()
        return [row["id"] for row in (result.data or [])]

    query = supabase.table("enrollments").select("course_id").eq("user_id", user.id)
    if role:
        query = query.eq("role", role)
    result = query.execute()
    return [row["course_id"] for row in (result.data or [])]


def is_course_teacher(course_id: str, user: CurrentUser) -> bool:
    """True if the user may act as staff on this course."""
    if user.role == "admin":
        return True
    enrollment = get_enrollment(course_id, user.id)
    return bool(enrollment and enrollment["role"] == "teacher")


# ─────────────────────────────────────────────────────────────────────────────
# Course guards
# ─────────────────────────────────────────────────────────────────────────────


def assert_course_exists(course_id: str) -> dict:
    result = (
        get_supabase_admin()
        .table("courses")
        .select("*")
        .eq("id", course_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return rows[0]


def assert_course_member(course_id: str, user: CurrentUser) -> dict:
    """
    The user must be enrolled in the course (any role), or be an admin.

    Returns the course row so callers that need it avoid a second query.
    """
    course = assert_course_exists(course_id)
    if user.role == "admin":
        return course
    if get_enrollment(course_id, user.id) is None:
        # 404 rather than 403: telling a non-member that a course exists but is
        # off-limits leaks the roster of the institute's course catalogue.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return course


def assert_course_staff(course_id: str, user: CurrentUser) -> dict:
    """The user must teach this course, or be an admin."""
    course = assert_course_exists(course_id)
    if is_course_teacher(course_id, user):
        return course
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a teacher of this course (or an admin) can perform this action",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Classroom guards
# ─────────────────────────────────────────────────────────────────────────────


def assert_assignment_in_course(assignment_id: str, course_id: str) -> dict:
    """
    Load an assignment and confirm it really belongs to the course in the URL.

    Without this, `/classroom/{my_course}/assignments/{someone_elses_id}` would
    pass the course guard and then act on an assignment from another course.
    """
    result = (
        get_supabase_admin()
        .table("assignments")
        .select("*")
        .eq("id", assignment_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows or rows[0]["course_id"] != course_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    return rows[0]


def assert_submission_access(submission_id: str, user: CurrentUser) -> dict:
    """
    A submission is readable by its author, by a teacher of the assignment's
    course, and by admins. Returns the submission with its assignment attached.
    """
    supabase = get_supabase_admin()
    result = (
        supabase.table("submissions")
        .select("*, assignments(id, course_id, title, max_points)")
        .eq("id", submission_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")

    submission = rows[0]
    assignment = submission.get("assignments") or {}
    course_id = assignment.get("course_id")

    if user.role == "admin":
        return submission
    if submission["student_id"] == user.id:
        return submission
    if course_id and is_course_teacher(course_id, user):
        return submission

    raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")


# ─────────────────────────────────────────────────────────────────────────────
# RAG guards
# ─────────────────────────────────────────────────────────────────────────────


def assert_can_use_mode(mode: str, course_id: str, user: CurrentUser) -> None:
    """
    Gate the two generation modes.

    PRD §14: "Students never see Paper Style outputs or the raw PYQ corpus …
    so they cannot reverse-engineer an actual upcoming exam."
    """
    if mode == "paper_style":
        if user.role == "student":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Paper Style is available to teachers only",
            )
        assert_course_staff(course_id, user)
    elif mode == "quiz_generation":
        assert_course_member(course_id, user)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown mode {mode!r}")


def assert_set_access(set_id: str, user: CurrentUser, *, require_staff: bool = False) -> dict:
    """
    Load a generated set the user is allowed to see.

    `require_staff=True` additionally demands teacher/admin rights on the
    course — used for the edit / approve / delete endpoints, which must not be
    reachable by the student who happened to generate a quiz.
    """
    result = (
        get_supabase_admin()
        .table("generated_sets")
        .select("*")
        .eq("id", set_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generated set not found")

    generated_set = rows[0]

    # Hard block first: a student must never load Paper Style output, even if
    # some other rule would otherwise let them through.
    if generated_set["mode"] == "paper_style" and user.role == "student":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generated set not found")

    is_owner = generated_set["requested_by"] == user.id
    is_staff = is_course_teacher(generated_set["course_id"], user)

    if require_staff:
        if not is_staff:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only a teacher of this course (or an admin) can modify a generated set",
            )
        return generated_set

    if is_owner or user.role == "admin":
        return generated_set
    # Teachers can review Paper Style sets drafted by colleagues on their course.
    if is_staff and generated_set["mode"] == "paper_style":
        return generated_set

    raise HTTPException(status.HTTP_404_NOT_FOUND, "Generated set not found")


def assert_attempt_access(attempt_id: str, user: CurrentUser) -> dict:
    """A quiz attempt belongs to the student who took it (admins may audit)."""
    result = (
        get_supabase_admin()
        .table("student_quiz_attempts")
        .select("*")
        .eq("id", attempt_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")

    attempt = rows[0]
    if attempt["student_id"] != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return attempt


def assert_can_read_pyq_corpus(course_id: str, user: CurrentUser) -> None:
    """
    PYQ questions and style profiles are teacher/admin-only (PRD §14).
    Kept separate from `assert_course_staff` so the intent reads clearly at
    call sites and in an audit.
    """
    if user.role == "student":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The previous-year question corpus is not available to students",
        )
    assert_course_staff(course_id, user)
