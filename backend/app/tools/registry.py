from __future__ import annotations

from app.tools.points_tool import PointsQueryTool
from app.tools.reward_tool import RewardQueryTool
from app.tools.schemas import ToolRequest, ToolResult


class ToolRegistry:
    """业务工具注册表。

    Orchestrator 只通过工具名调用这里；未来接 Java HTTP Tool 时，只替换具体 Tool 实现即可。
    """

    def __init__(self) -> None:
        self._tools = {
            RewardQueryTool.name: RewardQueryTool(),
            PointsQueryTool.name: PointsQueryTool(),
        }

    async def call(self, tool_name: str | None, request: ToolRequest) -> ToolResult | None:
        """根据工具名调用对应工具。"""
        if not tool_name:
            return None

        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult.skipped(tool_name, f"工具 {tool_name} 尚未注册。")

        return await tool.call(request)