import asyncio

import pytest

from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.rules.quick_reply import QuickReplyMatcher
from app.understanding.schemas import UnderstandingResult


class FailUnderstandingService:
    """用于证明确定性短句不会调用意图模型。"""

    async def understand(self, **kwargs) -> UnderstandingResult:
        raise AssertionError("确定性快捷回复不应调用DeepSeek")


class FakeUnderstandingService:
    """返回固定意图，测试DeepSeek识别后的直返分支。"""

    def __init__(self, result: UnderstandingResult) -> None:
        self.result = result

    async def understand(self, **kwargs) -> UnderstandingResult:
        return self.result


def test_pure_greeting_uses_friendly_reply_without_model() -> None:
    """“你好”应直接友好回复，不能进入未知问题澄清。"""
    agent = CustomerServiceAgent(
        Settings(),
        understanding_service=FailUnderstandingService(),
    )

    result = asyncio.run(agent.handle("你好！", None, []))

    assert result.provider == "local-quick-reply"
    assert result.intent == "greeting"
    assert "智能客服小智" in result.answer
    assert "订单、退款、积分、会员权益或活动规则" in result.answer
    assert "还没完全理解" not in result.answer


def test_identity_question_uses_standard_reply_without_model() -> None:
    """系统身份属于确定信息，不应让回答模型自由生成。"""
    agent = CustomerServiceAgent(
        Settings(),
        understanding_service=FailUnderstandingService(),
    )

    result = asyncio.run(agent.handle("你是谁？", None, []))

    assert result.provider == "local-quick-reply"
    assert result.intent == "system_identity"
    assert "智能客服小智" in result.answer
    assert "人工客服" in result.answer


def test_greeting_with_business_request_is_not_intercepted() -> None:
    """寒暄加业务的复合句必须继续交给DeepSeek识别业务意图。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="order_query",
            confidence=0.97,
            source="llm",
        )
    )
    agent = CustomerServiceAgent(Settings(), understanding_service=understanding)

    result = asyncio.run(agent.handle("你好，我要查订单", None, []))

    assert result.provider != "local-quick-reply"
    assert result.intent == "order_query"
    assert result.decision_action == "ask_slot"
    assert "订单号" in result.answer


def test_natural_capability_question_uses_deepseek_direct_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """快捷短句未覆盖的自然表达由DeepSeek理解，但不再调用第二次回答模型。"""
    understanding = FakeUnderstandingService(
        UnderstandingResult(
            intent="system_capability",
            confidence=0.96,
            source="llm",
        )
    )
    agent = CustomerServiceAgent(Settings(), understanding_service=understanding)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("交互意图已有标准话术，不应调用回答模型")

    monkeypatch.setattr(agent.orchestrator.answer_generator, "generate", fail_if_called)

    result = asyncio.run(agent.handle("第一次来，不知道你都能帮我干啥", None, []))

    assert result.provider == "llm-direct-reply"
    assert result.intent == "system_capability"
    assert "查询订单" in result.answer
    assert "人工客服" in result.answer


def test_matcher_uses_full_sentence_matching() -> None:
    """包含寒暄词不等于纯寒暄，防止快捷路由错误截断业务请求。"""
    matcher = QuickReplyMatcher()

    assert matcher.match("您好。") is not None
    assert matcher.match("您好，我要申请退款") is None
    assert matcher.match("你好不好") is None
