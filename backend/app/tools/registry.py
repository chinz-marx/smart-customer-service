from __future__ import annotations

from app.config import Settings
from app.errors import safe_error_message
from app.tools.order_tool import OrderQueryTool
from app.tools.points_tool import PointsQueryTool
from app.tools.reward_tool import RewardQueryTool
from app.tools.schemas import ToolRequest, ToolResult


class ToolRegistry:
    """业务工具注册表。

    Orchestrator 只通过工具名调用这里；未来接 Java HTTP Tool 时，只替换具体 Tool 实现即可。
    """

    def __init__(
        self,
        settings: Settings,
        order_tool: OrderQueryTool | None = None,
    ) -> None:
        self._tools = {
            RewardQueryTool.name: RewardQueryTool(),
            PointsQueryTool.name: PointsQueryTool(),
            # 测试可以注入 MockTransport 版本；生产环境默认创建真实 Java HTTP Tool。
            OrderQueryTool.name: order_tool or OrderQueryTool(settings),
        }

    async def call(self, tool_name: str | None, request: ToolRequest) -> ToolResult | None:
        """根据工具名调用对应工具。

        工具异常会在这里被捕获并转成 ToolResult，避免直接打断整条客服链路。
        """
        if not tool_name:
            return None

        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult.skipped(tool_name, f"工具 {tool_name} 尚未注册。")

        try:
            return await tool.call(request)
        except Exception as exc:
            return ToolResult.failed(
                tool_name=tool_name,
                message=safe_error_message(exc),
                error_type=exc.__class__.__name__,
            )