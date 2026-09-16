"""
Academix AI — Scheduler endpoints (PRD §10).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUser, get_current_user
from app.models.scheduler import (
    ROLE_EVENT_TYPES,
    ConflictCheckRequest,
    ConflictWarning,
    EventCreate,
    EventResponse,
    EventUpdate,
)
from app.services import authz, notice_service, scheduler_service

router = APIRouter()


async def _decorate(events: list[dict], user: CurrentUser) -> list[dict]:
    """Tell the client which events it may edit, so the UI can hide the controls."""
    for event in events:
        event["can_edit"] = await scheduler_service.can_modify_event(event, user)
    return events


@router.get("/events", response_model=list[EventResponse])
async def list_events(
    start_date: Optional[str] = Query(None, description="ISO datetime, window start"),
    end_date: Optional[str] = Query(None, description="ISO datetime, window end"),
    course_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Events on the caller's calendar for a date window."""
    if course_id:
        authz.assert_course_member(course_id, current_user)

    events = await scheduler_service.list_events(
        user=current_user,
        start_date=start_date,
        end_date=end_date,
        course_id=course_id,
        event_type=event_type,
    )
    return await _decorate(events, current_user)


@router.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    data: EventCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Add an event.

    What each role may create is defined once in `ROLE_EVENT_TYPES`: students
    get personal meetings and reminders, staff get the full set. A
    course-scoped event additionally requires teaching rights on that course —
    otherwise an enrolled student could post an "exam" to their cohort's
    calendar.
    """
    allowed = ROLE_EVENT_TYPES.get(current_user.role, set())
    if data.event_type not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"As a {current_user.role} you can create: {', '.join(sorted(allowed))}.",
        )

    if data.course_id:
        authz.assert_course_staff(data.course_id, current_user)

    if data.event_type == "holiday" and current_user.role == "student":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only staff can declare a holiday."
        )

    event = await scheduler_service.create_event(
        created_by=current_user.id,
        title=data.title,
        event_type=data.event_type,
        start_at=data.start_at.isoformat(),
        end_at=data.end_at.isoformat(),
        course_id=data.course_id,
        section_id=data.section_id,
        description=data.description,
        color=data.color,
        location=data.location,
        invitee_id=data.invitee_id,
        semester=data.semester,
        is_all_day=data.is_all_day,
        reminder_minutes=data.reminder_minutes,
    )

    # A personal event needs no announcement; a shared one does.
    if data.course_id or data.event_type == "holiday":
        when = data.start_at.strftime("%d %b %Y at %H:%M")
        await notice_service.create_system_notice(
            title=f"{data.event_type.replace('_', ' ').capitalize()}: {data.title}",
            body=f"Scheduled for {when}."
            + (f" Location: {data.location}." if data.location else ""),
            notice_type="event",
            course_id=data.course_id,
            posted_by=current_user.id,
            send_email=True,
        )
    elif data.invitee_id and data.invitee_id != current_user.id:
        # Someone was invited to a one-to-one meeting — tell just them.
        when = data.start_at.strftime("%d %b %Y at %H:%M")
        await notice_service.create_system_notice(
            title=f"Meeting request: {data.title}",
            body=f"{current_user.full_name} scheduled a meeting with you on {when}.",
            notice_type="event",
            posted_by=current_user.id,
            target_user_id=data.invitee_id,
        )

    full = await scheduler_service.get_event(event["id"])
    return (await _decorate([full or event], current_user))[0]


@router.post("/events/check-conflicts", response_model=ConflictWarning)
async def check_conflicts(
    data: ConflictCheckRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Warn about overlapping events before one is saved (PRD §10).

    Takes the window in the request body — the previous version declared these
    as required query parameters, so the frontend's POST with a JSON body
    always failed validation.
    """
    if data.course_id:
        authz.assert_course_member(data.course_id, current_user)

    conflicts = await scheduler_service.check_conflicts(
        start_at=data.start_at.isoformat(),
        end_at=data.end_at.isoformat(),
        course_id=data.course_id,
        section_id=data.section_id,
        creator_id=None if data.course_id else current_user.id,
        exclude_event_id=data.exclude_event_id,
    )
    await _decorate(conflicts, current_user)

    if not conflicts:
        return ConflictWarning(has_conflict=False, conflicting_events=[])

    titles = ", ".join(c["title"] for c in conflicts[:3])
    more = f" and {len(conflicts) - 3} more" if len(conflicts) > 3 else ""
    return ConflictWarning(
        has_conflict=True,
        conflicting_events=conflicts,
        message=f"This overlaps with: {titles}{more}.",
    )


@router.get("/events/upcoming", response_model=list[EventResponse])
async def upcoming(
    limit: int = Query(5, ge=1, le=20),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The next few events, for the dashboard cards."""
    events = await scheduler_service.upcoming_events(current_user, limit)
    return await _decorate(events, current_user)


@router.get("/events/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    event = await scheduler_service.get_event(event_id)
    if not event:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    # A course event is only visible to that course's members.
    if event.get("course_id"):
        authz.assert_course_member(event["course_id"], current_user)

    return (await _decorate([event], current_user))[0]


@router.patch("/events/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: str,
    data: EventUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Edit an event.

    Permission is per-event, not per-role: the creator, a teacher of the
    event's course, or an admin. The previous version let *any* teacher edit
    *any* event in the institute.
    """
    event = await scheduler_service.get_event(event_id)
    if not event:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    if not await scheduler_service.can_modify_event(event, current_user):
        detail = (
            "Assignment due dates are managed from the assignment itself."
            if event.get("assignment_id")
            else "You can only edit events you created, or events on a course you teach."
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail)

    updates = data.model_dump(exclude_none=True)

    # Validate the resulting window, not just the supplied half.
    new_start = data.start_at or event["start_at"]
    new_end = data.end_at or event["end_at"]
    if str(new_end) <= str(new_start):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The event must end after it starts."
        )

    if data.course_id:
        authz.assert_course_staff(data.course_id, current_user)

    updated = await scheduler_service.update_event(event_id, updates)

    if updated.get("course_id"):
        await notice_service.create_system_notice(
            title=f"Event updated: {updated.get('title')}",
            body="An event on your course calendar has changed. Check the Scheduler.",
            notice_type="event",
            course_id=updated["course_id"],
            posted_by=current_user.id,
            send_email=True,
        )

    return (await _decorate([updated], current_user))[0]


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Cancel an event and notify the affected course (PRD §10, §11)."""
    event = await scheduler_service.get_event(event_id)
    if not event:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    if not await scheduler_service.can_modify_event(event, current_user):
        detail = (
            "Assignment due dates disappear when the assignment is deleted."
            if event.get("assignment_id")
            else "You can only delete events you created, or events on a course you teach."
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail)

    # Announce before deleting, while the title is still readable.
    if event.get("course_id"):
        await notice_service.create_system_notice(
            title=f"Event cancelled: {event.get('title')}",
            body="A scheduled event has been cancelled.",
            notice_type="event",
            course_id=event["course_id"],
            posted_by=current_user.id,
            send_email=True,
        )

    await scheduler_service.delete_event(event_id)
