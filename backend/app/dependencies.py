"""
Academix AI — Request-scoped dependencies.

Validates the Supabase access token and loads the caller's profile, then
exposes role gates for routers to depend on.

Token verification is done **locally** against SUPABASE_JWT_SECRET. The
previous implementation called `supabase.auth.get_user(token)` first, which
added a network round-trip to Supabase on every single request — that is the
difference between a ~1 ms and a ~150 ms floor on every endpoint. The remote
check is kept only as a fallback for projects that have rotated to asymmetric
signing keys, where the shared HS256 secret no longer verifies anything.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_supabase_admin

logger = logging.getLogger(__name__)

# auto_error=False so a missing header produces our own 401 with a useful
# message rather than FastAPI's bare "Not authenticated".
security = HTTPBearer(auto_error=False)

ROLES = ("admin", "teacher", "student")


class CurrentUser(BaseModel):
    """The authenticated caller."""

    id: str
    email: str
    role: str  # 'admin' | 'teacher' | 'student'
    full_name: Optional[str] = None
    department: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_staff(self) -> bool:
        return self.role in ("admin", "teacher")


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_id_from_token(token: str) -> str:
    """Verify the access token and return its subject (the auth user id)."""
    settings = get_settings()

    try:
        claims = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            # Supabase stamps aud="authenticated"; accept it explicitly rather
            # than switching audience verification off wholesale.
            audience="authenticated",
            options={"verify_aud": True},
        )
        subject = claims.get("sub")
        if subject:
            return str(subject)
        raise _unauthorised("Access token has no subject claim")
    except JWTError as local_error:
        # Either the token is bad, or this project signs with an asymmetric key
        # and the HS256 secret cannot verify it. Ask Supabase to arbitrate.
        try:
            response = get_supabase_admin().auth.get_user(token)
        except Exception:
            raise _unauthorised(f"Invalid or expired access token: {local_error}") from local_error

        if response and response.user:
            return str(response.user.id)
        raise _unauthorised(f"Invalid or expired access token: {local_error}") from local_error


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> CurrentUser:
    """Resolve the caller from the Authorization header."""
    if credentials is None or not credentials.credentials:
        raise _unauthorised("Missing bearer token")

    user_id = _user_id_from_token(credentials.credentials)

    try:
        result = (
            get_supabase_admin()
            .table("profiles")
            .select("id, email, full_name, role, department")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("Profile lookup failed for %s", user_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Could not reach the user directory: {exc}",
        ) from exc

    rows = result.data or []
    if not rows:
        # The auth user exists but has no profile row — the signup trigger
        # never fired, or the profile was deleted out from under it.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Your account has no profile on this institute's platform. "
            "Ask an administrator to provision it.",
        )

    profile = rows[0]
    if profile.get("role") not in ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Account has an unrecognised role: {profile.get('role')!r}",
        )

    return CurrentUser(
        id=profile["id"],
        email=profile["email"],
        role=profile["role"],
        full_name=profile.get("full_name"),
        department=profile.get("department"),
    )


def require_role(*allowed_roles: str):
    """
    Build a dependency that admits only the listed roles.

        @router.post("/courses")
        async def create(user: CurrentUser = Depends(require_role("admin"))):
            ...

    This is a coarse gate on *who may call an endpoint at all*. Per-resource
    rules ("is this teacher on this course?") live in app/services/authz.py and
    must still be applied inside the handler.
    """
    unknown = set(allowed_roles) - set(ROLES)
    if unknown:  # a wiring mistake, worth failing at import time
        raise ValueError(f"require_role() got unknown role(s): {sorted(unknown)}")

    async def role_checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action requires the role: {', '.join(allowed_roles)}. "
                    f"You are signed in as {current_user.role}."
                ),
            )
        return current_user

    return role_checker
