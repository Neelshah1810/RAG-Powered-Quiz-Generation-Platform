"""Academix AI — Scheduler schemas (PRD §10)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

EventType = Literal["lecture", "meeting", "exam", "assignment_due", "holiday", "other"]

# Google Calendar-style palette, one colour per event type (PRD §12.2).
EVENT_TYPE_COLORS: dict[str, str] = {
    "lecture": "#FBC02D",         # amber
    "meeting": "#4285F4",         # blue
    "exam": "#DB4437",            # red
    "assignment_due": "#F4B400",  # orange
    "holiday": "#0F9D58",         # green
    "other": "#9E9E9E",           # grey
}

# What each role may put on the calendar. Students get personal meetings and
# reminders only — they must not be able to post a lecture or an exam to a
# whole cohort's calendar.
ROLE_EVENT_TYPES: dict[str, set[str]] = {
    "admin": {"lecture", "meeting", "exam", "holiday", "other"},
    "teacher": {"lecture", "meeting", "exam", "holiday", "other"},
    "student": {"meeting", "other"},
}

# A single event longer than this is almost always a mistyped year.
MAX_EVENT_DURATION = timedelta(days=30)


class EventCreate(BaseModel):
    course_id: Optional[str] = None
    section_id: Optional[str] = None
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = None
    event_type: EventType
    start_at: datetime
    end_at: datetime
    color: Optional[str] = None
    location: Optional[str] = None
    # For a meeting: the person being met. For a lecture: the teacher taking it.
    invitee_id: Optional[str] = None
    # For a holiday: 'everyone', or a semester number as a string.
    semester: Optional[str] = None
    is_all_day: bool = False
    reminder_minutes: int = Field(default=30, ge=0, le=10080)

    @field_validator("event_type")
    @classmethod
    def _not_auto_generated(cls, value: str) -> str:
        # Due-date events are created by Classroom, never by hand — accepting
        # one here would let a user forge a deadline marker with no assignment.
        if value == "assignment_due":
            raise ValueError(
                "assignment_due events are created automatically from Classroom "
                "assignments and cannot be added directly"
            )
        return value

    @model_validator(mode="after")
    def _validate_window(self) -> "EventCreate":
        if self.end_at <= self.start_at:
            raise ValueError("The event must end after it starts")
        if self.end_at - self.start_at > MAX_EVENT_DURATION:
            raise ValueError("An event cannot span more than 30 days")
        return self


class EventUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    description: Optional[str] = None
    event_type: Optional[EventType] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    color: Optional[str] = None
    location: Optional[str] = None
    course_id: Optional[str] = None
    section_id: Optional[str] = None
    reminder_minutes: Optional[int] = Field(default=None, ge=0, le=10080)

    @model_validator(mode="after")
    def _validate_window(self) -> "EventUpdate":
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValueError("The event must end after it starts")
        if not self.model_dump(exclude_none=True):
            raise ValueError("Provide at least one field to update")
        return self


class EventResponse(BaseModel):
    id: str
    course_id: Optional[str] = None
    section_id: Optional[str] = None
    assignment_id: Optional[str] = None
    creator_id: Optional[str] = None
    invitee_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    event_type: str
    start_at: datetime
    end_at: datetime
    color: str = "#4285F4"
    location: Optional[str] = None
    semester: Optional[str] = None
    is_all_day: bool = False
    reminder_minutes: int = 30
    created_at: Optional[datetime] = None
    # Joined
    course_name: Optional[str] = None
    course_code: Optional[str] = None
    creator_name: Optional[str] = None
    # Whether the requesting user may edit or delete this event.
    can_edit: bool = False


class ConflictCheckRequest(BaseModel):
    start_at: datetime
    end_at: datetime
    course_id: Optional[str] = None
    section_id: Optional[str] = None
    exclude_event_id: Optional[str] = None


class ConflictWarning(BaseModel):
    has_conflict: bool
    conflicting_events: list[EventResponse] = Field(default_factory=list)
    message: Optional[str] = None
