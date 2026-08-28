from __future__ import annotations

from app.tools.schemas import ToolRequest, ToolResult


class PointsQueryTool:
    """积分查询工具 mock。

    未来替换成 Java 接口后，应返回真实积分余额、到期积分和积分流水。
    """

    name = "points_query"

    async def call(self, request: ToolRequest) -> ToolResult:
        phone_tail = request.slots.get("phone_tail")
        user_id = request.slots.get("user_id")

        # Mock 数据用于验证“槽位满足 -> Tool -> 回答生成”的完整链路。
        data = {
            "points_balance": 1280,
            "expiring_points": 120,
            "expire_date": "2026-12-31",
            "query_basis": {
                "phone_tail": phone_tail,
                "user_id": user_id,
            },
        }
        basis = f"用户ID {user_id}" if user_id else f"手机号后四位 {phone_tail}"
        return ToolResult(
            tool_name=self.name,
            success=True,
            data=data,
            message=(
                f"您好，已根据{basis}查询到您的积分情况：\n"
                "当前积分余额：1280分\n"
                "即将到期积分：120分\n"
                "到期时间：2026-12-31\n"
                "请在到期前及时使用，具体积分变动以业务系统记录为准。"
            ),
            direct_answer=True,
        )