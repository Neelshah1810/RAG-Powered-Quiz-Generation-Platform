"""
Academix AI — Group chat endpoints + WebSocket.

Writes go through REST (normal auth + authz); after each write the affected
members are notified over the WebSocket at /api/chat/ws.

WebSocket protocol (JSON text frames)
  client -> server   {"type": "auth", "token": "<supabase access token>"}  (first frame, within 10 s)
                     {"type": "ping"}
                     {"type": "typing", "group_id": "..."}
  server -> client   {"type": "ready", "user_id": "..."}
                     {"type": "pong"}
                     {"type": "message.new",     "group_id", "message"}
                     {"type": "message.updated", "group_id", "message"}
                     {"type": "group.changed",   "group_id"}   -> refetch list/detail
                     {"type": "group.removed",   "group_id"}   -> you are no longer a member
                     {"type": "typing", "group_id", "user_id", "name"}

The token travels in the first frame rather than the URL so it never lands in
proxy access logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials

from app.dependencies import CurrentUser, get_current_user
from app.models.chat import (
    ChatGroupCreate,
    ChatGroupUpdate,
    ChatMembersAdd,
    ChatMessageCreate,
    ChatReaction,
    ChatVote,
)
from app.services import chat_service
from app.services.chat_hub import hub

logger = logging.getLogger(__name__)
router = APIRouter()


async def _notify_message(event_type: str, message: dict) -> None:
    group_id = message["group_id"]
    recipients = await run_in_threadpool(chat_service.member_ids, group_id)
    await hub.publish(recipients, {"type": event_type, "group_id": group_id, "message": message})


async def _notify_group_changed(group_id: str, user_ids: list[str]) -> None:
    await hub.publish(user_ids, {"type": "group.changed", "group_id": group_id})


# ─────────────────────────────────────────────────────────────────────────────
# Directory
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/directory")
async def search_directory(
    q: str = Query("", max_length=100),
    course_id: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
):
    """People the caller may add to a group (teachers: their semester(s); admins: everyone)."""
    return await run_in_threadpool(chat_service.search_directory, user, q, course_id)


@router.get("/directory/courses")
async def directory_courses(user: CurrentUser = Depends(get_current_user)):
    """Courses whose whole roster the caller may add at once."""
    return await run_in_threadpool(chat_service.list_scope_courses, user)


# ─────────────────────────────────────────────────────────────────────────────
# Groups
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/groups")
async def list_groups(user: CurrentUser = Depends(get_current_user)):
    return await run_in_threadpool(chat_service.list_groups, user)


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(data: ChatGroupCreate, user: CurrentUser = Depends(get_current_user)):
    detail, recipients, system = await run_in_threadpool(chat_service.create_group, user, data)
    await _notify_group_changed(detail["id"], recipients)
    await _notify_message("message.new", system)
    return detail


@router.get("/groups/{group_id}")
async def get_group(group_id: str, user: CurrentUser = Depends(get_current_user)):
    return await run_in_threadpool(chat_service.get_group_detail, group_id, user)


@router.patch("/groups/{group_id}")
async def update_group(group_id: str, data: ChatGroupUpdate, user: CurrentUser = Depends(get_current_user)):
    detail, system = await run_in_threadpool(chat_service.update_group, group_id, user, data)
    recipients = await run_in_threadpool(chat_service.member_ids, group_id)
    await _notify_group_changed(group_id, recipients)
    if system:
        await _notify_message("message.new", system)
    return detail


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: str, user: CurrentUser = Depends(get_current_user)):
    recipients = await run_in_threadpool(chat_service.delete_group, group_id, user)
    await hub.publish(recipients, {"type": "group.removed", "group_id": group_id})


@router.post("/groups/{group_id}/members")
async def add_members(group_id: str, data: ChatMembersAdd, user: CurrentUser = Depends(get_current_user)):
    detail, added, system = await run_in_threadpool(chat_service.add_members, group_id, user, data.user_ids)
    if added:
        recipients = await run_in_threadpool(chat_service.member_ids, group_id)
        await _notify_group_changed(group_id, recipients)
    if system:
        await _notify_message("message.new", system)
    return detail


@router.delete("/groups/{group_id}/members/{member_id}")
async def remove_member(group_id: str, member_id: str, user: CurrentUser = Depends(get_current_user)):
    detail, system = await run_in_threadpool(chat_service.remove_member, group_id, user, member_id)
    await hub.publish([member_id], {"type": "group.removed", "group_id": group_id})
    recipients = await run_in_threadpool(chat_service.member_ids, group_id)
    await _notify_group_changed(group_id, recipients)
    await _notify_message("message.new", system)
    return detail or {"left": True}


@router.post("/groups/{group_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(group_id: str, user: CurrentUser = Depends(get_current_user)):
    await run_in_threadpool(chat_service.mark_read, group_id, user)


# ─────────────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/groups/{group_id}/messages")
async def list_messages(
    group_id: str,
    before: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
):
    return await run_in_threadpool(chat_service.list_messages, group_id, user, before, limit)


@router.post("/groups/{group_id}/messages", status_code=status.HTTP_201_CREATED)
async def post_message(group_id: str, data: ChatMessageCreate, user: CurrentUser = Depends(get_current_user)):
    message = await run_in_threadpool(chat_service.post_message, group_id, user, data)
    await _notify_message("message.new", message)
    return message


@router.post("/groups/{group_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    group_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    data = await file.read()
    return await run_in_threadpool(
        chat_service.upload_attachment, group_id, user, file.filename or "file", data, file.content_type
    )


@router.delete("/messages/{message_id}")
async def delete_message(message_id: str, user: CurrentUser = Depends(get_current_user)):
    message = await run_in_threadpool(chat_service.delete_message, message_id, user)
    await _notify_message("message.updated", message)
    return message


@router.put("/messages/{message_id}/reaction")
async def set_reaction(message_id: str, data: ChatReaction, user: CurrentUser = Depends(get_current_user)):
    message = await run_in_threadpool(chat_service.set_reaction, message_id, user, data.emoji)
    await _notify_message("message.updated", message)
    return message


@router.post("/messages/{message_id}/vote")
async def vote(message_id: str, data: ChatVote, user: CurrentUser = Depends(get_current_user)):
    message = await run_in_threadpool(chat_service.vote, message_id, user, data.option_ids)
    await _notify_message("message.updated", message)
    return message


@router.post("/messages/{message_id}/close-poll")
async def close_poll(message_id: str, user: CurrentUser = Depends(get_current_user)):
    message = await run_in_threadpool(chat_service.close_poll, message_id, user)
    await _notify_message("message.updated", message)
    return message


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket
# ─────────────────────────────────────────────────────────────────────────────

_MEMBERSHIP_TTL = 60.0


@router.websocket("/ws")
async def chat_socket(ws: WebSocket):
    await ws.accept()

    # 1. Authenticate with the first frame.
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        token = (json.loads(raw) or {}).get("token") or ""
        user = await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, HTTPException, Exception) as exc:
        logger.info("Chat socket auth failed: %s", getattr(exc, "detail", exc))
        try:
            await ws.close(code=4401, reason="Unauthorized")
        except Exception:
            pass
        return

    await hub.add(user.id, ws)
    await ws.send_text(json.dumps({"type": "ready", "user_id": user.id}))

    # Cache of group memberships for typing relays: group_id -> (is_member, checked_at)
    membership: dict[str, tuple[bool, float]] = {}

    async def is_member(group_id: str) -> bool:
        cached = membership.get(group_id)
        if cached and time.monotonic() - cached[1] < _MEMBERSHIP_TTL:
            return cached[0]
        ok = await run_in_threadpool(lambda: chat_service._get_membership(group_id, user.id) is not None)
        membership[group_id] = (ok, time.monotonic())
        return ok

    try:
        while True:
            raw = await ws.receive_text()
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            kind = frame.get("type") if isinstance(frame, dict) else None
            if kind == "ping":
                await ws.send_text('{"type":"pong"}')
            elif kind == "typing":
                group_id = str(frame.get("group_id") or "")
                if group_id and await is_member(group_id):
                    recipients = [u for u in await run_in_threadpool(chat_service.member_ids, group_id) if u != user.id]
                    await hub.publish(recipients, {
                        "type": "typing",
                        "group_id": group_id,
                        "user_id": user.id,
                        "name": user.full_name or user.email.split("@")[0],
                    })
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("Chat socket error for %s: %s", user.id, exc)
    finally:
        await hub.remove(user.id, ws)
