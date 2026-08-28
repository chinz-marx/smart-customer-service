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
    """业务工具返回的统一结果结构。

    success=False 时，主流程不会崩溃，而是进入可控降级回复。
    """

    tool_name: str
    success: bool
    data: dict[str, object] = field(default_factory=dict)
    message: str = ""
    # True表示message已经是可直接展示给用户的完整话术，编排器无需再调用回答模型。
    direct_answer: bool = False
    error_code: str | None = None
    failed_stage: str | None = None
    error_type: str | None = None

    @classmethod
    def skipped(cls, tool_name: str, message: str) -> "ToolResult":
        """工具未注册或暂时不能调用时，返回统一失败结果。"""
        return cls(
            tool_name=tool_name,
            success=False,
            message=message,
            error_code="TOOL_SKIPPED",
            failed_stage="tool",
            error_type="ToolNotRegistered",
        )

    @classmethod
    def failed(cls, tool_name: str, message: str, error_type: str) -> "ToolResult":
        """工具内部异常时，返回统一失败结果。"""
        return cls(
            tool_name=tool_name,
            success=False,
            message=message,
            error_code="TOOL_FAILED",
            failed_stage="tool",
            error_type=error_type,
        )