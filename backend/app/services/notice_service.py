"""
Academix AI — Notice Board (PRD §11).

The in-app feed for institute- and course-level communication. Visibility
follows PRD §14 role-based isolation rather than showing every notice to
everyone:

  * `course_id` set        → only users enrolled in that course, plus admins.
  * `target_user_id` set   → only that person, plus admins (grades, personal
                             confirmations).
  * neither set            → institute-wide, filtered by `target_roles`.

Email delivery (PRD §11's second column) is queued through
`app/services/email_service.py`, which no-ops with a log line when no
transactional provider is configured — the in-app feed is the surface the
product actually depends on.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.database import get_supabase_admin
from app.dependencies import CurrentUser

logger = logging.getLogger(__name__)

# Feed page size ceiling — keeps a chatty course from returning thousands of rows.
MAX_LIMIT = 100


async def create_notice(
    posted_by: Optional[str],
    title: str,
    body: str,
    notice_type: str = "announcement",
    course_id: Optional[str] = None,
    target_roles: Optional[list[str]] = None,
    target_user_id: Optional[str] = None,
    send_email: bool = False,
) -> dict:
    """Insert a notice and optionally fan it out over email."""
    supabase = get_supabase_admin()

    record = {
        "author_id": posted_by,
        "title": title[:300],
        "body": body,
        "notice_type": notice_type,
        "course_id": course_id,
        "target_roles": target_roles or ["admin", "teacher", "student"],
        "target_user_id": target_user_id,
    }

    result = supabase.table("notices").insert(record).execute()
    notice = (result.data or [{}])[0]

    if send_email and notice:
        from app.services import email_service

        try:
            await email_service.deliver_notice(notice)
        except Exception as exc:  # notice delivery must never fail the action
            logger.warning("Email delivery for notice %s failed: %s", notice.get("id"), exc)

    return notice


async def create_system_notice(
    title: str,
    body: str,
    notice_type: str,
    course_id: Optional[str] = None,
    posted_by: Optional[str] = None,
    target_roles: Optional[list[str]] = None,
    target_user_id: Optional[str] = None,
    send_email: bool = False,
) -> Optional[dict]:
    """
    Notice raised by the platform itself (assignment posted, grade released,
    event cancelled…).

    Never raises: a notification failure must not roll back the action that
    triggered it. A teacher's assignment is created whether or not the
    accompanying notice lands.
    """
    try:
        return await create_notice(
            posted_by=posted_by,
            title=title,
            body=body,
            notice_type=notice_type,
            course_id=course_id,
            target_roles=target_roles,
            target_user_id=target_user_id,
            send_email=send_email,
        )
    except Exception as exc:
        logger.warning("Could not create %s notice %r: %s", notice_type, title, exc)
        return None


async def list_notices(
    user: CurrentUser,
    course_id: Optional[str] = None,
    notice_type: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    The notice feed this user is entitled to see.

    Scoping is done with an explicit `or_` filter rather than fetching
    everything and filtering in Python, so a student never receives another
    cohort's notices over the wire in the first place.
    """
    supabase = get_supabase_admin()
    limit = max(1, min(limit, MAX_LIMIT))

    query = supabase.table("notices").select(
        "*, profiles!notices_author_id_fkey(full_name, avatar_url), courses(name, code)",
        count="exact",
    )

    if course_id:
        query = query.eq("course_id", course_id)

    if user.role != "admin":
        visible_course_ids = [
            row["course_id"]
            for row in (
                supabase.table("enrollments")
                .select("course_id")
                .eq("user_id", user.id)
                .execute()
                .data
                or []
            )
        ]

        # Institute-wide notices addressed to this role, notices for a course
        # the user is enrolled in, and notices addressed to them personally.
        clauses = [
            f"and(course_id.is.null,target_user_id.is.null,target_roles.cs.[\"{user.role}\"])",
            f"target_user_id.eq.{user.id}",
        ]
        if visible_course_ids:
            joined = ",".join(visible_course_ids)
            clauses.append(f"and(course_id.in.({joined}),target_user_id.is.null)")

        query = query.or_(",".join(clauses))

    if notice_type:
        query = query.eq("notice_type", notice_type)

    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    notices = result.data or []
    total = result.count if result.count is not None else len(notices)

    read_ids = _read_ids(user.id, [n["id"] for n in notices])
    for notice in notices:
        notice["is_read"] = notice["id"] in read_ids
        author = notice.pop("profiles", None) or {}
        notice["author_name"] = author.get("full_name")
        notice["author_avatar"] = author.get("avatar_url")
        course = notice.pop("courses", None) or {}
        notice["course_name"] = course.get("name")
        notice["course_code"] = course.get("code")

    if unread_only:
        notices = [n for n in notices if not n["is_read"]]

    return {
        "notices": notices,
        "total": total,
        # Unread across the whole feed, not just this page — it drives the
        # sidebar badge, so a page-local count would be wrong.
        "unread_count": await get_unread_count(user),
    }


def _read_ids(user_id: str, notice_ids: list[str]) -> set[str]:
    if not notice_ids:
        return set()
    try:
        result = (
            get_supabase_admin()
            .table("notice_reads")
            .select("notice_id")
            .eq("user_id", user_id)
            .in_("notice_id", notice_ids)
            .execute()
        )
    except Exception as exc:
        logger.warning("Read-state lookup failed for %s: %s", user_id, exc)
        return set()
    return {row["notice_id"] for row in (result.data or [])}


async def mark_as_read(user_id: str, notice_ids: list[str]) -> int:
    """Record notices as read. Returns how many rows were written."""
    if not notice_ids:
        return 0
    records = [{"notice_id": nid, "user_id": user_id} for nid in dict.fromkeys(notice_ids)]
    result = (
        get_supabase_admin()
        .table("notice_reads")
        .upsert(records, on_conflict="notice_id,user_id")
        .execute()
    )
    return len(result.data or [])


async def mark_all_read(user: CurrentUser) -> int:
    """Mark every notice currently visible to this user as read."""
    feed = await list_notices(user, limit=MAX_LIMIT)
    unread = [n["id"] for n in feed["notices"] if not n["is_read"]]
    return await mark_as_read(user.id, unread)


async def get_unread_count(user: CurrentUser) -> int:
    """
    Unread notices for the sidebar badge.

    Counts visible ids minus read ids in two cheap queries rather than
    re-materialising the feed (which would recurse into list_notices).
    """
    supabase = get_supabase_admin()

    try:
        query = supabase.table("notices").select("id")

        if user.role != "admin":
            visible_course_ids = [
                row["course_id"]
                for row in (
                    supabase.table("enrollments")
                    .select("course_id")
                    .eq("user_id", user.id)
                    .execute()
                    .data
                    or []
                )
            ]
            clauses = [
                f"and(course_id.is.null,target_user_id.is.null,target_roles.cs.[\"{user.role}\"])",
                f"target_user_id.eq.{user.id}",
            ]
            if visible_course_ids:
                joined = ",".join(visible_course_ids)
                clauses.append(f"and(course_id.in.({joined}),target_user_id.is.null)")
            query = query.or_(",".join(clauses))

        visible = {row["id"] for row in (query.limit(500).execute().data or [])}
        if not visible:
            return 0

        read = {
            row["notice_id"]
            for row in (
                supabase.table("notice_reads")
                .select("notice_id")
                .eq("user_id", user.id)
                .execute()
                .data
                or []
            )
        }
        return len(visible - read)
    except Exception as exc:
        logger.warning("Unread count failed for %s: %s", user.id, exc)
        return 0


async def delete_notice(notice_id: str) -> None:
    get_supabase_admin().table("notices").delete().eq("id", notice_id).execute()
