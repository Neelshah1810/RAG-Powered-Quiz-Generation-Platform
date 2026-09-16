"""
Academix AI — Notice Board endpoints (PRD §11).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_supabase_admin
from app.dependencies import CurrentUser, get_current_user, require_role
from app.models.notice import (
    MarkReadRequest,
    NoticeCreate,
    NoticeListResponse,
    NoticeResponse,
)
from app.services import authz, notice_service

router = APIRouter()


@router.get("/", response_model=NoticeListResponse)
async def list_notices(
    course_id: Optional[str] = Query(None),
    notice_type: Optional[str] = Query(None),
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    The caller's notice feed.

    Scoped per PRD §14: institute-wide notices for their role, notices for
    courses they are enrolled in, and notices addressed to them personally.
    """
    if course_id:
        authz.assert_course_member(course_id, current_user)

    return await notice_service.list_notices(
        user=current_user,
        course_id=course_id,
        notice_type=notice_type,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=NoticeResponse, status_code=status.HTTP_201_CREATED)
async def create_notice(
    data: NoticeCreate,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """
    Post a notice.

    A course notice requires teaching rights on that course. Institute-wide
    notices are admin-only — a teacher should not be able to address the whole
    college.
    """
    if data.course_id:
        authz.assert_course_staff(data.course_id, current_user)
    elif current_user.role != "admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only an admin can post an institute-wide notice. Pick a course to "
            "post to your class instead.",
        )

    notice = await notice_service.create_notice(
        posted_by=current_user.id,
        title=data.title,
        body=data.body,
        notice_type=data.notice_type,
        course_id=data.course_id,
        target_roles=data.target_roles,
        send_email=data.send_email,
    )
    notice["author_name"] = current_user.full_name
    notice["is_read"] = True  # the author has, by definition, read it
    return notice


@router.get("/unread-count")
async def get_unread_count(current_user: CurrentUser = Depends(get_current_user)):
    """Unread count for the sidebar badge."""
    return {"unread_count": await notice_service.get_unread_count(current_user)}


@router.post("/mark-read")
async def mark_as_read(
    data: MarkReadRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Mark specific notices as read."""
    marked = await notice_service.mark_as_read(current_user.id, data.notice_ids)
    return {
        "marked": marked,
        "unread_count": await notice_service.get_unread_count(current_user),
    }


@router.post("/mark-all-read")
async def mark_all_as_read(current_user: CurrentUser = Depends(get_current_user)):
    """Mark everything currently visible to the caller as read."""
    marked = await notice_service.mark_all_read(current_user)
    return {"marked": marked, "unread_count": 0}


@router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notice(
    notice_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """Withdraw a notice. Teachers may only remove their own."""
    rows = (
        get_supabase_admin()
        .table("notices")
        .select("id, author_id, course_id")
        .eq("id", notice_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notice not found")

    notice = rows[0]
    if current_user.role != "admin" and notice.get("author_id") != current_user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can only delete notices you posted."
        )

    await notice_service.delete_notice(notice_id)
