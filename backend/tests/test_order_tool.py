import asyncio
import json
import logging

import httpx
import pytest

from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.session.store import ConversationState
from app.tools.order_tool import OrderQueryTool
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolRequest


@pytest.fixture
def local_settings() -> Settings:
    """订单闭环测试使用本地模型模式和假的 Java HTTP 地址，不访问外部服务。"""
    return Settings(
        doubao_api_key="YOUR_TEST_KEY",
        understanding_api_key="YOUR_TEST_KEY",
        business_tool_base_url="http://java-tool.test",
        business_tool_internal_token="unit-test-token",
    )


@pytest.fixture
def java_transport() -> httpx.MockTransport:
    """模拟 Java 统一响应协议，单元测试只验证 Python 的请求和解析逻辑。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/internal/tools/orders/query"
        assert request.headers["X-Internal-Token"] == "unit-test-token"
        assert request.headers["X-Request-Id"]

        body = json.loads(request.content)
        assert body["userId"] == "demo-user-001"
        order_id = body["orderId"]

        if order_id == "ORDER_999999":
            data = {
                "found": False,
                "orderId": order_id,
                "answer": (
                    f"没有查询到订单 {order_id}。请核对订单号是否完整；"
                    "如果订单号确认无误，请联系人工客服进一步核查。"
                ),
            }
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "code": "ORDER_NOT_FOUND",
                    "message": "订单查询完成",
                    "requestId": request.headers["X-Request-Id"],
                    "data": data,
                },
            )

        data = {
            "found": True,
            "orderId": order_id,
            "statusCode": "SHIPPED",
            "statusText": "已发货",
            "logisticsText": "包裹已从上海分拨中心发出",
            "expectedProgress": "预计明天送达",
            "answer": (
                f"您好，已查询到订单 {order_id}：\n"
                "订单状态：已发货\n"
                "物流信息：包裹已从上海分拨中心发出\n"
                "进度预估：预计明天送达\n"
                "订单状态以业务系统最新记录为准。"
            ),
        }
        return httpx.Response(
            200,
            json={
                "success": True,
                "code": "ORDER_FOUND",
                "message": "订单查询完成",
                "requestId": request.headers["X-Request-Id"],
                "data": data,
            },
        )

    return httpx.MockTransport(handler)


def build_agent(
    settings: Settings,
    transport: httpx.MockTransport,
) -> CustomerServiceAgent:
    """给编排器注入离线 Java Tool，避免单元测试依赖已启动的 Java 服务。"""
    agent = CustomerServiceAgent(settings)
    order_tool = OrderQueryTool(settings, transport=transport)
    agent.orchestrator.tool_registry = ToolRegistry(settings, order_tool=order_tool)
    return agent


def test_order_flow_asks_for_order_id(local_settings: Settings) -> None:
    """识别到订单查询但没有订单号时，只能追问，不能提前调用 Tool。"""
    agent = CustomerServiceAgent(local_settings)

    result = asyncio.run(agent.handle("帮我查询订单状态", None, []))

    assert result.decision_action == "ask_slot"
    assert result.answer == "请提供需要查询的订单号。"
    assert result.provider == "local-fallback"


def test_order_flow_calls_java_tool_and_skips_answer_model(
    local_settings: Settings,
    java_transport: httpx.MockTransport,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """补齐订单号后直接返回 Java 完整话术，不再调用最终回答模型。"""
    caplog.set_level(logging.INFO, logger="smart_customer_service.chat_trace")
    agent = build_agent(local_settings, java_transport)
    answer_model_called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal answer_model_called
        answer_model_called = True
        raise AssertionError("Java Tool 已返回完整话术，不应再次调用回答模型")

    monkeypatch.setattr(agent.orchestrator.answer_generator, "generate", fail_if_called)

    first = asyncio.run(
        agent.handle(
            "帮我查询订单状态",
            None,
            [],
            user_id=local_settings.demo_user_id,
        )
    )
    second = asyncio.run(
        agent.handle("订单号是 ORDER_123456", first.session_id, [])
    )

    assert answer_model_called is False
    assert second.provider == "tool:order_query"
    assert second.decision_action == "generate"
    assert "订单状态：已发货" in second.answer
    assert "预计明天送达" in second.answer

    payload = json.loads(caplog.records[-1].message)
    assert payload["tool_name"] == "order_query"
    assert payload["tool_success"] is True
    assert payload["slots"]["order_id"] == "ORDE****3456"


def test_order_tool_returns_direct_answer_when_order_is_not_found(
    local_settings: Settings,
    java_transport: httpx.MockTransport,
) -> None:
    """查不到订单是正常业务结果，应返回核对提示而不是系统故障。"""
    agent = build_agent(local_settings, java_transport)

    first = asyncio.run(
        agent.handle(
            "查询订单状态",
            None,
            [],
            user_id=local_settings.demo_user_id,
        )
    )
    second = asyncio.run(
        agent.handle("订单号是 ORDER_999999", first.session_id, [])
    )

    assert second.provider == "tool:order_query"
    assert "没有查询到订单 ORDER_999999" in second.answer
    assert "核对订单号" in second.answer


def test_order_tool_defensively_rejects_missing_order_id(
    local_settings: Settings,
) -> None:
    """即使绕过槽位层直接调用 Tool，缺少订单号也必须返回结构化失败。"""
    tool = OrderQueryTool(local_settings)
    request = ToolRequest(
        session_id="test-session",
        intent="order_query",
        slots={},
        state=ConversationState(
            session_id="test-session",
            user_id=local_settings.demo_user_id,
        ),
    )

    result = asyncio.run(tool.call(request))

    assert result.success is False
    assert result.error_code == "INVALID_ARGUMENT"
    assert result.error_type == "MissingOrderId"
    assert result.direct_answer is False


def test_order_tool_handles_java_unavailable(local_settings: Settings) -> None:
    """Java 无法连接时必须返回可降级结果，不能把 httpx 异常抛到接口层。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    tool = OrderQueryTool(local_settings, transport=httpx.MockTransport(handler))
    request = ToolRequest(
        session_id="test-session",
        intent="order_query",
        slots={"order_id": "ORDER_123456"},
        state=ConversationState(
            session_id="test-session",
            user_id=local_settings.demo_user_id,
        ),
    )

    result = asyncio.run(tool.call(request))

    assert result.success is False
    assert result.error_code == "TOOL_UNAVAILABLE"
    assert result.error_type == "OrderToolRequestError"
