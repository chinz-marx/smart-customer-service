import asyncio
import json
import logging

from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.llm.generator import AnswerGenerator
from app.session.store import ConversationState
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolRequest


class BrokenTool:
    name = "broken_tool"

    async def call(self, request: ToolRequest):
        raise RuntimeError("java timeout")


def test_tool_exception_degrades_to_safe_answer(caplog, monkeypatch) -> None:
    caplog.set_level(logging.INFO, logger="smart_customer_service.chat_trace")
    monkeypatch.setenv("DOUBAO_API_KEY", "YOUR_TEST_KEY")

    original_init = ToolRegistry.__init__

    def patched_init(self, settings, order_tool=None):
        # 保持新注册表构造参数不变，只替换本测试关注的奖励 Tool。
        original_init(self, settings, order_tool=order_tool)
        self._tools["reward_query"] = BrokenTool()

    monkeypatch.setattr(ToolRegistry, "__init__", patched_init)
    agent = CustomerServiceAgent(Settings())

    _, session_id, _, _ = asyncio.run(agent.reply("我的奖励还没到账", None, []))
    answer, _, provider, _ = asyncio.run(agent.reply("订单号是 123456789", session_id, []))

    assert provider == "local-fallback"
    assert "业务工具暂时不可用" in answer
    assert "java timeout" in answer

    payload = json.loads(caplog.records[-1].message)
    assert payload["failed_stage"] == "tool"
    assert payload["error_type"] == "RuntimeError"
    assert payload["fallback_used"] is True


def test_llm_exception_degrades_to_local_answer(monkeypatch) -> None:
    monkeypatch.setenv("DOUBAO_API_KEY", "REAL_TEST_KEY")
    received_options = {}

    class BrokenChatOpenAI:
        def __init__(self, **kwargs):
            received_options.update(kwargs)
            raise RuntimeError("model timeout")

    monkeypatch.setattr("app.llm.generator.ChatOpenAI", BrokenChatOpenAI)
    state = ConversationState(session_id="s1", current_intent="reward_not_received")
    generator = AnswerGenerator(Settings())

    result = asyncio.run(generator.generate("我的奖励还没到账", state, []))

    assert result.provider == "local-fallback"
    assert result.fallback_used is True
    assert result.error is not None
    assert result.error.stage == "llm"
    assert result.error.error_type == "RuntimeError"
    assert "已记录您的奖励查询信息" in result.answer
    # 确认生产防护参数确实传入LangChain客户端，而不只是声明在配置文件中。
    assert received_options["timeout"] == 15.0
    assert received_options["max_retries"] == 1

def test_answer_generator_forwards_stream_chunks(monkeypatch) -> None:
    """回答生成器必须按模型产生顺序转发增量，并同时拼出完整落库文本。"""

    class FakeChunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class FakeChain:
        async def astream(self, values):
            yield FakeChunk("第一段")
            yield FakeChunk("，第二段")

    class FakePrompt:
        def __or__(self, llm):
            return FakeChain()

    settings = Settings(
        doubao_api_key="REAL_TEST_KEY",
        doubao_timeout_seconds=1,
    )
    generator = AnswerGenerator(settings)
    monkeypatch.setattr(
        "app.llm.generator.ChatPromptTemplate.from_messages",
        lambda messages: FakePrompt(),
    )
    monkeypatch.setattr(generator, "_get_llm", lambda: object())

    received: list[str] = []

    async def scenario():
        async def collect(chunk: str) -> None:
            received.append(chunk)

        state = ConversationState(session_id="stream-1", current_intent="points_query")
        return await generator.generate(
            "查询积分",
            state,
            [],
            on_chunk=collect,
        )

    result = asyncio.run(scenario())

    assert received == ["第一段", "，第二段"]
    assert result.answer == "第一段，第二段"
    assert result.provider == "doubao"
