from __future__ import annotations

from app.tools.schemas import ToolRequest, ToolResult


class RewardQueryTool:
    """奖励查询工具 mock。

    现在返回固定数据，用来打通生产级链路；后续这里会替换成 Java HTTP 调用。
    """

    name = "reward_query"

    async def call(self, request: ToolRequest) -> ToolResult:
        order_id = request.slots.get("order_id")
        activity_name = request.slots.get("activity_name") or "消费返现活动"
        phone_tail = request.slots.get("phone_tail")

        # Mock 数据模拟 Java 业务系统返回。生产环境必须以真实接口返回为准。
        data = {
            "reward_status": "processing",
            "activity_name": activity_name,
            "expected_days": 3,
            "query_basis": {
                "order_id": order_id,
                "phone_tail": phone_tail,
            },
        }
        basis = f"订单号 {order_id}" if order_id else f"活动 {activity_name}"
        if phone_tail and not order_id:
            basis = f"手机号后四位 {phone_tail}"

        return ToolResult(
            tool_name=self.name,
            success=True,
            data=data,
            message=f"已根据{basis}查询到奖励正在处理中，通常会在满足活动条件后的3个工作日内到账。",
        )