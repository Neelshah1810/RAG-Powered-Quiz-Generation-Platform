"""
Academix AI — Auth endpoints.

Accounts are admin-provisioned; there is no public signup (PRD §9).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.dependencies import CurrentUser, get_current_user, require_role
from app.models.user import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    SignUpRequest,
    TokenResponse,
    UserResponse,
    UserUpdate,
)
from app.services import auth_service

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


@router.post("/login", response_model=LoginResponse)
async def login(data: LoginRequest):
    """Sign in with email and password."""
    return await auth_service.sign_in_user(data)


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    data: SignUpRequest,
    _: CurrentUser = Depends(require_role("admin")),
):
    """Provision a new account (admin only)."""
    return await auth_service.sign_up_user(data)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: RefreshRequest):
    """
    Exchange a refresh token for a new access token.

    Takes the token in the body, not the query string, so it stays out of
    server access logs and browser history.
    """
    return await auth_service.refresh_session(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Revoke the current session server-side."""
    if credentials and credentials.credentials:
        await auth_service.sign_out(credentials.credentials)


@router.get("/me", response_model=UserResponse)
async def get_my_profile(current_user: CurrentUser = Depends(get_current_user)):
    """The signed-in user's profile."""
    profile = await auth_service.get_user_profile(current_user.id)
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return profile


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    data: UserUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update your own profile. Role and email are not editable here."""
    return await auth_service.update_user_profile(
        current_user.id, data.model_dump(exclude_none=True)
    )
