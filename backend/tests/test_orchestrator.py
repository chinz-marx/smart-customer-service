import asyncio
import json
import logging

import pytest

from app.config import Settings
from app.customer_service import CustomerServiceAgent


@pytest.fixture
def local_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DOUBAO_API_KEY", "YOUR_TEST_KEY")
    return Settings()


def test_reward_flow_asks_for_missing_slot(local_settings: Settings) -> None:
    agent = CustomerServiceAgent(local_settings)

    answer, session_id, provider, suggestions = asyncio.run(agent.reply("我的奖励还没到账", None, []))

    assert provider == "local-fallback"
    assert session_id
    assert "请提供订单号、活动名称、手机号后四位中的任意一项" in answer
    assert "查看我的奖励" in suggestions


def test_reward_flow_calls_mock_tool_when_user_provides_slot(local_settings: Settings, caplog) -> None:
    caplog.set_level(logging.INFO, logger="smart_customer_service.chat_trace")
    agent = CustomerServiceAgent(local_settings)

    _, session_id, _, _ = asyncio.run(agent.reply("我的奖励还没到账", None, []))
    answer, same_session_id, provider, _ = asyncio.run(agent.reply("订单号是 123456789", session_id, []))

    assert same_session_id == session_id
    assert provider == "local-fallback"
    assert "订单号 123456789" in answer
    assert "奖励正在处理中" in answer
    assert "3个工作日" in answer

    # 统一埋点应该记录本轮走了 reward_query 工具，同时订单号已被脱敏。
    payload = json.loads(caplog.records[-1].message)
    assert payload["tool_name"] == "reward_query"
    assert payload["slots"]["order_id"] == "1234****6789"


def test_points_flow_calls_mock_tool(local_settings: Settings) -> None:
    agent = CustomerServiceAgent(local_settings)

    _, session_id, _, _ = asyncio.run(agent.reply("我想查询积分", None, []))
    answer, same_session_id, provider, _ = asyncio.run(agent.reply("手机号后四位是 1234", session_id, []))

    assert same_session_id == session_id
    assert provider == "local-fallback"
    assert "当前积分为1280分" in answer
    assert "2026-12-31" in answer


def test_human_handoff_rule(local_settings: Settings) -> None:
    agent = CustomerServiceAgent(local_settings)

    answer, _, _, suggestions = asyncio.run(agent.reply("我要转人工", None, []))

    assert "转人工诉求" in answer
    assert "继续描述问题" in suggestions