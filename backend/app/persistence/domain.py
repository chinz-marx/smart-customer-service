from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    """统一生成带时区的UTC时间。"""
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ConversationRecord:
    """一次完整客服对话的持久化记录。"""

    id: str
    user_id: str
    session_id: str
    title: str
    status: str = "active"
    channel: str = "web"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class MessageRecord:
    """用户、AI或系统产生的一条聊天消息。"""

    id: str
    conversation_id: str
    role: str
    content: str
    request_id: str
    intent: str | None = None
    intent_confidence: float | None = None
    provider: str | None = None
    latency_ms: float | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class FeedbackRecord:
    """用户针对某条AI回答提交的评价。"""

    id: str
    conversation_id: str
    message_id: str
    user_id: str
    feedback_type: str
    rating: int | None = None
    comment: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class TicketRecord:
    """需要人工继续处理的客服工单。"""

    id: str
    conversation_id: str
    user_id: str
    reason: str
    summary: str
    context_snapshot: dict[str, Any]
    priority: str = "normal"
    status: str = "pending"
    assigned_agent_id: str | None = None
    external_ticket_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)