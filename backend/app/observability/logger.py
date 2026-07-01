from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger("smart_customer_service.chat_trace")


@dataclass(slots=True)
class ChatTrace:
    """一轮客服对话的结构化日志。

    这个结构只记录排查问题需要的摘要信息，避免把完整用户隐私长期写进日志。
    """

    session_id: str
    message_preview: str
    intent: str
    intent_confidence: float
    slots: dict[str, str]
    decision_action: str
    decision_reason: str
    provider: str
    latency_ms: float
    tool_name: str | None = None
    tool_success: bool | None = None
    tool_error_code: str | None = None
    failed_stage: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    fallback_used: bool = False
    emotion: str = "normal"
    sensitive: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def log_chat_trace(trace: ChatTrace) -> None:
    """输出一条 JSON 格式的聊天链路日志。

    ensure_ascii=False 可以让中文在日志里保持可读，不会变成 \u4f60 这类转义。
    """
    payload = json.dumps(asdict(trace), ensure_ascii=False, default=str)
    logger.info(payload)


def mask_message(text: str, max_length: int = 120) -> str:
    """生成用户消息预览。

    生产日志不建议保存完整原文，所以这里只留短预览，并对常见敏感数字做基础脱敏。
    """
    preview = text.strip().replace("\n", " ")[:max_length]
    return _mask_digits(preview)


def mask_slots(slots: dict[str, Any]) -> dict[str, str]:
    """对槽位值做脱敏后再写日志。

    例如手机号后四位、订单号这类字段会保留排查所需的少量信息，但不完整暴露。
    """
    masked: dict[str, str] = {}
    for code, value in slots.items():
        text = str(value)
        if code in {"phone_tail"}:
            masked[code] = "****"
        elif code in {"order_id"}:
            masked[code] = _mask_order_id(text)
        else:
            masked[code] = _mask_digits(text)
    return masked


def _mask_order_id(value: str) -> str:
    """订单号只保留前后少量字符，方便排查同时降低泄露风险。"""
    if len(value) <= 4:
        return "****"
    if len(value) <= 8:
        return f"{value[:2]}****{value[-2:]}"
    return f"{value[:4]}****{value[-4:]}"


def _mask_digits(value: str) -> str:
    """把长数字串做基础脱敏，避免手机号、验证码等直接进日志。"""
    result: list[str] = []
    digit_run: list[str] = []

    def flush_digits() -> None:
        if not digit_run:
            return
        digits = "".join(digit_run)
        if len(digits) >= 4:
            result.append(f"{digits[:2]}****{digits[-2:]}")
        else:
            result.append(digits)
        digit_run.clear()

    for char in value:
        if char.isdigit():
            digit_run.append(char)
        else:
            flush_digits()
            result.append(char)
    flush_digits()
    return "".join(result)