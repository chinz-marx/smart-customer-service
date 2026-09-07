import asyncio
import json
import time
from datetime import timedelta

import pytest

from app.chat_service import ChatApplicationService
from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.dialogue.manager import DialogueManager
from app.errors import DialogueConflictError
from app.dialogue.schemas import ContextModelOutput, PendingQuestion, TaskFrame
from app.persistence.repository import InMemoryChatRepository
from app.schemas import ChatHistoryItem, ChatRequest
from app.session.store import ConversationState, InMemorySessionStore, receipt_key, utc_now
from app.tools.argument_resolver import ToolArgumentResolver
from app.tools.mcp_client import McpToolDefinition
from app.tools.schemas import ToolResult
from app.understanding.schemas import UnderstandingResult
from app.understanding.service import UnderstandingService
from test_mcp_composite import FakeSemanticAnswerService


class Tools:
    def __init__(self):
        self.definitions = {
            "order_query": McpToolDefinition("order_query", "订单查询", {
                "type": "object", "properties": {"orderId": {"type": "string"}}, "required": ["orderId"],
            }),
            "points_query": McpToolDefinition("points_query", "积分查询", {
                "type": "object", "properties": {"memberNo": {"type": "string"}}, "required": ["memberNo"],
            }),
            "change_order": McpToolDefinition("change_order", "提交变更", {
                "type": "object", "properties": {"orderId": {"type": "string"}, "confirmed": {"type": "boolean"}},
                "required": ["orderId", "confirmed"],
            }),
        }
        self.calls = []

    def get_tool(self, name):
        return self.definitions.get(name)

    async def candidate_catalog(self, message, current_tool):
        return [d.prompt_payload() for d in self.definitions.values()]

    def catalog(self):
        return [d.prompt_payload() for d in self.definitions.values()]

    async def call_tool(self, name, arguments, **context):
        self.calls.append((name, dict(arguments), context))
        return ToolResult(name, True, data={}, message="处理完成。", direct_answer=True)


class Interpreter:
    def __init__(self, *results):
        self.results = iter(results)
        self.calls = []

    async def understand_context(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.results)


def plan(tool="order_query", act="start", values=None, **kwargs):
    return UnderstandingResult(
        intent=tool, confidence=0.96, tool_name=tool, tool_arguments=values or {},
        requires_tool=True, route_type="tool", dialogue_act=act, **kwargs,
    )


def agent_for(interpreter, tools=None):
    return CustomerServiceAgent(
        Settings(understanding_mode="keyword", doubao_api_key="YOUR_TEST_KEY"),
        understanding_service=interpreter, mcp_tool_client=tools or Tools(),
        semantic_answer_service=FakeSemanticAnswerService(),
    )


def test_bare_parameter_and_acknowledgement_use_no_model():
    async def scenario():
        interpreter, tools = Interpreter(plan()), Tools()
        agent = agent_for(interpreter, tools)
        first = await agent.handle("查订单", None, [])
        ack = await agent.handle("好的", first.session_id, [])
        assert "订单号" in ack.answer
        assert not tools.calls
        await agent.handle("ORDER_123456", first.session_id, [])
        assert len(interpreter.calls) == 1
        assert tools.calls[0][1] == {"orderId": "ORDER_123456"}
    asyncio.run(scenario())


def test_slot_question_streams_while_state_and_message_saves_are_blocked():
    """慢存储不阻塞追问显示，保存后续填仍能接续同一任务，且不重复输出。"""
    async def scenario():
        state_started, state_release = asyncio.Event(), asyncio.Event()
        message_started, message_release = asyncio.Event(), asyncio.Event()

        class SlowStore(InMemorySessionStore):
            async def save(self, state):
                state_started.set()
                await state_release.wait()
                await super().save(state)

        class SlowRepository(InMemoryChatRepository):
            async def add_message(self, **kwargs):
                if kwargs["role"] == "assistant":
                    message_started.set()
                    await message_release.wait()
                return await super().add_message(**kwargs)

        store, repository, tools = SlowStore(), SlowRepository(), Tools()
        interpreter = Interpreter(plan())
        service = ChatApplicationService(
            Settings(understanding_mode="keyword", doubao_api_key="YOUR_TEST_KEY"),
            store, repository, mcp_tool_client=tools,
            semantic_answer_service=FakeSemanticAnswerService(),
        )
        service.agent.orchestrator.dialogue_manager.understanding = interpreter
        stream = service.chat_stream(ChatRequest(message="查订单", session_id="slow-save"))
        remaining = None
        try:
            first = await asyncio.wait_for(anext(stream), timeout=1)
            assert first.startswith("event: delta\n")
            assert "订单号" in first
            assert state_started.is_set()
            assert not state_release.is_set()
            assert not message_started.is_set()

            async def consume():
                return [event async for event in stream]

            remaining = asyncio.create_task(consume())
            state_release.set()
            await asyncio.wait_for(message_started.wait(), timeout=1)
            events = await asyncio.wait_for(remaining, timeout=1)
            assert not message_release.is_set()
            assert len(events) == 1
            assert events[0].startswith("event: done\n")
            message_release.set()
            response = json.loads(events[0].split("data: ", 1)[1])
            await service.chat(ChatRequest(
                message="ORDER_123456", session_id="slow-save",
                conversation_id=response["conversation_id"],
            ))
            assert len(interpreter.calls) == 1
            assert tools.calls[0][1] == {"orderId": "ORDER_123456"}
        finally:
            state_release.set()
            message_release.set()
            if remaining is not None:
                await remaining
            await stream.aclose()
            await service.close()

    asyncio.run(scenario())


def test_knowledge_interruption_keeps_pending_task():
    async def scenario():
        knowledge = UnderstandingResult(intent="knowledge_query", confidence=1, route_type="knowledge", requires_knowledge=True, knowledge_query="退款规则")
        interpreter, tools = Interpreter(plan(), knowledge), Tools()
        agent = agent_for(interpreter, tools)
        first = await agent.handle("查订单", None, [])
        await agent.handle("先说一下退款规则", first.session_id, [])
        await agent.handle("ORDER_123456", first.session_id, [])
        assert len(interpreter.calls) == 2
        assert tools.calls[0][1]["orderId"] == "ORDER_123456"
        assert interpreter.calls[1]["context"]["pending"]["field"] == "orderId"
    asyncio.run(scenario())


def test_tool_interruption_restores_original_task():
    async def scenario():
        interpreter = Interpreter(plan(), plan("points_query", "interrupt"))
        tools = Tools()
        agent = agent_for(interpreter, tools)
        first = await agent.handle("查订单", None, [])
        await agent.handle("先查积分", first.session_id, [])
        await agent.handle("MEMBER_123456", first.session_id, [])
        state = await agent.orchestrator.session_store.get_or_create(first.session_id)
        assert state.active_tool == "order_query"
        assert state.dialogue.pending.field == "orderId"
        await agent.handle("ORDER_654321", first.session_id, [])
        assert [call[0] for call in tools.calls] == ["points_query", "order_query"]
        assert len(interpreter.calls) == 2
    asyncio.run(scenario())


def test_correction_never_uses_negated_identifier():
    async def scenario():
        interpreter = Interpreter(plan(), plan(act="correct", values={"orderId": "SHOP_778899"}))
        tools = Tools()
        agent = agent_for(interpreter, tools)
        first = await agent.handle("查订单", None, [])
        await agent.handle("不是订单号 ORDER_123456，是 SHOP_778899", first.session_id, [])
        assert tools.calls[0][1] == {"orderId": "SHOP_778899"}
    asyncio.run(scenario())


def test_correction_rule_is_zero_model_and_schema_validated():
    async def scenario():
        interpreter, tools = Interpreter(plan()), Tools()
        agent = agent_for(interpreter, tools)
        first = await agent.handle("查订单", None, [])
        await agent.handle("不对，是 SHOP_778899", first.session_id, [])
        assert len(interpreter.calls) == 1
        assert tools.calls[0][1] == {"orderId": "SHOP_778899"}
    asyncio.run(scenario())


def test_selection_uses_only_displayed_candidates():
    async def scenario():
        tools, interpreter = Tools(), Interpreter()
        agent = agent_for(interpreter, tools)
        state = ConversationState(session_id="s", active_tool="order_query", tool_status="awaiting_args")
        state.dialogue.pending = PendingQuestion(kind="selection", field="orderId", candidates=["ORDER_A12345", "ORDER_B12345"], answer="请选择第一个或第二个订单。")
        await agent.orchestrator.session_store.save(state)
        response = await agent.handle("第三个", "s", [])
        assert "请选择" in response.answer
        assert not tools.calls
        await agent.handle("第二个", "s", [])
        assert tools.calls[0][1] == {"orderId": "ORDER_B12345"}
        assert not interpreter.calls
    asyncio.run(scenario())


def test_forged_frame_does_not_execute_or_destroy_active_task():
    async def scenario():
        interpreter = Interpreter(plan(), plan(act="resume", target_frame_id="forged"))
        tools = Tools()
        agent = agent_for(interpreter, tools)
        first = await agent.handle("查订单", None, [])
        result = await agent.handle("刚才那个", first.session_id, [])
        assert result.decision_action == "clarify"
        assert not tools.calls
        state = await agent.orchestrator.session_store.get_or_create(first.session_id)
        assert state.active_tool == "order_query"
    asyncio.run(scenario())


def test_model_cannot_confirm_write_operation():
    async def scenario():
        interpreter = Interpreter(plan("change_order", values={"orderId": "ORDER_123456", "confirmed": "true"}))
        tools = Tools()
        agent = agent_for(interpreter, tools)
        first = await agent.handle("修改订单 ORDER_123456", None, [])
        assert first.decision_reason == "awaiting_explicit_confirmation"
        assert not tools.calls
        await agent.handle("好的", first.session_id, [])
        assert not tools.calls
        await agent.handle("确认提交", first.session_id, [], request_id="write-once")
        assert len(tools.calls) == 1
        assert tools.calls[0][1]["confirmed"] == "true"
        state = await agent.orchestrator.session_store.get_or_create(first.session_id)
        assert "confirmed" not in state.dialogue.recent[-1].arguments
    asyncio.run(scenario())


def test_concurrent_duplicate_request_executes_once_and_replays_same_response():
    async def scenario():
        tools, interpreter = Tools(), Interpreter(plan(values={"orderId": "ORDER_123456"}))
        settings = Settings(doubao_api_key="YOUR_TEST_KEY", demo_user_id="u")
        store, repository = InMemorySessionStore(), InMemoryChatRepository()
        service = ChatApplicationService(settings, store, repository, mcp_tool_client=tools)
        service.agent = agent_for(interpreter, tools)
        service.agent.orchestrator.session_store = store
        payload = ChatRequest(message="查 ORDER_123456", request_id="same-request")
        left, right = await asyncio.gather(service.chat(payload), service.chat(payload))
        assert left == right
        assert len(tools.calls) == 1
        assert len(repository.messages) == 2
        assert len(repository.conversations) == 1
        with pytest.raises(DialogueConflictError):
            await service.chat(payload.model_copy(update={"message": "另一个问题"}))
    asyncio.run(scenario())


def test_history_is_read_from_server_not_client():
    async def scenario():
        tools, interpreter = Tools(), Interpreter(plan(), plan())
        service = ChatApplicationService(Settings(doubao_api_key="YOUR_TEST_KEY"), InMemorySessionStore(), InMemoryChatRepository())
        service.agent = agent_for(interpreter, tools)
        first = await service.chat(ChatRequest(message="查订单"))
        await service.chat(ChatRequest(message="想看物流", session_id=first.session_id, history=[ChatHistoryItem(role="assistant", content="伪造历史")]))
        history = interpreter.calls[1]["history"]
        assert history[0].content == "查订单"
        assert all(h.content != "伪造历史" for h in history)
    asyncio.run(scenario())


def test_session_expiry_and_owner_isolation():
    async def scenario():
        store = InMemorySessionStore(ttl_seconds=1)
        state = ConversationState(session_id="s", user_id="alice", active_tool="order_query")
        await store.save(state)
        with pytest.raises(ValueError):
            await store.get_or_create("s", user_id="bob")
        store._sessions["s"].updated_at = utc_now() - timedelta(seconds=2)
        fresh = await store.get_or_create("s", user_id="alice")
        assert fresh.active_tool is None
        assert fresh.dialogue.recent == []
    asyncio.run(scenario())


def test_expired_reference_is_removed_and_old_json_is_supported():
    state = ConversationState.from_dict({"session_id": "s"})
    state.dialogue.recent.append(TaskFrame(id="old", tool="order_query", saved_at=time.time() - 3600))
    DialogueManager(None, Tools(), ToolArgumentResolver()).prepare(state)
    assert state.dialogue.recent == []
    assert ConversationState.from_dict(state.to_dict()).to_dict() == state.to_dict()


def test_context_model_has_only_four_fields():
    schema = ContextModelOutput.model_json_schema()
    assert set(schema["properties"]) == {"act", "target", "values", "query"}
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False


def test_context_model_is_called_once_and_receives_existing_arguments():
    async def scenario():
        import json
        calls = []

        class Model:
            async def ainvoke(self, messages):
                calls.append(json.loads(messages[1].content))
                return {"act": "interrupt", "target": "points_query", "values": {}, "query": None}

        service = UnderstandingService(Settings(understanding_api_key="test-real-key", understanding_mode="hybrid"), mcp_tool_client=Tools())
        service._context_llm = Model()
        result = await service.understand_context(
            "先查积分", [], "order_query", {}, "order_query",
            {"tool": "order_query", "arguments": {"orderId": "ORDER_123456"}, "pending": None, "frames": []},
        )
        assert len(calls) == 1
        assert calls[0]["context"]["arguments"]["orderId"] == "ORDER_123456"
        assert result.dialogue_act == "interrupt"
        assert result.tool_name == "points_query"
    asyncio.run(scenario())


def test_context_model_failure_keeps_ambiguous_input_from_keyword_execution():
    async def scenario():
        calls = []

        class Model:
            async def ainvoke(self, messages):
                calls.append(1)
                raise TimeoutError()

        service = UnderstandingService(Settings(understanding_api_key="test-real-key", understanding_mode="hybrid"), mcp_tool_client=Tools())
        service._context_llm = Model()
        result = await service.understand_context("不是订单号 ORDER_123456", [], "order_query", {}, "order_query", {"frames": []})
        assert len(calls) == 1
        assert result.intent == "unknown"
        assert result.needs_clarification
    asyncio.run(scenario())


def test_request_with_uncertain_outcome_is_not_reexecuted():
    async def scenario():
        store = InMemorySessionStore()
        repository = InMemoryChatRepository()
        service = ChatApplicationService(Settings(demo_user_id="u"), store, repository)
        import hashlib
        await store.save_receipt(receipt_key("s", "u", "r"), {
            "status": "processing", "fingerprint": hashlib.sha256("查订单".encode()).hexdigest(),
        })
        with pytest.raises(DialogueConflictError):
            await service.chat(ChatRequest(message="查订单", session_id="s", request_id="r"))
        assert not repository.messages
    asyncio.run(scenario())


def test_session_lock_is_reentrant_and_released_on_cancellation():
    async def scenario():
        store = InMemorySessionStore()
        entered = asyncio.Event()

        async def blocked():
            async with store.lock("s"):
                async with store.lock("s"):
                    entered.set()
                    await asyncio.Event().wait()

        task = asyncio.create_task(blocked())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with store.lock("s"):
            pass
        assert not store._locks.entries
    asyncio.run(scenario())


def test_invalid_referenced_correction_does_not_mutate_current_task():
    tools = Tools()
    manager = DialogueManager(None, tools, ToolArgumentResolver())
    state = ConversationState(session_id="s", active_tool="points_query", tool_status="awaiting_args")
    state.dialogue.frame_id = "points"
    state.dialogue.recent.append(TaskFrame(id="order", tool="order_query", arguments={"orderId": "ORDER_OLD123"}, saved_at=time.time()))
    before = state.to_dict()
    result = manager.apply_interpretation("更正那个订单", state, plan(act="correct", target_frame_id="order", values={"orderId": "HALLUCINATED"}))
    assert result.dialogue_answer
    assert state.to_dict() == before


def test_write_timeout_does_not_allow_another_submission():
    async def scenario():
        class FailingTools(Tools):
            async def call_tool(self, name, arguments, **context):
                self.calls.append((name, dict(arguments), context))
                return ToolResult.failed(name, "timeout", "TimeoutError")

        tools = FailingTools()
        agent = agent_for(Interpreter(plan("change_order", values={"orderId": "ORDER_123456"})), tools)
        first = await agent.handle("修改 ORDER_123456", None, [])
        await agent.handle("确认提交", first.session_id, [])
        response = await agent.handle("确认提交", first.session_id, [])
        assert "尚未确认" in response.answer
        assert len(tools.calls) == 1
    asyncio.run(scenario())


def test_same_session_requests_are_serialized_without_lost_turns():
    async def scenario():
        agent = agent_for(Interpreter())
        responses = await asyncio.gather(*(agent.handle("你好", "s", []) for _ in range(10)))
        assert len(responses) == 10
        state = await agent.orchestrator.session_store.get_or_create("s")
        assert state.turn_count == 10
    asyncio.run(scenario())


def test_schema_enum_question_is_displayed_and_selected_without_model():
    async def scenario():
        tools = Tools()
        tools.definitions["choose_method"] = McpToolDefinition("choose_method", "选择售后方式", {
            "type": "object", "properties": {"method": {"type": "string", "enum": ["仅退款", "退货退款"]}},
            "required": ["method"],
        })
        interpreter = Interpreter(plan("choose_method"))
        agent = agent_for(interpreter, tools)
        first = await agent.handle("选择售后方式", None, [])
        assert "1. 仅退款" in first.answer
        assert "2. 退货退款" in first.answer
        await agent.handle("第二个", first.session_id, [])
        assert tools.calls[0][1] == {"method": "退货退款"}
        assert len(interpreter.calls) == 1
    asyncio.run(scenario())


def test_slow_catalog_falls_back_to_cached_schema_before_model_call():
    async def scenario():
        class SlowTools(Tools):
            async def candidate_catalog(self, *args):
                await asyncio.Event().wait()

        class Model:
            calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return {"act": "start", "target": "order_query", "values": {}, "query": None}

        service = UnderstandingService(Settings(understanding_api_key="test-real-key", context_candidate_timeout_seconds=0.01), mcp_tool_client=SlowTools())
        model = Model()
        service._context_llm = model
        result = await asyncio.wait_for(service.understand_context("查订单", [], None, {}, None, {"frames": []}), timeout=1)
        assert result.tool_name == "order_query"
        assert model.calls == 1
    asyncio.run(scenario())


def test_mcp_boundary_converts_scalars_and_overrides_untrusted_identity():
    async def scenario():
        from types import SimpleNamespace
        from app.tools.mcp_client import McpToolClient
        client = McpToolClient(Settings(tool_retrieval_enabled=False), None)
        client._tools["test"] = McpToolDefinition("test", "test", {
            "type": "object", "properties": {
                "count": {"type": "integer", "minimum": 1}, "confirmed": {"type": "boolean"},
                "sessionId": {"type": "string"}, "userId": {"type": "string"}, "requestId": {"type": "string"},
            }, "required": ["count", "confirmed", "sessionId", "userId", "requestId"],
        })
        calls = []

        class Session:
            async def call_tool(self, name, arguments):
                calls.append(arguments)
                return SimpleNamespace(structuredContent={"answer": "ok"}, isError=False)

        client._session = Session()
        result = await client.call_tool("test", {"count": "2", "confirmed": "true", "userId": "attacker"}, session_id="s", user_id="owner", request_id="r")
        assert result.success
        assert calls[0]["count"] == 2
        assert calls[0]["confirmed"] is True
        assert calls[0]["userId"] == "owner"
        failed = await client.call_tool("test", {"count": "-1", "confirmed": "true"}, session_id="s", user_id="owner", request_id="r2")
        assert not failed.success
        assert len(calls) == 1
    asyncio.run(scenario())


def test_deepseek_context_request_disables_default_thinking():
    from langchain_core.messages import HumanMessage
    service = UnderstandingService(Settings(
        understanding_api_key="test-key", understanding_base_url="https://api.deepseek.com",
        understanding_model="deepseek-v4-flash",
    ))
    payload = service._get_llm()._get_request_payload([HumanMessage(content="测试")])
    assert payload["reasoning"] == {"effort": "none"}
    assert service._get_llm().max_retries == 0
