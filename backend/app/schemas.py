from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):
    """前端传给后端的单条历史消息。"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """聊天接口请求体。"""

    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)
    conversation_id: str | None = Field(default=None, max_length=36)
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=64)
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    """聊天接口响应体。"""

    answer: str
    session_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    ticket_id: str | None = None
    provider: str
    suggestions: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    """针对某条AI回答提交的反馈。"""

    conversation_id: str = Field(max_length=36)
    message_id: str = Field(max_length=36)
    feedback_type: Literal["helpful", "unhelpful"]
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    """反馈保存结果。"""

    feedback_id: str
    feedback_type: str
    updated_at: datetime


class ConversationSummaryResponse(BaseModel):
    """历史对话列表中的一项。"""

    id: str
    session_id: str
    title: str
    status: str
    channel: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    """历史消息返回结构。"""

    id: str
    conversation_id: str
    role: str
    content: str
    intent: str | None = None
    provider: str | None = None
    created_at: datetime