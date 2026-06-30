from __future__ import annotations

from dataclasses import dataclass, field

from app.session.store import ConversationState


@dataclass(slots=True)
class ToolRequest:
    """调用业务工具时传入的统一请求结构。"""

    session_id: str
    intent: str
    slots: dict[str, str]
    state: ConversationState


@dataclass(slots=True)
class ToolResult:
    """业务工具返回的统一结果结构。"""

    tool_name: str
    success: bool
    data: dict[str, object] = field(default_factory=dict)
    message: str = ""
    error_code: str | None = None

    @classmethod
    def skipped(cls, tool_name: str, message: str) -> "ToolResult":
        """工具未注册或暂时不能调用时，返回统一失败结果。"""
        return cls(tool_name=tool_name, success=False, message=message, error_code="TOOL_SKIPPED")