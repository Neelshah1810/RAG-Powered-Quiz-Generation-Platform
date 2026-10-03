"""Academix AI — Group chat request schemas.

Responses are plain dicts built in chat_service (they are also pushed verbatim
over the WebSocket, so REST and real-time payloads share one shape).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

PostPolicy = Literal["admins", "everyone"]


class ChatGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    course_id: Optional[str] = None
    post_policy: PostPolicy = "admins"
    member_ids: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Group name cannot be blank")
        return value


class ChatGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    post_policy: Optional[PostPolicy] = None


class ChatMembersAdd(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=1000)


class ChatAttachment(BaseModel):
    path: str
    name: str = Field(max_length=255)
    size: int = Field(ge=0)
    mime: str = Field(default="application/octet-stream", max_length=150)


class ChatPollCreate(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=12)
    allow_multiple: bool = False

    @field_validator("options")
    @classmethod
    def _clean_options(cls, value: list[str]) -> list[str]:
        cleaned = [o.strip()[:150] for o in value if o and o.strip()]
        if len(cleaned) < 2:
            raise ValueError("A poll needs at least two non-empty options")
        return cleaned


class ChatMessageCreate(BaseModel):
    body: Optional[str] = Field(default=None, max_length=5000)
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=10)
    is_important: bool = False
    poll: Optional[ChatPollCreate] = None


class ChatReaction(BaseModel):
    # None removes the caller's reaction.
    emoji: Optional[str] = Field(default=None, max_length=16)


class ChatVote(BaseModel):
    option_ids: list[str] = Field(default_factory=list, max_length=12)
