from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChatFlowError:
    """聊天链路中的可观测错误。

    这个结构用于日志记录，不直接展示给用户，避免把底层异常细节暴露出去。
    """

    stage: str
    error_type: str
    message: str
    fallback_used: bool = True


def safe_error_message(exc: Exception, max_length: int = 200) -> str:
    """把异常转成短文本，避免日志过长。"""
    text = str(exc).replace("\n", " ").strip()
    if not text:
        text = exc.__class__.__name__
    return text[:max_length]
