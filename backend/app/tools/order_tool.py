from __future__ import annotations

import uuid

import httpx

from app.config import Settings
from app.tools.schemas import ToolRequest, ToolResult


class OrderQueryTool:
    """通过内部 HTTP 接口调用 Java 订单业务服务。"""

    name = "order_query"
    _path = "/api/internal/tools/orders/query"

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = settings.business_tool_base_url.rstrip("/")
        self.internal_token = settings.business_tool_internal_token.strip()
        self.timeout_seconds = settings.business_tool_timeout_seconds
        # transport 仅供单元测试注入 MockTransport，生产环境保持为 None。
        self.transport = transport

    async def call(self, request: ToolRequest) -> ToolResult:
        """查询属于当前登录用户的订单，并转换成 Python 统一 ToolResult。"""
        order_id = (request.slots.get("order_id") or "").strip().upper()
        if not order_id:
            # 正常流程会在槽位层拦截；这里再次校验，防止其他代码绕过编排器直接调用。
            return ToolResult(
                tool_name=self.name,
                success=False,
                message="订单号不能为空，请补充订单号后再查询。",
                error_code="INVALID_ARGUMENT",
                failed_stage="tool",
                error_type="MissingOrderId",
            )

        # user_id 必须来自登录态或可信应用层，绝不能使用用户在聊天文本中声称的身份。
        user_id = (request.state.user_id or "").strip()
        if not user_id:
            return ToolResult(
                tool_name=self.name,
                success=False,
                message="当前用户身份无效，暂时无法查询订单。",
                error_code="INVALID_USER_ID",
                failed_stage="tool",
                error_type="MissingUserId",
            )

        if not self.internal_token:
            return self._failed(
                code="TOOL_NOT_CONFIGURED",
                error_type="MissingInternalToken",
            )

        headers = {
            "X-Internal-Token": self.internal_token,
            # requestId 用来串联 Python 与 Java 日志；每次 Tool 调用都生成唯一值。
            "X-Request-Id": str(uuid.uuid4()),
        }
        payload = {
            "sessionId": request.session_id,
            "userId": user_id,
            "orderId": order_id,
        }

        try:
            timeout = httpx.Timeout(self.timeout_seconds)
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout,
                transport=self.transport,
            ) as client:
                response = await client.post(self._path, headers=headers, json=payload)
        except httpx.TimeoutException:
            return self._failed(code="TOOL_TIMEOUT", error_type="OrderToolTimeout")
        except httpx.RequestError:
            return self._failed(code="TOOL_UNAVAILABLE", error_type="OrderToolRequestError")

        try:
            response_payload = response.json()
        except ValueError:
            return self._failed(code="INVALID_TOOL_RESPONSE", error_type="InvalidToolJson")

        if not isinstance(response_payload, dict):
            return self._failed(code="INVALID_TOOL_RESPONSE", error_type="InvalidToolPayload")

        code = str(response_payload.get("code") or f"HTTP_{response.status_code}")
        if response.status_code >= 400 or response_payload.get("success") is not True:
            # Java 的具体内部错误写入结构化字段，展示给用户的仍是稳定且不泄露细节的话术。
            return self._failed(code=code, error_type="OrderToolRejected")

        data = response_payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("answer"), str):
            return self._failed(code="INVALID_TOOL_RESPONSE", error_type="MissingToolAnswer")

        return ToolResult(
            tool_name=self.name,
            success=True,
            data=data,
            message=data["answer"],
            direct_answer=True,
        )

    def _failed(self, code: str, error_type: str) -> ToolResult:
        """把网络、鉴权或响应格式错误转换成编排器可处理的统一失败结果。"""
        return ToolResult(
            tool_name=self.name,
            success=False,
            message="订单查询服务暂时不可用，请稍后重试或联系人工客服。",
            error_code=code,
            failed_stage="tool",
            error_type=error_type,
        )
