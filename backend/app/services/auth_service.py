"""
Academix AI — Authentication (Supabase Auth).

Accounts are admin-provisioned (PRD §9: "Admin/teacher enrolls students by
roster assignment … rather than a public join-code flow"), so there is no
self-service signup. Password hashing, token issue and refresh are Supabase's
responsibility; this module wraps them and keeps `profiles` in step.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status

from app.database import get_supabase, get_supabase_admin
from app.models.user import LoginRequest, SignUpRequest

logger = logging.getLogger(__name__)

VALID_ROLES = ("admin", "teacher", "student")
MIN_PASSWORD_LENGTH = 8


async def sign_up_user(data: SignUpRequest) -> dict:
    """
    Provision an account (admin action).

    The `handle_new_user` trigger creates the matching `profiles` row from the
    user metadata; this then fills in the fields the trigger does not carry.
    """
    if data.role not in VALID_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Role must be one of {', '.join(VALID_ROLES)}",
        )
    if len(data.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )

    supabase = get_supabase_admin()
    email = data.email.strip().lower()

    existing = supabase.table("profiles").select("id").eq("email", email).limit(1).execute()
    if existing.data:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"An account already exists for {email}",
        )

    try:
        created = supabase.auth.admin.create_user(
            {
                "email": email,
                "password": data.password,
                # Admin-provisioned accounts skip the confirmation email; the
                # admin is vouching for the address.
                "email_confirm": True,
                "user_metadata": {
                    "full_name": data.full_name.strip(),
                    "role": data.role,
                    "department": (data.department or "").strip() or None,
                },
            }
        )
    except Exception as exc:
        message = str(exc)
        if "already been registered" in message or "already exists" in message:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"An account already exists for {email}"
            ) from exc
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Could not create the account: {message}"
        ) from exc

    if not created or not created.user:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Supabase accepted the request but returned no user",
        )

    user_id = str(created.user.id)

    # Upsert rather than update: if the trigger is missing on a fresh project,
    # this still produces a usable profile instead of a login that 403s.
    profile = {
        "id": user_id,
        "email": email,
        "full_name": data.full_name.strip(),
        "role": data.role,
        "department": (data.department or "").strip() or None,
        "phone": (data.phone or "").strip() or None,
    }
    try:
        result = supabase.table("profiles").upsert(profile, on_conflict="id").execute()
        return (result.data or [profile])[0]
    except Exception as exc:
        # The auth user now exists without a profile, which would leave the
        # account unusable. Roll it back so the admin can retry cleanly.
        logger.error("Profile creation failed for %s; removing auth user: %s", email, exc)
        try:
            supabase.auth.admin.delete_user(user_id)
        except Exception:
            logger.exception("Could not roll back orphaned auth user %s", user_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Account created but its profile could not be saved: {exc}",
        ) from exc


async def sign_in_user(data: LoginRequest) -> dict:
    """Exchange email + password for an access/refresh token pair."""
    supabase = get_supabase()

    try:
        session_response = supabase.auth.sign_in_with_password(
            {"email": data.email.strip().lower(), "password": data.password}
        )
    except Exception as exc:
        # Never echo the provider's message back: it distinguishes "no such
        # user" from "wrong password", which enables account enumeration.
        logger.info("Failed sign-in for %s: %s", data.email, exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password"
        ) from exc

    session = getattr(session_response, "session", None)
    user = getattr(session_response, "user", None)
    if not session or not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    profile = await get_user_profile(str(user.id))
    if not profile:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This account has no profile on the platform. Ask an administrator "
            "to provision it.",
        )

    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_in": getattr(session, "expires_in", None),
        "user": profile,
    }


async def refresh_session(refresh_token: str) -> dict:
    try:
        result = get_supabase().auth.refresh_session(refresh_token)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Refresh token is invalid or expired"
        ) from exc

    session = getattr(result, "session", None)
    if not session:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Refresh token is invalid or expired"
        )

    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_in": getattr(session, "expires_in", None),
    }


async def sign_out(access_token: str) -> None:
    """Revoke a session server-side. Best effort — the client clears its own."""
    try:
        get_supabase_admin().auth.admin.sign_out(access_token)
    except Exception as exc:
        logger.debug("Server-side sign-out was a no-op: %s", exc)


async def get_user_profile(user_id: str) -> Optional[dict]:
    result = (
        get_supabase_admin()
        .table("profiles")
        .select("*")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


async def update_user_profile(user_id: str, updates: dict) -> dict:
    """
    Update a user's own profile.

    Role and email are excluded on purpose: changing your own role would be a
    privilege-escalation path, and email is Supabase Auth's identifier and must
    be changed through it.
    """
    editable = {"full_name", "department", "phone", "avatar_url"}
    clean = {k: v for k, v in updates.items() if k in editable and v is not None}

    if not clean:
        return await get_user_profile(user_id) or {}

    result = (
        get_supabase_admin().table("profiles").update(clean).eq("id", user_id).execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return result.data[0]


async def set_user_role(user_id: str, role: str) -> dict:
    """
    Change a user's role (admin action).

    Updates both `profiles.role` and the auth user metadata, so a later
    trigger-driven upsert cannot resurrect the old value.
    """
    if role not in VALID_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Role must be one of {', '.join(VALID_ROLES)}"
        )

    supabase = get_supabase_admin()
    result = supabase.table("profiles").update({"role": role}).eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    try:
        supabase.auth.admin.update_user_by_id(user_id, {"user_metadata": {"role": role}})
    except Exception as exc:
        logger.warning("Could not sync role metadata for %s: %s", user_id, exc)

    # Demoting a teacher would leave them holding teacher enrollments — and with
    # them Paper Style access on those courses, which PRD §14 forbids.
    if role == "student":
        supabase.table("enrollments").update({"role": "student"}).eq("user_id", user_id).eq(
            "role", "teacher"
        ).execute()

    return result.data[0]


async def set_user_password(user_id: str, password: str) -> None:
    """Reset a user's password (admin action)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    try:
        get_supabase_admin().auth.admin.update_user_by_id(user_id, {"password": password})
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Could not update the password: {exc}"
        ) from exc


async def delete_user(user_id: str) -> None:
    """
    Delete an account.

    Removing the auth user cascades to `profiles` and from there to every
    dependent row via the schema's ON DELETE CASCADE definitions.
    """
    supabase = get_supabase_admin()
    try:
        supabase.auth.admin.delete_user(user_id)
    except Exception as exc:
        message = str(exc)
        if "not found" in message.lower():
            # No auth user, but a stray profile may remain — clean that up.
            supabase.table("profiles").delete().eq("id", user_id).execute()
            return
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Could not delete the account: {message}"
        ) from exc
