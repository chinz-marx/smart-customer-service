from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum


class LearningSignalType(IntEnum):
    """数据库中的问题来源数字枚举，避免依赖可变的中文展示名称。"""

    UNHELPFUL = 1
    NEGATIVE_RATING = 2
    HUMAN_HANDOFF = 3
    COMPLAINT = 4
    TOOL_FAILURE = 5
    RAG_MISS = 6


@dataclass(frozen=True, slots=True)
class LearningSignalCreate:
    """主链路准备写入 PostgreSQL 的轻量问题信号。"""

    signal_key: str
    source_type: LearningSignalType
    source_id: str
    conversation_id: str
    trigger_message_id: str
    user_id: str
    question_text: str
    target_assistant_message_id: str | None = None
    answer_text: str | None = None
    intent_code: str | None = None
    confidence: float | None = None
    tool_name: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class PendingLearningSignal:
    """后台任务从数据库原子领取的一条待向量化信号。"""

    id: int
    source_type: LearningSignalType
    conversation_id: str
    trigger_message_id: str
    user_id: str
    question_text: str
    answer_text: str | None
    intent_code: str | None
    occurred_at: datetime
