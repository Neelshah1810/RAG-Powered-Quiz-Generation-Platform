"""
Academix AI — Group chat (Teams/WhatsApp-style).

Rules enforced here (the backend is the only DB client, so this is the whole
security boundary for chat):

  * Groups are created by teachers and admins only. Students never pick who
    they talk to: they see exactly the groups they were added to.
  * Directory isolation — a teacher can find and add only people enrolled in
    courses of the semester(s) they teach (plus their own courses when a course
    has no semester). Admins can add anyone. Students cannot search at all.
  * Group roles: teachers/admins join as group 'admin', students as 'member'.
  * Posting policy per group: 'admins' (announcement channel — students read,
    react and vote) or 'everyone'.
  * Every member can react and vote; only the sender or a group admin can
    delete a message; only group admins can mark messages important.

All functions are synchronous (supabase-py is sync); the router runs them in a
thread pool and then publishes the returned events over the WebSocket hub.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import HTTPException, status

from app.config import get_settings
from app.database import get_supabase_admin
from app.dependencies import CurrentUser
from app.models.chat import (
    ChatGroupCreate,
    ChatGroupUpdate,
    ChatMessageCreate,
)
from app.services import storage_service
from app.services.authz import is_course_teacher
from app.utils.helpers import generate_course_color

logger = logging.getLogger(__name__)

_IN_CHUNK = 100  # keep PostgREST `in.(...)` URLs well under proxy limits
STAFF_ROLES = ("teacher", "admin")


def _sb():
    return get_supabase_admin()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunks(items: list[str], size: int = _IN_CHUNK) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _select_in(table: str, columns: str, column: str, values: Iterable[str]) -> list[dict]:
    values = [v for v in dict.fromkeys(values) if v]
    rows: list[dict] = []
    for chunk in _chunks(values):
        rows += _sb().table(table).select(columns).in_(column, chunk).execute().data or []
    return rows


def _not_found(what: str = "Chat group") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


# ─────────────────────────────────────────────────────────────────────────────
# Membership & permission helpers
# ─────────────────────────────────────────────────────────────────────────────


def _get_group(group_id: str) -> dict:
    rows = _sb().table("chat_groups").select("*").eq("id", group_id).limit(1).execute().data or []
    if not rows:
        raise _not_found()
    return rows[0]


def _get_membership(group_id: str, user_id: str) -> Optional[dict]:
    rows = (
        _sb().table("chat_members").select("*")
        .eq("group_id", group_id).eq("user_id", user_id).limit(1).execute().data
        or []
    )
    return rows[0] if rows else None


def assert_member(group_id: str, user: CurrentUser) -> tuple[dict, dict]:
    """The caller must belong to the group. 404 otherwise (don't leak existence)."""
    try:
        uuid.UUID(str(group_id))
    except ValueError:
        raise _not_found()
    membership = _get_membership(group_id, user.id)
    if membership is None:
        raise _not_found()
    return _get_group(group_id), membership


def _is_group_admin(membership: dict) -> bool:
    return membership.get("role") == "admin"


def assert_group_admin(group_id: str, user: CurrentUser) -> tuple[dict, dict]:
    group, membership = assert_member(group_id, user)
    if not _is_group_admin(membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only group admins can do that.")
    return group, membership


def _can_post(group: dict, membership: dict) -> bool:
    return _is_group_admin(membership) or group.get("post_policy") == "everyone"


def member_ids(group_id: str) -> list[str]:
    rows = _sb().table("chat_members").select("user_id").eq("group_id", group_id).execute().data or []
    return [r["user_id"] for r in rows]


def _group_role_for(platform_role: str) -> str:
    return "admin" if platform_role in STAFF_ROLES else "member"


# ─────────────────────────────────────────────────────────────────────────────
# Directory (who may a teacher add?)
# ─────────────────────────────────────────────────────────────────────────────


def _scope_course_ids(user: CurrentUser) -> Optional[list[str]]:
    """
    Course ids whose roster the user may reach. None means "everyone" (admin).

    A teacher's scope is every course in the semester(s) they teach, plus their
    own courses (covers courses with no semester set).
    """
    if user.role == "admin":
        return None
    if user.role != "teacher":
        return []

    taught = [
        r["course_id"]
        for r in _sb().table("enrollments").select("course_id")
        .eq("user_id", user.id).eq("role", "teacher").execute().data or []
    ]
    if not taught:
        return []

    semesters = {
        c["semester"]
        for c in _select_in("courses", "id, semester", "id", taught)
        if c.get("semester") is not None
    }
    scope = set(taught)
    if semesters:
        same_sem = (
            _sb().table("courses").select("id").in_("semester", list(semesters)).execute().data or []
        )
        scope.update(c["id"] for c in same_sem)
    return list(scope)


def _scope_user_ids(user: CurrentUser) -> Optional[set[str]]:
    course_ids = _scope_course_ids(user)
    if course_ids is None:
        return None
    if not course_ids:
        return set()
    rows = _select_in("enrollments", "user_id, course_id", "course_id", course_ids)
    return {r["user_id"] for r in rows}


def _assert_addable(user: CurrentUser, user_ids: Iterable[str]) -> list[str]:
    """Validate that every id exists and is inside the caller's directory scope."""
    wanted = [u for u in dict.fromkeys(user_ids) if u and u != user.id]
    if not wanted:
        return []
    for uid in wanted:
        try:
            uuid.UUID(uid)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid user id: {uid!r}")

    existing = {p["id"] for p in _select_in("profiles", "id", "id", wanted)}
    missing = [u for u in wanted if u not in existing]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown user(s): {', '.join(missing[:5])}")

    scope = _scope_user_ids(user)
    if scope is not None:
        outside = [u for u in wanted if u not in scope]
        if outside:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can only add people enrolled in courses of the semester(s) you teach.",
            )
    return wanted


def search_directory(user: CurrentUser, q: str = "", course_id: Optional[str] = None) -> list[dict]:
    """People the caller may add to a group, optionally narrowed to one course."""
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only teachers and admins can add people to chats.")

    scope_courses = _scope_course_ids(user)
    if course_id:
        if scope_courses is not None and course_id not in scope_courses:
            raise _not_found("Course")
        scope_courses = [course_id]

    courses_by_user: dict[str, list[str]] = {}
    if scope_courses is None:
        profiles = _sb().table("profiles").select("id, full_name, email, role").limit(5000).execute().data or []
    else:
        enrollments = _select_in("enrollments", "user_id, course_id", "course_id", scope_courses)
        codes = {c["id"]: c["code"] for c in _select_in("courses", "id, code", "id", scope_courses)}
        for e in enrollments:
            courses_by_user.setdefault(e["user_id"], []).append(codes.get(e["course_id"], ""))
        profiles = _select_in("profiles", "id, full_name, email, role", "id", list(courses_by_user))

    needle = (q or "").strip().lower()
    results = []
    for p in profiles:
        if p["id"] == user.id:
            continue
        if needle and needle not in (p.get("full_name") or "").lower() and needle not in (p.get("email") or "").lower():
            continue
        results.append({
            "id": p["id"],
            "full_name": p.get("full_name") or p.get("email", "").split("@")[0],
            "email": p.get("email"),
            "role": p.get("role"),
            "courses": sorted({c for c in courses_by_user.get(p["id"], []) if c}),
        })
    role_order = {"admin": 0, "teacher": 1, "student": 2}
    results.sort(key=lambda r: (role_order.get(r["role"], 3), (r["full_name"] or "").lower()))
    return results[:500]


def list_scope_courses(user: CurrentUser) -> list[dict]:
    """Courses whose roster the caller can bulk-add (for the 'add whole course' picker)."""
    if user.role not in STAFF_ROLES:
        return []
    ids = _scope_course_ids(user)
    query = _sb().table("courses").select("id, name, code, semester")
    rows = (query.order("name").execute().data or []) if ids is None else _select_in(
        "courses", "id, name, code, semester", "id", ids
    )
    return sorted(rows, key=lambda c: (c.get("semester") or 0, c.get("name") or ""))


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation
# ─────────────────────────────────────────────────────────────────────────────


def _profiles(ids: Iterable[str]) -> dict[str, dict]:
    return {p["id"]: p for p in _select_in("profiles", "id, full_name, email, role", "id", ids)}


def _display_name(profile: Optional[dict]) -> str:
    if not profile:
        return "Unknown user"
    return (profile.get("full_name") or "").strip() or (profile.get("email") or "").split("@")[0] or "User"


def _sign_attachments(messages: list[dict]) -> None:
    """Replace each attachment's storage path with a signed URL, in one call per bucket."""
    settings = get_settings()
    refs = [a for m in messages for a in (m.get("attachments") or []) if a.get("path")]
    if not refs:
        return

    by_bucket: dict[str, list[str]] = {}
    for a in refs:
        bucket, key = storage_service.split_reference(a["path"], settings.BUCKET_CHAT)
        by_bucket.setdefault(bucket, []).append(key)

    signed: dict[str, str] = {}
    for bucket, keys in by_bucket.items():
        keys = list(dict.fromkeys(keys))
        try:
            for item in _sb().storage.from_(bucket).create_signed_urls(keys, settings.CHAT_SIGNED_URL_TTL_SECONDS):
                url = item.get("signedURL") or item.get("signedUrl")
                if url and item.get("path"):
                    if url.startswith("/"):
                        url = f"{settings.SUPABASE_URL}/storage/v1{url}"
                    signed[f"{bucket}/{item['path']}"] = url
        except Exception as exc:  # fall back to one-by-one so one bad key can't blank the chat
            logger.warning("Batch signing failed for %s: %s", bucket, exc)
            for key in keys:
                try:
                    signed[f"{bucket}/{key}"] = storage_service.create_signed_url(
                        f"{bucket}/{key}", bucket, expires_in=settings.CHAT_SIGNED_URL_TTL_SECONDS
                    )
                except Exception:
                    pass

    for a in refs:
        bucket, key = storage_service.split_reference(a["path"], settings.BUCKET_CHAT)
        a["url"] = signed.get(f"{bucket}/{key}")


def serialize_messages(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    senders = _profiles(r["sender_id"] for r in rows if r.get("sender_id"))

    reactions: dict[str, dict[str, list[str]]] = {}
    for r in _select_in("chat_reactions", "message_id, user_id, emoji", "message_id", ids):
        reactions.setdefault(r["message_id"], {}).setdefault(r["emoji"], []).append(r["user_id"])

    poll_ids = [r["id"] for r in rows if r.get("kind") == "poll" and not r.get("deleted_at")]
    votes: dict[str, dict[str, list[str]]] = {}
    for v in _select_in("chat_poll_votes", "message_id, user_id, option_id", "message_id", poll_ids):
        votes.setdefault(v["message_id"], {}).setdefault(v["option_id"], []).append(v["user_id"])

    out = []
    for r in rows:
        deleted = bool(r.get("deleted_at"))
        sender = senders.get(r.get("sender_id") or "")
        poll = None
        if r.get("poll") and not deleted:
            p = r["poll"]
            poll = {
                "question": p.get("question"),
                "allow_multiple": bool(p.get("allow_multiple")),
                "closed": bool(p.get("closed")),
                "options": [
                    {"id": o["id"], "text": o["text"], "voter_ids": votes.get(r["id"], {}).get(o["id"], [])}
                    for o in p.get("options", [])
                ],
            }
        out.append({
            "id": r["id"],
            "group_id": r["group_id"],
            "kind": r.get("kind") or "text",
            "body": None if deleted else r.get("body"),
            "attachments": [] if deleted else [dict(a) for a in (r.get("attachments") or [])],
            "is_important": bool(r.get("is_important")) and not deleted,
            "poll": poll,
            "created_at": r.get("created_at"),
            "deleted": deleted,
            "sender": {
                "id": r.get("sender_id"),
                "full_name": _display_name(sender),
                "role": (sender or {}).get("role"),
            } if r.get("sender_id") else None,
            "reactions": {} if deleted else reactions.get(r["id"], {}),
        })
    _sign_attachments(out)
    return out


def _load_message(message_id: str) -> dict:
    try:
        uuid.UUID(str(message_id))
    except ValueError:
        raise _not_found("Message")
    rows = _sb().table("chat_messages").select("*").eq("id", message_id).limit(1).execute().data or []
    if not rows:
        raise _not_found("Message")
    return rows[0]


def _message_payload(message_id: str) -> dict:
    return serialize_messages([_load_message(message_id)])[0]


def _group_payload(group: dict, membership: Optional[dict], extra: Optional[dict] = None) -> dict:
    payload = {
        "id": group["id"],
        "name": group["name"],
        "description": group.get("description"),
        "course_id": group.get("course_id"),
        "post_policy": group.get("post_policy", "admins"),
        "color": group.get("color") or "#4285F4",
        "created_by": group.get("created_by"),
        "created_at": group.get("created_at"),
        "last_message_at": group.get("last_message_at"),
        "my_role": (membership or {}).get("role"),
        "can_post": bool(membership) and _can_post(group, membership),
    }
    payload.update(extra or {})
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Groups
# ─────────────────────────────────────────────────────────────────────────────


def list_groups(user: CurrentUser) -> list[dict]:
    summaries = _sb().rpc("chat_group_summaries", {"p_user_id": user.id}).execute().data or []
    if not summaries:
        return []
    by_group = {s["group_id"]: s for s in summaries}

    groups = _select_in("chat_groups", "*", "id", list(by_group))
    memberships = {
        m["group_id"]: m
        for m in _sb().table("chat_members").select("*").eq("user_id", user.id).execute().data or []
    }
    course_codes = {
        c["id"]: c["code"]
        for c in _select_in("courses", "id, code", "id", [g["course_id"] for g in groups if g.get("course_id")])
    }
    last_ids = [s["last_message_id"] for s in summaries if s.get("last_message_id")]
    last_rows = _select_in("chat_messages", "*", "id", last_ids)
    last_by_id = {m["id"]: m for m in serialize_messages(last_rows)} if last_rows else {}

    result = []
    for g in groups:
        s = by_group.get(g["id"], {})
        result.append(_group_payload(g, memberships.get(g["id"]), {
            "course_code": course_codes.get(g.get("course_id") or ""),
            "unread_count": s.get("unread_count") or 0,
            "member_count": s.get("member_count") or 0,
            "last_message": last_by_id.get(s.get("last_message_id") or ""),
        }))
    result.sort(key=lambda g: g.get("last_message_at") or g.get("created_at") or "", reverse=True)
    return result


def get_group_detail(group_id: str, user: CurrentUser) -> dict:
    group, membership = assert_member(group_id, user)
    members = _sb().table("chat_members").select("*").eq("group_id", group_id).execute().data or []
    profiles = _profiles(m["user_id"] for m in members)
    member_list = [
        {
            "user_id": m["user_id"],
            "full_name": _display_name(profiles.get(m["user_id"])),
            "email": (profiles.get(m["user_id"]) or {}).get("email"),
            "role": (profiles.get(m["user_id"]) or {}).get("role"),
            "group_role": m["role"],
            "joined_at": m.get("joined_at"),
        }
        for m in members
    ]
    member_list.sort(key=lambda m: (m["group_role"] != "admin", m["full_name"].lower()))
    course = None
    if group.get("course_id"):
        rows = _sb().table("courses").select("id, name, code").eq("id", group["course_id"]).limit(1).execute().data or []
        course = rows[0] if rows else None
    return _group_payload(group, membership, {
        "members": member_list,
        "member_count": len(member_list),
        "course_code": (course or {}).get("code"),
        "course_name": (course or {}).get("name"),
    })


def _insert_system_message(group_id: str, actor_id: str, text: str) -> dict:
    row = _sb().table("chat_messages").insert({
        "group_id": group_id, "sender_id": actor_id, "kind": "system", "body": text,
    }).execute().data[0]
    _sb().table("chat_groups").update({"last_message_at": row["created_at"]}).eq("id", group_id).execute()
    return serialize_messages([row])[0]


def _names(user_ids: list[str], limit: int = 3) -> str:
    profiles = _profiles(user_ids)
    names = [_display_name(profiles.get(u)) for u in user_ids]
    if len(names) <= limit:
        return ", ".join(names)
    return f"{', '.join(names[:limit])} and {len(names) - limit} others"


def create_group(user: CurrentUser, data: ChatGroupCreate) -> tuple[dict, list[str], dict]:
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only teachers and admins can create chat groups.")
    if data.course_id and not is_course_teacher(data.course_id, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only link a group to a course you teach.")

    to_add = _assert_addable(user, data.member_ids)
    roles = {p["id"]: p["role"] for p in _select_in("profiles", "id, role", "id", to_add)}

    group = _sb().table("chat_groups").insert({
        "name": data.name,
        "description": (data.description or "").strip() or None,
        "course_id": data.course_id,
        "created_by": user.id,
        "post_policy": data.post_policy,
        "color": generate_course_color(random.randrange(1000)),
    }).execute().data[0]

    rows = [{"group_id": group["id"], "user_id": user.id, "role": "admin", "added_by": user.id}]
    rows += [
        {"group_id": group["id"], "user_id": uid, "role": _group_role_for(roles.get(uid, "student")), "added_by": user.id}
        for uid in to_add
    ]
    for chunk in (rows[i : i + 500] for i in range(0, len(rows), 500)):
        _sb().table("chat_members").insert(chunk).execute()

    system = _insert_system_message(group["id"], user.id, f"{_display_name(_profiles([user.id]).get(user.id))} created the group")
    return get_group_detail(group["id"], user), [user.id, *to_add], system


def update_group(group_id: str, user: CurrentUser, data: ChatGroupUpdate) -> tuple[dict, Optional[dict]]:
    group, _ = assert_group_admin(group_id, user)
    patch = data.model_dump(exclude_unset=True)
    if "name" in patch:
        patch["name"] = (patch["name"] or "").strip()
        if not patch["name"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Group name cannot be blank")
    if "description" in patch:
        patch["description"] = (patch["description"] or "").strip() or None
    if not patch:
        return get_group_detail(group_id, user), None
    patch["updated_at"] = _now()
    _sb().table("chat_groups").update(patch).eq("id", group_id).execute()

    system = None
    if "post_policy" in patch and patch["post_policy"] != group.get("post_policy"):
        who = _display_name(_profiles([user.id]).get(user.id))
        text = (
            f"{who} changed settings: everyone can send messages"
            if patch["post_policy"] == "everyone"
            else f"{who} changed settings: only teachers/admins can send messages"
        )
        system = _insert_system_message(group_id, user.id, text)
    return get_group_detail(group_id, user), system


def delete_group(group_id: str, user: CurrentUser) -> list[str]:
    group, _ = assert_member(group_id, user)
    if not (user.role == "admin" or group.get("created_by") == user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the group creator or an admin can delete this group.")
    recipients = member_ids(group_id)
    paths = [
        a["path"]
        for m in _sb().table("chat_messages").select("attachments").eq("group_id", group_id).execute().data or []
        for a in (m.get("attachments") or []) if a.get("path")
    ]
    _sb().table("chat_groups").delete().eq("id", group_id).execute()
    _remove_objects(paths)
    return recipients


def add_members(group_id: str, user: CurrentUser, user_ids: list[str]) -> tuple[dict, list[str], Optional[dict]]:
    assert_group_admin(group_id, user)
    current = set(member_ids(group_id))
    to_add = [u for u in _assert_addable(user, user_ids) if u not in current]
    if not to_add:
        return get_group_detail(group_id, user), [], None
    roles = {p["id"]: p["role"] for p in _select_in("profiles", "id, role", "id", to_add)}
    rows = [
        {"group_id": group_id, "user_id": uid, "role": _group_role_for(roles.get(uid, "student")), "added_by": user.id}
        for uid in to_add
    ]
    for chunk in (rows[i : i + 500] for i in range(0, len(rows), 500)):
        _sb().table("chat_members").insert(chunk).execute()
    who = _display_name(_profiles([user.id]).get(user.id))
    system = _insert_system_message(group_id, user.id, f"{who} added {_names(to_add)}")
    return get_group_detail(group_id, user), to_add, system


def remove_member(group_id: str, user: CurrentUser, target_id: str) -> tuple[Optional[dict], dict]:
    """Remove someone (group admin) or leave (staff only). Returns (detail or None if caller left, system msg)."""
    group, membership = assert_member(group_id, user)
    leaving = target_id == user.id

    if leaving:
        if user.role not in STAFF_ROLES:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Students can't leave class groups. Ask your teacher.")
    elif not _is_group_admin(membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only group admins can remove members.")

    target = _get_membership(group_id, target_id)
    if target is None:
        raise _not_found("Member")
    if target["role"] == "admin":
        admins = (
            _sb().table("chat_members").select("user_id")
            .eq("group_id", group_id).eq("role", "admin").execute().data or []
        )
        if len(admins) <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "A group needs at least one admin. Add another teacher first, or delete the group.",
            )

    _sb().table("chat_members").delete().eq("group_id", group_id).eq("user_id", target_id).execute()
    who = _display_name(_profiles([user.id]).get(user.id))
    text = f"{who} left the group" if leaving else f"{who} removed {_names([target_id])}"
    system = _insert_system_message(group_id, user.id, text)
    return (None if leaving else get_group_detail(group_id, user)), system


def mark_read(group_id: str, user: CurrentUser) -> None:
    assert_member(group_id, user)
    _sb().table("chat_members").update({"last_read_at": _now()}).eq("group_id", group_id).eq("user_id", user.id).execute()


# ─────────────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────────────


def list_messages(group_id: str, user: CurrentUser, before: Optional[str], limit: int) -> list[dict]:
    assert_member(group_id, user)
    query = _sb().table("chat_messages").select("*").eq("group_id", group_id)
    if before:
        query = query.lt("created_at", before)
    rows = query.order("created_at", desc=True).limit(max(1, min(limit, 100))).execute().data or []
    rows.reverse()
    return serialize_messages(rows)


def post_message(group_id: str, user: CurrentUser, data: ChatMessageCreate) -> dict:
    settings = get_settings()
    group, membership = assert_member(group_id, user)
    if not _can_post(group, membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only teachers and admins can send messages in this group.")

    body = (data.body or "").strip() or None
    if not body and not data.attachments and not data.poll:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Message is empty.")
    if data.is_important and not _is_group_admin(membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only group admins can mark messages as important.")

    # Attachments must have been uploaded into *this* group's folder.
    prefix = f"{settings.BUCKET_CHAT}/{group_id}/"
    attachments = []
    for a in data.attachments:
        if not a.path.startswith(prefix) or ".." in a.path:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid attachment.")
        attachments.append(a.model_dump())

    row: dict[str, Any] = {
        "group_id": group_id,
        "sender_id": user.id,
        "kind": "poll" if data.poll else "text",
        "body": body,
        "attachments": attachments,
        "is_important": data.is_important,
    }
    if data.poll:
        row["poll"] = {
            "question": data.poll.question.strip(),
            "allow_multiple": data.poll.allow_multiple,
            "closed": False,
            "options": [{"id": f"o{i + 1}", "text": text} for i, text in enumerate(data.poll.options)],
        }

    inserted = _sb().table("chat_messages").insert(row).execute().data[0]
    _sb().table("chat_groups").update({"last_message_at": inserted["created_at"]}).eq("id", group_id).execute()
    # Sending implies you've read everything up to now.
    _sb().table("chat_members").update({"last_read_at": inserted["created_at"]}).eq("group_id", group_id).eq("user_id", user.id).execute()
    return serialize_messages([inserted])[0]


def _remove_objects(paths: list[str]) -> None:
    for path in paths:
        storage_service.delete_object(path, get_settings().BUCKET_CHAT)


def delete_message(message_id: str, user: CurrentUser) -> dict:
    message = _load_message(message_id)
    _, membership = assert_member(message["group_id"], user)
    if message.get("sender_id") != user.id and not _is_group_admin(membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own messages.")
    if message.get("kind") == "system":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "System messages can't be deleted.")
    if not message.get("deleted_at"):
        paths = [a["path"] for a in (message.get("attachments") or []) if a.get("path")]
        _sb().table("chat_messages").update({
            "deleted_at": _now(), "body": None, "attachments": [], "poll": None, "is_important": False,
        }).eq("id", message_id).execute()
        _sb().table("chat_reactions").delete().eq("message_id", message_id).execute()
        _remove_objects(paths)
    return _message_payload(message_id)


def set_reaction(message_id: str, user: CurrentUser, emoji: Optional[str]) -> dict:
    message = _load_message(message_id)
    assert_member(message["group_id"], user)
    if message.get("deleted_at") or message.get("kind") == "system":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't react to this message.")
    _sb().table("chat_reactions").delete().eq("message_id", message_id).eq("user_id", user.id).execute()
    emoji = (emoji or "").strip()
    if emoji:
        _sb().table("chat_reactions").insert({"message_id": message_id, "user_id": user.id, "emoji": emoji}).execute()
    return _message_payload(message_id)


def vote(message_id: str, user: CurrentUser, option_ids: list[str]) -> dict:
    message = _load_message(message_id)
    assert_member(message["group_id"], user)
    poll = message.get("poll")
    if message.get("kind") != "poll" or not poll or message.get("deleted_at"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This message is not a poll.")
    if poll.get("closed"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This poll is closed.")

    valid = {o["id"] for o in poll.get("options", [])}
    chosen = list(dict.fromkeys(o for o in option_ids if o))
    if any(o not in valid for o in chosen):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown poll option.")
    if len(chosen) > 1 and not poll.get("allow_multiple"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This poll allows only one choice.")

    _sb().table("chat_poll_votes").delete().eq("message_id", message_id).eq("user_id", user.id).execute()
    if chosen:
        _sb().table("chat_poll_votes").insert(
            [{"message_id": message_id, "user_id": user.id, "option_id": o} for o in chosen]
        ).execute()
    return _message_payload(message_id)


def close_poll(message_id: str, user: CurrentUser) -> dict:
    message = _load_message(message_id)
    _, membership = assert_member(message["group_id"], user)
    if message.get("kind") != "poll" or not message.get("poll"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This message is not a poll.")
    if message.get("sender_id") != user.id and not _is_group_admin(membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the poll creator or a group admin can close it.")
    poll = dict(message["poll"])
    poll["closed"] = True
    _sb().table("chat_messages").update({"poll": poll}).eq("id", message_id).execute()
    return _message_payload(message_id)


def upload_attachment(group_id: str, user: CurrentUser, file_name: str, data: bytes, content_type: Optional[str]) -> dict:
    settings = get_settings()
    group, membership = assert_member(group_id, user)
    if not _can_post(group, membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only teachers and admins can send files in this group.")
    storage_service.assert_submission_upload_allowed(file_name, len(data))

    key = storage_service.build_object_key(group_id, file_name=file_name)
    try:
        path = storage_service.upload_bytes(settings.BUCKET_CHAT, key, data, content_type)
    except storage_service.StorageError as exc:
        logger.error("Chat upload failed: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not store the file. Check that the 'chat-media' storage bucket exists.",
        ) from exc
    return {
        "path": path,
        "name": file_name,
        "size": len(data),
        "mime": content_type or "application/octet-stream",
    }
