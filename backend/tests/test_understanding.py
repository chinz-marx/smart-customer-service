import asyncio
import json

from app.config import Settings
from app.configs.loader import load_runtime_config
from app.customer_service import CustomerServiceAgent
from app.intent.classifier import IntentClassifier
from app.tools.mcp_client import McpToolDefinition
from app.understanding.prompt import build_user_payload
from app.understanding.schemas import UnderstandingResult
from app.understanding.service import UnderstandingService


def test_pending_tool_understanding_only_sends_current_schema(monkeypatch) -> None:
    """结构化规则未命中时，轻量理解不能再次请求完整 Tool 语义目录。"""

    definition = McpToolDefinition(
        name="order_query",
        description="查询订单",
        input_schema={
            "type": "object",
            "properties": {"orderId": {"type": "string"}},
            "required": ["orderId"],
        },
    )

    class FakeMcpClient:
        def get_tool(self, tool_name: str):
            return definition if tool_name == "order_query" else None

        async def candidate_catalog(self, *args, **kwargs):
            raise AssertionError("待补参数理解不应执行完整 Tool 语义召回")

    service = UnderstandingService(
        Settings(
            understanding_mode="llm",
            understanding_api_key="real-test-key",
        ),
        mcp_tool_client=FakeMcpClient(),
    )

    async def fake_invoke_llm(**kwargs):
        assert kwargs["available_tools_override"] == [definition.prompt_payload()]
        return """{
          "intent": "order_query",
          "confidence": 0.96,
          "requires_tool": true,
          "route_type": "tool",
          "tool_name": "order_query",
          "tool_arguments": {"orderId": "ORDER_20260809001"}
        }"""

    monkeypatch.setattr(service, "_invoke_llm", fake_invoke_llm)

    result = asyncio.run(
        service.understand_pending_tool(
            message="这个编号帮我看看",
            history=[],
            current_intent="order_query",
            current_slots={},
            current_tool="order_query",
        )
    )

    assert result is not None
    assert result.tool_arguments == {"orderId": "ORDER_20260809001"}


def test_understanding_payload_exposes_knowledge_without_legacy_route_strategy() -> None:
    """业务意图不能与MCP Schema重复发送，Python只提供系统路由和知识来源。"""
    payload = json.loads(
        build_user_payload(
            message="物流不更新怎么办",
            history=[],
            current_intent=None,
            current_slots={},
            runtime_config=load_runtime_config(),
            available_tools=[
                {
                    "name": "order_query",
                    "description": "查询订单实时状态",
                    "input_schema": {
                        "type": "object",
                        "properties": {"orderId": {"type": "string"}},
                        "required": ["orderId"],
                    },
                }
            ],
            current_tool="order_query",
        )
    )

    assert payload["knowledge_source"]["available"] is True
    assert "异常处理办法" in payload["knowledge_source"]["content_scope"]
    assert "available_intents" not in payload
    assert {route["code"] for route in payload["system_routes"]} == {
        "greeting",
        "system_identity",
        "system_capability",
        "complaint",
        "human_handoff",
    }
    assert "order_query" not in {route["code"] for route in payload["system_routes"]}
    assert payload["available_tools"][0]["name"] == "order_query"
    assert payload["current_state"]["tool"] == "order_query"


def test_registered_mcp_tool_name_becomes_canonical_business_intent() -> None:
    """新版业务结果必须统一使用Java Tool名称，不能继续保存两套业务编码。"""

    class FakeMcpClient:
        def get_tool(self, tool_name: str):
            return object() if tool_name == "reward_query" else None

    service = UnderstandingService(
        Settings(understanding_mode="keyword"),
        mcp_tool_client=FakeMcpClient(),
    )

    result = service._parse_result(
        """{
          "intent": "reward_not_received",
          "confidence": 0.96,
          "requires_tool": true,
          "route_type": "tool",
          "tool_name": "reward_query",
          "tool_arguments": {"activityName": "消费返现"}
        }"""
    )

    assert result.intent == "reward_query"
    assert result.tool_name == "reward_query"


def test_registered_tool_intent_uses_schema_instead_of_generic_clarification() -> None:
    """意图已是真实Tool时，缺参数必须交给Schema追问而不是澄清业务。"""

    class FakeMcpClient:
        def get_tool(self, tool_name: str):
            return object() if tool_name == "order_query" else None

    service = UnderstandingService(
        Settings(understanding_mode="keyword"),
        mcp_tool_client=FakeMcpClient(),
    )

    result = service._parse_result(
        """{
          "intent": "order_query",
          "confidence": 0.90,
          "needs_clarification": true,
          "requires_tool": false,
          "route_type": "unknown",
          "tool_name": null
        }"""
    )

    assert result.intent == "order_query"
    assert result.route_type == "tool"
    assert result.tool_name == "order_query"
    assert result.requires_tool is True
    assert result.needs_clarification is False


def test_low_confidence_registered_tool_still_uses_hybrid_recheck(monkeypatch) -> None:
    """Tool选择置信度过低时，仍由hybrid复核而不盲目执行。"""

    class FakeMcpClient:
        def get_tool(self, tool_name: str):
            return object() if tool_name == "order_query" else None

    service = UnderstandingService(
        Settings(
            understanding_api_key="REAL_TEST_KEY",
            understanding_mode="hybrid",
        ),
        mcp_tool_client=FakeMcpClient(),
    )

    async def fake_invoke_llm(**kwargs) -> str:
        return """{
          "intent": "order_query",
          "confidence": 0.40,
          "needs_clarification": true,
          "route_type": "unknown"
        }"""

    monkeypatch.setattr(service, "_invoke_llm", fake_invoke_llm)
    result = asyncio.run(
        service.understand(
            message="帮我查订单",
            history=[],
            current_intent=None,
            current_slots={},
        )
    )

    assert result.intent == "order_query"
    assert result.confidence == 0.78
    assert result.source == "keyword"
    assert result.route_type == "tool"
    assert result.tool_name == "order_query"
    assert result.requires_tool is True


def test_knowledge_route_uses_generic_knowledge_intent() -> None:
    """纯知识检索不再依赖YAML中的活动、积分或退款业务意图。"""
    service = UnderstandingService(Settings(understanding_mode="keyword"))

    result = service._parse_result(
        """{
          "intent": "activity_rules",
          "confidence": 0.94,
          "requires_knowledge": true,
          "route_type": "knowledge",
          "knowledge_query": "活动什么时候结束"
        }"""
    )

    assert result.intent == "knowledge_query"
    assert result.route_type == "knowledge"


def test_keyword_slot_followup_keeps_active_mcp_tool() -> None:
    """模型降级时，纯参数补充必须继续当前MCP Tool而不是退回legacy。"""
    service = UnderstandingService(Settings(understanding_mode="keyword"))

    result = service._keyword_fallback(
        "ORDER_123456",
        current_intent="order_query",
        current_tool="order_query",
    )

    assert result.intent == "order_query"
    assert result.route_type == "tool"
    assert result.tool_name == "order_query"
    assert result.requires_tool is True


def test_keyword_mode_does_not_require_model() -> None:
    """keyword模式必须保持原有识别能力，并且不请求真实模型。"""
    settings = Settings(
        doubao_api_key="YOUR_TEST_KEY",
        understanding_mode="keyword",
    )
    service = UnderstandingService(settings)

    result = asyncio.run(
        service.understand(
            message="我的奖励还没到账",
            history=[],
            current_intent=None,
            current_slots={},
        )
    )

    assert result.intent == "reward_not_received"
    assert result.source == "keyword"
    assert result.needs_clarification is False


def test_keyword_tie_uses_configured_multi_intent_priority() -> None:
    """关键词分数相同时转人工优先，但普通的“客服”背景不能盖过明确投诉。"""
    classifier = IntentClassifier()

    assert classifier.classify("我要投诉并转人工").intent == "human_handoff"
    assert classifier.classify("我要投诉客服态度").intent == "complaint"
    assert classifier.classify("我要退款并查订单").intent == "refund_request"


def test_keyword_fallback_keeps_current_intent_for_slot_only_message() -> None:
    """模型不可用时，纯订单号应继续退款会话，不能误切到订单查询。"""
    service = UnderstandingService(
        Settings(
            understanding_mode="keyword",
            doubao_api_key="YOUR_TEST_KEY",
        )
    )

    for message in ("订单号REFUND_889900", "REFUND_889900"):
        result = asyncio.run(
            service.understand(
                message=message,
                history=[],
                current_intent="refund_request",
                current_slots={},
            )
        )

        assert result.intent == "refund_request"
        assert result.confidence == 0.88
        assert result.source == "keyword"


def test_hybrid_mode_parses_llm_json(monkeypatch) -> None:
    """LLM返回的JSON应被解析为统一结果，而不是把自然语言直接交给业务层。"""
    settings = Settings(
        doubao_api_key="REAL_TEST_KEY",
        understanding_api_key="REAL_TEST_KEY",
        understanding_mode="hybrid",
    )
    service = UnderstandingService(settings)

    async def fake_invoke_llm(**kwargs) -> str:
        return """```json
        {
          "intent": "reward_not_received",
          "confidence": 0.96,
          "slots": {"activity_name": "618消费返现"},
          "emotion": "normal",
          "risk_level": "low",
          "needs_clarification": false
        }
        ```"""

    monkeypatch.setattr(service, "_invoke_llm", fake_invoke_llm)
    result = asyncio.run(
        service.understand(
            message="618那笔钱还没给我",
            history=[],
            current_intent=None,
            current_slots={},
        )
    )

    assert result.intent == "reward_not_received"
    assert result.slots == {"activity_name": "618消费返现"}
    assert result.source == "llm"


def test_hybrid_mode_falls_back_when_llm_output_is_invalid(monkeypatch) -> None:
    """模型输出损坏时应降级到关键词识别，不能让聊天接口直接报错。"""
    settings = Settings(
        doubao_api_key="REAL_TEST_KEY",
        understanding_api_key="REAL_TEST_KEY",
        understanding_mode="hybrid",
    )
    service = UnderstandingService(settings)

    async def fake_invoke_llm(**kwargs) -> str:
        return "这不是合法JSON"

    monkeypatch.setattr(service, "_invoke_llm", fake_invoke_llm)
    result = asyncio.run(
        service.understand(
            message="我要查询积分",
            history=[],
            current_intent=None,
            current_slots={},
        )
    )

    assert result.intent == "points_query"
    assert result.source == "keyword"
    assert result.error_message


def test_hybrid_mode_rechecks_low_confidence_result(monkeypatch) -> None:
    """LLM返回unknown时，hybrid应采用更可靠的关键词结果继续业务流程。"""
    settings = Settings(
        understanding_api_key="REAL_TEST_KEY",
        understanding_mode="hybrid",
    )
    service = UnderstandingService(settings)

    async def fake_invoke_llm(**kwargs) -> str:
        return """{
          "intent": "unknown",
          "confidence": 0.1,
          "slots": {},
          "emotion": "normal",
          "risk_level": "low",
          "needs_clarification": true
        }"""

    monkeypatch.setattr(service, "_invoke_llm", fake_invoke_llm)
    result = asyncio.run(
        service.understand(
            message="帮我查询积分",
            history=[],
            current_intent=None,
            current_slots={},
        )
    )

    assert result.intent == "points_query"
    assert result.confidence == 0.95
    assert result.source == "keyword"
    assert result.error_message


def test_independent_source_flags_upgrade_tool_route_to_composite() -> None:
    """模型遗漏组合枚举时，独立数据来源判断必须由代码合成为composite。"""

    class FakeMcpClient:
        def get_tool(self, tool_name: str):
            return object() if tool_name == "order_query" else None

    service = UnderstandingService(
        Settings(understanding_mode="keyword"),
        mcp_tool_client=FakeMcpClient(),
    )

    result = service._parse_result(
        """{
          "intent": "order_query",
          "confidence": 0.95,
          "requires_tool": true,
          "requires_knowledge": true,
          "route_type": "tool",
          "tool_name": "order_query",
          "tool_arguments": {"orderId": "ORDER_123456"},
          "knowledge_query": "发货后还能不能取消"
        }"""
    )

    assert result.route_type == "composite"
    assert result.requires_tool is True
    assert result.requires_knowledge is True


def test_clear_additional_clause_protects_composite_plan() -> None:
    """小模型遗漏知识标记时，通用追加诉求结构应送入知识检索做二次验证。"""
    service = UnderstandingService(Settings(understanding_mode="keyword"))
    initial = UnderstandingResult(
        intent="order_query",
        confidence=0.92,
        requires_tool=True,
        requires_knowledge=False,
        route_type="tool",
        tool_name="order_query",
        tool_arguments={"orderId": "ORDER_123456"},
    )

    result = service._protect_composite_plan(
        initial,
        "查询订单 ORDER_123456，同时我还想咨询物流信息长时间不更新怎么办",
    )

    assert result.route_type == "composite"
    assert result.requires_knowledge is True
    assert result.knowledge_query == "咨询物流信息长时间不更新怎么办"


def test_single_tool_request_does_not_trigger_composite_guard() -> None:
    """纯Tool问题没有追加结构时，不能额外增加知识检索和回答模型耗时。"""
    service = UnderstandingService(Settings(understanding_mode="keyword"))
    initial = UnderstandingResult(
        intent="order_query",
        confidence=0.92,
        requires_tool=True,
        route_type="tool",
        tool_name="order_query",
    )

    result = service._protect_composite_plan(initial, "查询订单 ORDER_123456")

    assert result.route_type == "tool"
    assert result.requires_knowledge is False

class FakeUnderstandingService:
    """编排测试使用的固定理解结果，避免调用任何外部模型。"""

    def __init__(self, result: UnderstandingResult) -> None:
        self.result = result

    async def understand(self, **kwargs) -> UnderstandingResult:
        return self.result


def test_orchestrator_uses_llm_semantic_slot() -> None:
    """LLM提取的语义槽位应继续经过SlotManager校验并驱动原Tool流程。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="reward_not_received",
            confidence=0.96,
            slots={"activity_name": "夏季拉新奖励"},
            source="llm",
        )
    )
    agent = CustomerServiceAgent(
        Settings(doubao_api_key="YOUR_TEST_KEY"),
        understanding_service=understanding,
    )

    answer, _, provider, _ = asyncio.run(agent.reply("帮我看看那笔奖励", None, []))

    assert provider == "tool:reward_query"
    assert "夏季拉新奖励" in answer
    assert "当前状态：奖励正在处理中" in answer


def test_generic_activity_word_does_not_trigger_tool() -> None:
    """“返现”只是业务类别，不应被当成具体活动名称后直接调用Tool。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="reward_not_received",
            confidence=0.96,
            slots={"activity_name": "返现"},
            source="llm",
        )
    )
    agent = CustomerServiceAgent(
        Settings(doubao_api_key="YOUR_TEST_KEY"),
        understanding_service=understanding,
    )

    result = asyncio.run(agent.handle("我的返现一直没到账", None, []))

    assert result.decision_action == "ask_slot"
    assert "请提供" in result.answer


def test_explicit_handoff_is_not_blocked_by_clarification_flag() -> None:
    """模型已识别转人工时，即使同时要求澄清，也应优先执行人工策略。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="human_handoff",
            confidence=0.90,
            needs_clarification=True,
            source="llm",
        )
    )
    agent = CustomerServiceAgent(
        Settings(doubao_api_key="YOUR_TEST_KEY"),
        understanding_service=understanding,
    )

    result = asyncio.run(agent.handle("我要找真人客服", None, []))

    assert result.decision_action == "handoff"
    assert "转人工" in result.answer

def test_llm_high_risk_is_forced_to_handoff() -> None:
    """即使意图和槽位齐全，高风险结果也必须在调用Tool前转人工。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="points_query",
            confidence=0.97,
            slots={"phone_tail": "1234"},
            risk_level="high",
            source="llm",
        )
    )
    agent = CustomerServiceAgent(
        Settings(doubao_api_key="YOUR_TEST_KEY"),
        understanding_service=understanding,
    )

    answer, _, _, _ = asyncio.run(agent.reply("帮我处理一下", None, []))

    assert "敏感信息" in answer
    assert "转人工" in answer
