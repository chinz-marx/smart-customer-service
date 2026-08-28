from __future__ import annotations

import uuid
from typing import Protocol

from app.persistence.domain import (
    ConversationRecord,
    FeedbackRecord,
    MessageRecord,
    TicketRecord,
    utc_now,
)


class ChatRepository(Protocol):
    """聊天持久化统一接口，内存和PostgreSQL实现使用相同方法。"""

    async def initialize(self) -> None:
        """初始化数据库连接或测试数据容器。"""

    async def get_or_create_conversation(
        self,
        user_id: str,
        session_id: str,
        conversation_id: str | None,
        title: str,
    ) -> ConversationRecord:
        """读取当前用户的对话，不存在时创建。"""

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        request_id: str,
        intent: str | None = None,
        intent_confidence: float | None = None,
        provider: str | None = None,
        latency_ms: float | None = None,
    ) -> MessageRecord:
        """保存一条消息。"""

    async def list_conversations(self, user_id: str, limit: int = 20) -> list[ConversationRecord]:
        """查询用户最近的对话。"""

    async def list_messages(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 100,
    ) -> list[MessageRecord]:
        """查询一段对话中的消息。"""

    async def save_feedback(
        self,
        conversation_id: str,
        message_id: str,
        user_id: str,
        feedback_type: str,
        rating: int | None,
        comment: str | None,
    ) -> FeedbackRecord:
        """新增或更新用户对同一条消息的反馈。"""

    async def create_ticket(
        self,
        conversation_id: str,
        user_id: str,
        reason: str,
        summary: str,
        context_snapshot: dict[str, object],
        priority: str = "normal",
    ) -> TicketRecord:
        """创建人工工单；同一对话存在未完成工单时直接复用。"""

    async def health_check(self) -> bool:
        """检查持久化存储是否可用。"""

    async def close(self) -> None:
        """释放数据库连接。"""


class InMemoryChatRepository:
    """不依赖PostgreSQL的内存仓储，用于本地自测和单元测试。"""

    def __init__(self) -> None:
        self.conversations: dict[str, ConversationRecord] = {}
        self.messages: dict[str, MessageRecord] = {}
        self.feedback: dict[str, FeedbackRecord] = {}
        self.tickets: dict[str, TicketRecord] = {}

    async def initialize(self) -> None:
        """内存仓储无需初始化外部资源。"""

    async def get_or_create_conversation(
        self,
        user_id: str,
        session_id: str,
        conversation_id: str | None,
        title: str,
    ) -> ConversationRecord:
        """优先按conversation_id读取，其次按session_id复用。"""
        if conversation_id:
            conversation = self.conversations.get(conversation_id)
            if conversation is None or conversation.user_id != user_id:
                raise ValueError("对话不存在或不属于当前用户")
            return conversation

        for conversation in self.conversations.values():
            if conversation.session_id == session_id and conversation.user_id == user_id:
                return conversation

        conversation = ConversationRecord(
            id=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            title=title[:120],
        )
        self.conversations[conversation.id] = conversation
        return conversation

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        request_id: str,
        intent: str | None = None,
        intent_confidence: float | None = None,
        provider: str | None = None,
        latency_ms: float | None = None,
    ) -> MessageRecord:
        """保存消息，并刷新所属对话的更新时间。"""
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            raise ValueError("对话不存在")
        record = MessageRecord(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            request_id=request_id,
            intent=intent,
            intent_confidence=intent_confidence,
            provider=provider,
            latency_ms=latency_ms,
        )
        self.messages[record.id] = record
        conversation.updated_at = utc_now()
        return record

    async def list_conversations(self, user_id: str, limit: int = 20) -> list[ConversationRecord]:
        """按最后更新时间倒序返回当前用户的对话。"""
        rows = [item for item in self.conversations.values() if item.user_id == user_id]
        rows.sort(key=lambda item: item.updated_at, reverse=True)
        return rows[:limit]

    async def list_messages(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 100,
    ) -> list[MessageRecord]:
        """校验归属后按时间正序返回消息。"""
        conversation = self.conversations.get(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise ValueError("对话不存在或不属于当前用户")
        rows = [item for item in self.messages.values() if item.conversation_id == conversation_id]
        rows.sort(key=lambda item: item.created_at)
        return rows[-limit:]

    async def save_feedback(
        self,
        conversation_id: str,
        message_id: str,
        user_id: str,
        feedback_type: str,
        rating: int | None,
        comment: str | None,
    ) -> FeedbackRecord:
        """同一用户重复评价同一条消息时更新原记录。"""
        conversation = self.conversations.get(conversation_id)
        message = self.messages.get(message_id)
        if (
            conversation is None
            or conversation.user_id != user_id
            or message is None
            or message.conversation_id != conversation_id
            or message.role != "assistant"
        ):
            raise ValueError("只能评价当前用户对话中的AI回答")

        for record in self.feedback.values():
            if record.message_id == message_id and record.user_id == user_id:
                record.feedback_type = feedback_type
                record.rating = rating
                record.comment = comment
                record.updated_at = utc_now()
                return record

        record = FeedbackRecord(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            message_id=message_id,
            user_id=user_id,
            feedback_type=feedback_type,
            rating=rating,
            comment=comment,
        )
        self.feedback[record.id] = record
        return record

    async def create_ticket(
        self,
        conversation_id: str,
        user_id: str,
        reason: str,
        summary: str,
        context_snapshot: dict[str, object],
        priority: str = "normal",
    ) -> TicketRecord:
        """创建工单并把对话状态更新为handoff。"""
        conversation = self.conversations.get(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise ValueError("对话不存在或不属于当前用户")

        for ticket in self.tickets.values():
            if ticket.conversation_id == conversation_id and ticket.status in {"pending", "processing"}:
                return ticket

        record = TicketRecord(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            user_id=user_id,
            reason=reason,
            summary=summary,
            context_snapshot=context_snapshot,
            priority=priority,
        )
        self.tickets[record.id] = record
        conversation.status = "handoff"
        conversation.updated_at = utc_now()
        return record

    async def health_check(self) -> bool:
        """进程存活时内存仓储始终可用。"""
        return True

    async def close(self) -> None:
        """内存仓储没有需要释放的资源。"""