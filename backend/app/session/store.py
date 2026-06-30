from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.slots.schemas import SlotValue


@dataclass(slots=True)
class ConversationState:
    """单个会话的状态。

    目前保存在内存里；未来接 Redis 时保持这个数据结构即可。
    """

    session_id: str
    current_intent: str | None = None
    slots: dict[str, SlotValue] = field(default_factory=dict)
    turn_count: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        """每轮对话后刷新轮次和更新时间。"""
        self.turn_count += 1
        self.updated_at = datetime.now(timezone.utc)


class InMemorySessionStore:
    """开发阶段使用的内存会话存储。

    注意：多进程部署时内存不共享，生产环境应替换为 Redis 或数据库。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationState] = {}

    def get_or_create(self, session_id: str) -> ConversationState:
        """根据 session_id 获取已有会话，没有就创建。"""
        if session_id not in self._sessions:
            self._sessions[session_id] = ConversationState(session_id=session_id)
        return self._sessions[session_id]

    def save(self, state: ConversationState) -> None:
        """保存会话状态。内存实现里就是覆盖字典。"""
        self._sessions[state.session_id] = state


# 全局单例，保证一次进程内的多轮对话能共享同一份状态。
session_store = InMemorySessionStore()