"""
Academix AI — User management (admin), plus the staff directory.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_supabase_admin
from app.dependencies import CurrentUser, get_current_user, require_role
from app.models.user import (
    PasswordResetRequest,
    UserResponse,
    UserRoleUpdate,
    UserStats,
)
from app.services import auth_service

router = APIRouter()


@router.get("/staff", response_model=list[UserResponse])
async def list_staff(_: CurrentUser = Depends(get_current_user)):
    """
    Teachers and admins, for the "meet with" and "lecture by" pickers.

    Readable by any signed-in user: a student booking a meeting needs to pick a
    teacher. Only name, role and department are exposed — never phone numbers.
    """
    result = (
        get_supabase_admin()
        .table("profiles")
        .select("id, email, full_name, role, department, avatar_url")
        .in_("role", ["admin", "teacher"])
        .order("full_name")
        .execute()
    )
    return result.data or []


@router.get("/", response_model=list[UserResponse])
async def list_users(
    role: Optional[str] = Query(None, description="admin | teacher | student"),
    search: Optional[str] = Query(None, description="Match on name or email"),
    limit: int = Query(200, ge=1, le=500),
    _: CurrentUser = Depends(require_role("admin")),
):
    """List accounts (admin only)."""
    query = get_supabase_admin().table("profiles").select("*").order("full_name")

    if role:
        if role not in ("admin", "teacher", "student"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown role {role!r}")
        query = query.eq("role", role)

    if search:
        # Escape PostgREST's `or` delimiters so a search for "a,b" cannot break
        # out of the filter expression.
        needle = search.replace(",", " ").replace("(", " ").replace(")", " ").strip()
        if needle:
            query = query.or_(f"full_name.ilike.%{needle}%,email.ilike.%{needle}%")

    return query.limit(limit).execute().data or []


@router.get("/stats/summary", response_model=UserStats)
async def get_user_stats(_: CurrentUser = Depends(require_role("admin"))):
    """Account counts by role, for the admin dashboard."""
    result = (
        get_supabase_admin().table("profiles").select("role").limit(5000).execute()
    )
    roles = [row["role"] for row in (result.data or [])]
    return UserStats(
        total=len(roles),
        admins=roles.count("admin"),
        teachers=roles.count("teacher"),
        students=roles.count("student"),
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    _: CurrentUser = Depends(require_role("admin")),
):
    profile = await auth_service.get_user_profile(user_id)
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return profile


@router.patch("/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: str,
    data: UserRoleUpdate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """
    Change a user's role.

    An admin cannot demote themselves — doing so would immediately revoke the
    access needed to undo it, and could leave the institute with no admin.
    """
    if user_id == current_user.id and data.role != "admin":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "You cannot change your own role. Ask another admin to do it.",
        )
    return await auth_service.set_user_role(user_id, data.role)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_user_password(
    user_id: str,
    data: PasswordResetRequest,
    _: CurrentUser = Depends(require_role("admin")),
):
    """Set a user's password (admin-assisted reset)."""
    await auth_service.set_user_password(user_id, data.password)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """
    Delete an account and everything owned by it.

    Refused for your own account, and refused if it would remove the last
    admin — leaving the institute with no way in.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You cannot delete your own account"
        )

    target = await auth_service.get_user_profile(user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if target["role"] == "admin":
        remaining = (
            get_supabase_admin()
            .table("profiles")
            .select("id", count="exact")
            .eq("role", "admin")
            .execute()
        )
        if (remaining.count or 0) <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This is the only admin account. Promote another user first.",
            )

    await auth_service.delete_user(user_id)


@router.get("/{user_id}/courses")
async def get_user_courses(
    user_id: str,
    _: CurrentUser = Depends(require_role("admin")),
):
    """A user's enrollments, so an admin can audit access before changing a role."""
    result = (
        get_supabase_admin()
        .table("enrollments")
        .select("*, courses(id, name, code, semester)")
        .eq("user_id", user_id)
        .execute()
    )
    enrollments = []
    for row in (result.data or []):
        course = row.pop("courses", None) or {}
        enrollments.append(
            {
                "enrollment_id": row["id"],
                "course_id": course.get("id"),
                "course_name": course.get("name"),
                "course_code": course.get("code"),
                "semester": course.get("semester"),
                "role": row["role"],
                "enrolled_at": row.get("enrolled_at"),
            }
        )
    return enrollments
