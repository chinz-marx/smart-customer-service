import asyncio

import pytest

from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.llm.generator import GenerateAnswerResult
from app.retrieval.schemas import SemanticAnswerHit, SemanticLookup
from app.tools.mcp_client import McpToolDefinition
from app.tools.schemas import ToolResult
from app.understanding.schemas import UnderstandingResult


class FakeUnderstandingService:
    """固定返回执行计划，避免测试调用真实语义理解模型。"""

    def __init__(self, result: UnderstandingResult) -> None:
        self.result = result

    async def understand(self, **kwargs) -> UnderstandingResult:
        return self.result


class CountingUnderstandingService(FakeUnderstandingService):
    """记录完整理解调用次数，用于证明结构化续填不会再次调用模型。"""

    def __init__(self, result: UnderstandingResult) -> None:
        super().__init__(result)
        self.calls = 0

    async def understand(self, **kwargs) -> UnderstandingResult:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("结构化参数续填不应再次调用完整理解模型")
        return await super().understand(**kwargs)


class SequenceUnderstandingService:
    """按轮次返回不同业务意图，并允许待补参数判断回退到完整路由。"""

    def __init__(self, results: list[UnderstandingResult]) -> None:
        self.results = iter(results)

    async def understand_pending_tool(self, **kwargs) -> None:
        return None

    async def understand(self, **kwargs) -> UnderstandingResult:
        return next(self.results)


class FakeMcpToolClient:
    """模拟 Java MCP，只暴露 Schema 并记录调用，不实现业务规则。"""

    def __init__(self) -> None:
        self.definition = McpToolDefinition(
            name="order_query",
            description="查询当前用户订单",
            input_schema={
                "type": "object",
                "properties": {
                    "sessionId": {"type": "string"},
                    "userId": {"type": "string"},
                    "requestId": {"type": "string"},
                    "orderId": {"type": "string"},
                },
                "required": ["sessionId", "userId", "requestId", "orderId"],
            },
        )
        self.calls: list[dict[str, object]] = []

    def get_tool(self, tool_name: str | None) -> McpToolDefinition | None:
        return self.definition if tool_name == self.definition.name else None

    async def call_tool(self, tool_name: str, arguments: dict[str, str], **context) -> ToolResult:
        self.calls.append(
            {"tool_name": tool_name, "arguments": dict(arguments), "context": context}
        )
        return ToolResult(
            tool_name=tool_name,
            success=True,
            data={"status": "SHIPPED"},
            message="订单已发货。",
            direct_answer=True,
        )


class MultiToolMcpClient(FakeMcpToolClient):
    """增加积分 Tool，用于验证用户明确切换业务时旧待办会被清理。"""

    def __init__(self) -> None:
        super().__init__()
        self.points_definition = McpToolDefinition(
            name="points_query",
            description="查询用户积分",
            input_schema={
                "type": "object",
                "properties": {
                    "sessionId": {"type": "string"},
                    "userId": {"type": "string"},
                    "requestId": {"type": "string"},
                    "memberNo": {"type": "string", "description": "会员编号"},
                },
                "required": ["sessionId", "userId", "requestId", "memberNo"],
            },
        )

    def get_tool(self, tool_name: str | None) -> McpToolDefinition | None:
        if tool_name == self.points_definition.name:
            return self.points_definition
        return super().get_tool(tool_name)


class FakeSemanticAnswerService:
    """返回固定规则，并记录知识查询是否执行。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def lookup(self, question: str, intent: str) -> SemanticLookup:
        self.calls.append((question, intent))
        return SemanticLookup(
            hit=SemanticAnswerHit(
                answer="已发货订单可以在订单详情查看物流节点。",
                provider="redis-search:knowledge",
                distance=0.20,
                source_id="shipping-rule",
            )
        )

    async def record_generated_answer(self, **kwargs) -> bool:
        return False


@pytest.fixture
def settings() -> Settings:
    """关闭真实模型和语义检索连接，测试只使用注入的替身。"""
    return Settings(
        understanding_mode="keyword",
        doubao_api_key="YOUR_TEST_KEY",
        semantic_search_enabled=False,
    )


def test_composite_route_combines_mcp_tool_and_knowledge_once(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """组合问题必须同时执行 Java Tool 与知识检索，再仅调用一次回答模型整合。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="order_query",
            confidence=0.97,
            route_type="composite",
            tool_name="order_query",
            tool_arguments={"orderId": "ORDER_123456"},
            knowledge_query="订单发货后在哪里查看物流规则",
            source="llm",
        )
    )
    mcp = FakeMcpToolClient()
    semantic = FakeSemanticAnswerService()
    agent = CustomerServiceAgent(
        settings,
        understanding_service=understanding,
        semantic_answer_service=semantic,
        mcp_tool_client=mcp,
    )
    generate_calls = 0

    async def combine_answer(message, state, history, tool_result, **kwargs):
        nonlocal generate_calls
        generate_calls += 1
        assert tool_result.message == "订单已发货。"
        assert kwargs["knowledge_answer"] == "已发货订单可以在订单详情查看物流节点。"
        return GenerateAnswerResult(
            answer="订单已发货，可以在订单详情查看物流节点。",
            provider="doubao",
        )

    monkeypatch.setattr(agent.orchestrator.answer_generator, "generate", combine_answer)

    result = asyncio.run(agent.handle("查一下 ORDER_123456，发货后去哪看物流", None, []))

    assert result.answer == "订单已发货，可以在订单详情查看物流节点。"
    assert result.decision_reason == "mcp_composite_ready"
    assert generate_calls == 1
    assert mcp.calls[0]["arguments"] == {"orderId": "ORDER_123456"}
    assert semantic.calls == [("订单发货后在哪里查看物流规则", "order_query")]


def test_missing_mcp_argument_is_asked_without_calling_tool(settings: Settings) -> None:
    """意图明确但缺少业务参数时，应由 MCP Schema 追问，不得误调用 Java Tool。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="order_query",
            confidence=0.97,
            route_type="tool",
            tool_name="order_query",
            source="llm",
        )
    )
    mcp = FakeMcpToolClient()
    agent = CustomerServiceAgent(
        settings,
        understanding_service=understanding,
        mcp_tool_client=mcp,
    )

    result = asyncio.run(agent.handle("帮我查订单", None, []))

    assert result.decision_action == "ask_slot"
    assert result.answer == "请提供需要查询的订单号。"
    assert mcp.calls == []


def test_pending_tool_accepts_bare_identifier_without_second_model_call(
    settings: Settings,
) -> None:
    """订单号位于句首且带自然语言后缀时，应由公共参数解析器直接续填。"""
    understanding = CountingUnderstandingService(
        UnderstandingResult(
            intent="order_query",
            confidence=0.97,
            route_type="tool",
            tool_name="order_query",
            source="llm",
        )
    )
    mcp = FakeMcpToolClient()
    agent = CustomerServiceAgent(
        settings,
        understanding_service=understanding,
        mcp_tool_client=mcp,
    )

    first = asyncio.run(agent.handle("帮我查订单", None, []))
    second = asyncio.run(
        agent.handle("ORDER_20260809001 我的订单号", first.session_id, [])
    )

    assert understanding.calls == 1
    assert second.provider == "tool:order_query"
    assert mcp.calls[0]["arguments"] == {"orderId": "ORDER_20260809001"}

    state = asyncio.run(
        agent.orchestrator.session_store.get_or_create(first.session_id)
    )
    assert state.active_tool is None
    assert state.tool_status is None
    assert state.tool_arguments == {}
    assert state.last_tool == "order_query"


def test_completed_order_arguments_are_not_reused_for_next_query(
    settings: Settings,
) -> None:
    """再次查订单必须重新索要订单号，不能调用Redis会话中的上一笔订单。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="order_query",
            confidence=0.97,
            route_type="tool",
            tool_name="order_query",
            source="llm",
        )
    )
    mcp = FakeMcpToolClient()
    agent = CustomerServiceAgent(
        settings,
        understanding_service=understanding,
        mcp_tool_client=mcp,
    )

    first = asyncio.run(agent.handle("帮我查订单", None, []))
    second = asyncio.run(agent.handle("ORDER_20260809001", first.session_id, []))
    third = asyncio.run(agent.handle("再次查订单", first.session_id, []))

    assert second.provider == "tool:order_query"
    assert third.decision_action == "ask_slot"
    assert third.answer == "请提供需要查询的订单号。"
    assert len(mcp.calls) == 1


def test_explicit_cancellation_clears_pending_tool(settings: Settings) -> None:
    """明确说不查了时应结束待办，不能让后续消息继续补旧 Tool 参数。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="order_query",
            confidence=0.97,
            route_type="tool",
            tool_name="order_query",
            source="llm",
        )
    )
    agent = CustomerServiceAgent(
        settings,
        understanding_service=understanding,
        mcp_tool_client=FakeMcpToolClient(),
    )

    first = asyncio.run(agent.handle("帮我查订单", None, []))
    cancelled = asyncio.run(agent.handle("不查了", first.session_id, []))
    state = asyncio.run(
        agent.orchestrator.session_store.get_or_create(first.session_id)
    )

    assert cancelled.answer == "好的，已取消当前操作。"
    assert state.active_tool is None
    assert state.tool_arguments == {}


def test_explicit_business_switch_replaces_pending_tool(settings: Settings) -> None:
    """等待订单号期间改查积分时，应终止订单待办并只等待积分参数。"""
    understanding = SequenceUnderstandingService(
        [
            UnderstandingResult(
                intent="order_query",
                confidence=0.97,
                route_type="tool",
                tool_name="order_query",
                source="llm",
            ),
            UnderstandingResult(
                intent="points_query",
                confidence=0.98,
                route_type="tool",
                tool_name="points_query",
                source="llm",
            ),
        ]
    )
    mcp = MultiToolMcpClient()
    agent = CustomerServiceAgent(
        settings,
        understanding_service=understanding,
        mcp_tool_client=mcp,
    )

    first = asyncio.run(agent.handle("帮我查订单", None, []))
    switched = asyncio.run(agent.handle("改成查积分", first.session_id, []))
    state = asyncio.run(
        agent.orchestrator.session_store.get_or_create(first.session_id)
    )

    assert switched.decision_action == "ask_slot"
    assert state.active_tool == "points_query"
    assert state.tool_status == "awaiting_args"
    assert state.tool_arguments == {}
    assert mcp.calls == []


def test_legacy_completed_arguments_are_cleared_before_new_turn(
    settings: Settings,
) -> None:
    """兼容旧Redis数据：无状态标记的完整参数不能在新一轮被再次执行。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="order_query",
            confidence=0.97,
            route_type="tool",
            tool_name="order_query",
            source="llm",
        )
    )
    mcp = FakeMcpToolClient()
    agent = CustomerServiceAgent(
        settings,
        understanding_service=understanding,
        mcp_tool_client=mcp,
    )
    state = asyncio.run(agent.orchestrator.session_store.get_or_create("legacy-session"))
    state.active_tool = "order_query"
    state.tool_arguments = {"orderId": "ORDER_OLD_123456"}
    asyncio.run(agent.orchestrator.session_store.save(state))

    result = asyncio.run(agent.handle("再次查订单", "legacy-session", []))
    restored = asyncio.run(
        agent.orchestrator.session_store.get_or_create("legacy-session")
    )

    assert result.decision_action == "ask_slot"
    assert restored.active_tool == "order_query"
    assert restored.tool_status == "awaiting_args"
    assert restored.tool_arguments == {}
    assert restored.last_tool == "order_query"
    assert mcp.calls == []
