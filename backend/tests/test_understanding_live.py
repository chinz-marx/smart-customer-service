"""真实DeepSeek理解模型与完整聊天链路的冒烟测试。

默认执行pytest时本文件会跳过。只有显式设置RUN_LIVE_LLM_TESTS=1时才请求模型，
避免本地开发和CI无意产生网络请求、等待时间或模型费用。
这组测试只验证连通性与降级能力，不承担意图准确率评测。
"""

from __future__ import annotations

import asyncio
import os
from typing import Literal

import pytest

from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.session.store import InMemorySessionStore
from app.understanding.service import UnderstandingService


pytestmark = pytest.mark.live_llm


def _live_settings(
    mode: Literal["llm", "hybrid"],
    understanding_timeout_seconds: float,
) -> Settings:
    """读取真实.env，并按测试目的覆盖理解模式和超时时间。"""
    if os.getenv("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("设置RUN_LIVE_LLM_TESTS=1后才执行真实模型测试")

    settings = Settings(
        understanding_mode=mode,
        understanding_temperature=0.0,
        understanding_timeout_seconds=understanding_timeout_seconds,
    )
    if not settings.has_real_understanding_api_key:
        pytest.fail("真实理解测试需要在backend/.env配置UNDERSTANDING_API_KEY")
    return settings


def test_live_model_connectivity_and_json_output() -> None:
    """只发起一次直连请求，确认Key、模型名、地址和JSON解析都可用。"""

    async def scenario() -> None:
        settings = _live_settings(mode="llm", understanding_timeout_seconds=30)
        service = UnderstandingService(settings)
        result = await service.understand(
            message="帮我查下积分，手机号后四位是1234",
            history=[],
            current_intent=None,
            current_slots={},
        )

        print("模型直连 =>", result.model_dump(exclude={"error_message"}))
        assert result.source == "llm", result.error_message
        assert result.intent == "points_query"
        assert result.slots.get("phone_tail") == "1234"

    asyncio.run(scenario())


def test_live_hybrid_two_turn_chat_stays_available() -> None:
    """验证理解模型超时后，hybrid降级仍能完成两轮槽位收集和业务回答。"""

    async def scenario() -> None:
        settings = _live_settings(mode="hybrid", understanding_timeout_seconds=10)
        session_store = InMemorySessionStore()
        agent = CustomerServiceAgent(settings, session_store=session_store)

        first = await agent.handle("我的返现一直没到账", None, [])
        print(
            "第一轮 =>",
            {
                "intent": first.intent,
                "action": first.decision_action,
                "source": first.understanding_source,
                "latency_ms": first.latency_ms,
            },
        )
        assert first.intent == "reward_not_received"
        assert first.decision_action == "ask_slot"
        assert first.understanding_source in {"llm", "keyword"}

        second = await agent.handle(
            "订单号是 ABC123456",
            first.session_id,
            [],
        )
        print(
            "第二轮 =>",
            {
                "intent": second.intent,
                "action": second.decision_action,
                "source": second.understanding_source,
                "provider": second.provider,
                "latency_ms": second.latency_ms,
            },
        )
        assert second.intent == "reward_not_received"
        assert second.decision_action == "generate"
        assert second.slots.get("order_id") == "ABC123456"
        # reward_query已经提供完整话术，因此必须跳过回答模型。
        assert second.provider == "tool:reward_query"
        assert second.answer.strip()

    asyncio.run(scenario())