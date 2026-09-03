"""
Academix AI — Scheduler (PRD §10, native calendar).

Event visibility follows PRD §14 isolation: a student sees institute-wide
events, events for courses they are enrolled in, and events they created or
were invited to — not every event in the institute.

Also implements the conflict detection PRD §10 asks for ("warns a teacher if a
new event overlaps another one they've scheduled for the same section") and
keeps assignment due dates in step with Classroom.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.database import get_supabase_admin
from app.dependencies import CurrentUser
from app.models.scheduler import EVENT_TYPE_COLORS

logger = logging.getLogger(__name__)

_JOIN = "*, courses(name, code), profiles!calendar_events_creator_id_fkey(full_name)"

# How long a due-date marker occupies on the grid. It ends on the deadline,
# so the block visually leads up to the moment the work is due.
_DUE_MARKER_WINDOW = timedelta(minutes=30)


def _flatten(event: dict) -> dict:
    course = event.pop("courses", None) or {}
    creator = event.pop("profiles!calendar_events_creator_id_fkey", None)
    if creator is None:
        creator = event.pop("profiles", None) or {}
    event["course_name"] = course.get("name")
    event["course_code"] = course.get("code")
    event["creator_name"] = (creator or {}).get("full_name")
    return event


async def create_event(
    created_by: str,
    title: str,
    event_type: str,
    start_at: str,
    end_at: str,
    course_id: Optional[str] = None,
    section_id: Optional[str] = None,
    description: Optional[str] = None,
    color: Optional[str] = None,
    location: Optional[str] = None,
    invitee_id: Optional[str] = None,
    semester: Optional[str] = None,
    is_all_day: bool = False,
    reminder_minutes: int = 30,
    assignment_id: Optional[str] = None,
) -> dict:
    record = {
        "creator_id": created_by,
        "title": title,
        "event_type": event_type,
        "start_at": start_at,
        "end_at": end_at,
        "course_id": course_id,
        "section_id": section_id,
        "description": description,
        "color": color or EVENT_TYPE_COLORS.get(event_type, "#4285F4"),
        "location": location,
        "invitee_id": invitee_id,
        "semester": semester,
        "is_all_day": is_all_day,
        "reminder_minutes": reminder_minutes,
        "assignment_id": assignment_id,
    }
    result = get_supabase_admin().table("calendar_events").insert(record).execute()
    return (result.data or [{}])[0]


async def list_events(
    user: CurrentUser,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    course_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> list[dict]:
    """
    Events on this user's calendar for a date window.

    The window test is an *overlap* test, not `start_at BETWEEN …`: a lecture
    that begins on 31 January and ends on 1 February must appear in both
    months' grids. The previous implementation filtered `start_at >= from` AND
    `end_at <= to`, which dropped any event straddling a boundary.
    """
    supabase = get_supabase_admin()
    query = supabase.table("calendar_events").select(_JOIN)

    if start_date:
        query = query.gte("end_at", start_date)
    if end_date:
        query = query.lte("start_at", end_date)
    if course_id:
        query = query.eq("course_id", course_id)
    if event_type:
        query = query.eq("event_type", event_type)

    if user.role != "admin":
        enrolled = [
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
            "course_id.is.null",             # institute-wide (holidays, notices)
            f"creator_id.eq.{user.id}",       # events they created
            f"invitee_id.eq.{user.id}",       # meetings they were invited to
        ]
        if enrolled:
            clauses.append(f"course_id.in.({','.join(enrolled)})")
        query = query.or_(",".join(clauses))

    result = query.order("start_at").execute()
    return [_flatten(row) for row in (result.data or [])]


async def get_event(event_id: str) -> Optional[dict]:
    result = (
        get_supabase_admin()
        .table("calendar_events")
        .select(_JOIN)
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return _flatten(rows[0]) if rows else None


async def can_modify_event(event: dict, user: CurrentUser) -> bool:
    """
    Who may edit or delete an event.

    Admins anything; the creator their own; a course teacher anything on their
    course. Auto-generated assignment due dates are excluded — they are owned
    by the assignment and change when it does.
    """
    if event.get("assignment_id"):
        return False
    if user.role == "admin":
        return True
    if event.get("creator_id") == user.id:
        return True
    if event.get("course_id"):
        from app.services import authz

        return authz.is_course_teacher(event["course_id"], user)
    return False


async def update_event(event_id: str, updates: dict) -> dict:
    clean: dict = {}
    for key, value in updates.items():
        if value is None:
            continue
        clean[key] = value.isoformat() if isinstance(value, datetime) else value

    if not clean:
        return await get_event(event_id) or {}

    # Keep the colour consistent when the type changes and no colour was given.
    if "event_type" in clean and "color" not in clean:
        clean["color"] = EVENT_TYPE_COLORS.get(clean["event_type"], "#4285F4")

    get_supabase_admin().table("calendar_events").update(clean).eq("id", event_id).execute()
    return await get_event(event_id) or {}


async def delete_event(event_id: str) -> None:
    get_supabase_admin().table("calendar_events").delete().eq("id", event_id).execute()


async def check_conflicts(
    start_at: str,
    end_at: str,
    course_id: Optional[str] = None,
    section_id: Optional[str] = None,
    creator_id: Optional[str] = None,
    exclude_event_id: Optional[str] = None,
) -> list[dict]:
    """
    Events overlapping the proposed window (PRD §10 conflict detection).

    Two intervals overlap when `existing.start < new.end AND existing.end >
    new.start`. Scoped to the same course/section where given, otherwise to the
    same creator — a teacher double-booking themselves across two courses is
    still a clash worth warning about.
    """
    supabase = get_supabase_admin()

    query = (
        supabase.table("calendar_events")
        .select(_JOIN)
        .lt("start_at", end_at)
        .gt("end_at", start_at)
    )

    if course_id:
        query = query.eq("course_id", course_id)
        if section_id:
            query = query.eq("section_id", section_id)
    elif creator_id:
        query = query.eq("creator_id", creator_id)

    if exclude_event_id:
        query = query.neq("id", exclude_event_id)

    # A due-date marker is a milestone, not an occupied room; flagging it as a
    # clash would make the warning useless.
    query = query.neq("event_type", "assignment_due")

    result = query.execute()
    return [_flatten(row) for row in (result.data or [])]


async def sync_assignment_due_event(
    assignment: dict,
    created_by: str,
) -> Optional[dict]:
    """
    Create or update the calendar entry for an assignment's due date
    (PRD §10: "Assignment Due Date … auto-populated from Classroom assignments").

    The unique index on `calendar_events.assignment_id` makes this an upsert,
    so editing an assignment's due date moves the existing entry instead of
    leaving a stale duplicate behind — the previous implementation inserted a
    fresh event on every save.
    """
    supabase = get_supabase_admin()
    assignment_id = assignment.get("id")
    due_at = assignment.get("due_at")

    if not assignment_id:
        return None

    if not due_at:
        # The due date was cleared: remove the marker rather than orphan it.
        supabase.table("calendar_events").delete().eq("assignment_id", assignment_id).execute()
        return None

    if isinstance(due_at, datetime):
        starts = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
    else:
        try:
            parsed = datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
            starts = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            logger.warning("Assignment %s has an unparseable due_at %r", assignment_id, due_at)
            return None

    # `calendar_events` enforces end_at > start_at, so a deadline cannot be a
    # zero-length instant. Render it as a short window ending on the deadline,
    # which is also how it reads on the calendar grid.
    ends = starts
    starts = ends - _DUE_MARKER_WINDOW

    record = {
        "assignment_id": assignment_id,
        "course_id": assignment.get("course_id"),
        "creator_id": created_by,
        "title": f"Due: {assignment.get('title', 'Assignment')}",
        "description": f"Assignment worth {assignment.get('max_points', 0)} points.",
        "event_type": "assignment_due",
        "start_at": starts.isoformat(),
        "end_at": ends.isoformat(),
        "color": EVENT_TYPE_COLORS["assignment_due"],
        "is_all_day": False,
        "reminder_minutes": 1440,  # a day's notice on a deadline
    }

    try:
        result = (
            supabase.table("calendar_events")
            .upsert(record, on_conflict="assignment_id")
            .execute()
        )
        return (result.data or [None])[0]
    except Exception as exc:
        logger.warning(
            "Could not sync due-date event for assignment %s: %s", assignment_id, exc
        )
        return None


async def upcoming_events(user: CurrentUser, limit: int = 5) -> list[dict]:
    """The next few events on this user's calendar, for the dashboard."""
    now = datetime.now(timezone.utc).isoformat()
    events = await list_events(user, start_date=now)
    return events[:limit]


async def events_today(user: CurrentUser) -> list[dict]:
    """Today's events (institute-local == UTC here), for the teacher dashboard."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
    return await list_events(user, start_date=start, end_date=end)
