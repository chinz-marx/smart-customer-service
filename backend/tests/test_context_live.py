"""Real context model smoke tests; no real business operations. Explicit opt-in."""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.dialogue.schemas import PendingQuestion, TaskFrame
from app.session.store import ConversationState, InMemorySessionStore
from app.understanding.service import UnderstandingService
from test_dialogue import Tools
from test_mcp_composite import FakeSemanticAnswerService

pytestmark = pytest.mark.live_llm


class RecordingUnderstanding(UnderstandingService):
    def __init__(self, settings, tools):
        super().__init__(settings, mcp_tool_client=tools)
        self.outputs = []

    async def understand_context(self, **kwargs):
        result = await super().understand_context(**kwargs)
        self.outputs.append(result)
        return result


def test_live_context_routing_and_multiturn():
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("requires RUN_LIVE_LLM_TESTS=1")

    async def scenario():
        settings = Settings(understanding_mode="llm", understanding_temperature=0.0, doubao_api_key="YOUR_TEST_KEY")
        assert settings.has_real_understanding_api_key, "UNDERSTANDING_API_KEY is not configured"
        tools = Tools()
        understanding = RecordingUnderstanding(settings, tools)
        rows = []

        def blank():
            return ConversationState(session_id="live-test", user_id="live-test-user")

        def pending(tool="order_query", args=None):
            state = blank()
            state.active_tool = state.current_intent = tool
            state.tool_status = "awaiting_args"
            state.tool_arguments = args or {}
            state.dialogue.frame_id = "active-frame"
            state.dialogue.pending = PendingQuestion(field="orderId", answer="请提供订单号。")
            return state

        resume = blank()
        resume.dialogue.suspended = [TaskFrame(id="suspended-order", tool="order_query", saved_at=time.time(), pending=PendingQuestion(field="orderId", answer="请提供订单号。"))]
        followup = blank()
        followup.dialogue.recent = [TaskFrame(id="last-order", tool="order_query", arguments={"orderId": "ORDER_123456"}, saved_at=time.time())]
        ambiguous = blank()
        ambiguous.dialogue.recent = [
            TaskFrame(id="order-a", tool="order_query", arguments={"orderId": "ORDER_123456"}, saved_at=time.time()),
            TaskFrame(id="order-b", tool="order_query", arguments={"orderId": "SHOP_778899"}, saved_at=time.time()),
        ]
        confirmation = pending("change_order", {"orderId": "ORDER_123456"})
        confirmation.dialogue.pending = PendingQuestion(kind="confirmation", field="confirmed", answer="是否确认提交订单变更？")
        cases = [
            ("new_task", "帮我查一下订单现在到哪了", blank(), 1, "ask_slot", "order_query", None),
            ("knowledge", "退款一般需要满足什么条件？", blank(), 1, "generate", None, None),
            ("bare_fill", "ORDER_123456", pending(), 0, "generate", None, {"orderId": "ORDER_123456"}),
            ("natural_fill", "我终于找到了，单号是 ORDER_123456，麻烦帮我看看", pending(), 1, "generate", None, {"orderId": "ORDER_123456"}),
            ("correction", "不是订单号 ORDER_123456，是 SHOP_778899，刚才说错了", pending(), 1, "generate", None, {"orderId": "SHOP_778899"}),
            ("interrupt", "订单先放一下，我想先查积分，等会儿再继续查订单", pending(), 1, "ask_slot", "points_query", None),
            ("resume", "接着处理刚刚暂停的那个订单查询吧", resume, 1, "ask_slot", "order_query", None),
            ("reference", "刚才那笔订单，再帮我查一次进度", followup, 1, "generate", None, {"orderId": "ORDER_123456"}),
            ("ambiguous", "查一下其中一个订单，我还没决定查哪个", ambiguous, 1, "clarify", None, None),
            ("no_consent", "我只是问问，并没有确认提交", confirmation, 1, "clarify", None, None),
        ]
        for name, message, initial, expected_calls, action, active, arguments in cases:
            store = InMemorySessionStore()
            await store.save(initial)
            agent = CustomerServiceAgent(settings, session_store=store, understanding_service=understanding,
                                         mcp_tool_client=tools, semantic_answer_service=FakeSemanticAnswerService())
            async def forbid_answer_model(*args, **kwargs):
                raise AssertionError("Unexpected answer-model call in context-only smoke test")
            agent.orchestrator.answer_generator.generate = forbid_answer_model
            before = len(understanding.outputs)
            tools.calls.clear()
            started = time.perf_counter()
            checks = []
            row = {"case": name, "message": message}
            try:
                result = await agent.handle(message, initial.session_id, [], user_id="live-test-user")
                state = await store.get_or_create(initial.session_id, user_id="live-test-user")
                actual_calls = len(understanding.outputs) - before
                output = understanding.outputs[-1] if actual_calls else None
                if actual_calls != expected_calls:
                    checks.append(f"model_calls:{actual_calls}!={expected_calls}")
                if expected_calls and (output is None or output.source != "llm"):
                    checks.append("real_model_did_not_return_valid_output")
                if result.decision_action != action:
                    checks.append(f"action:{result.decision_action}!={action}")
                if active and state.active_tool != active:
                    checks.append(f"active_tool:{state.active_tool}!={active}")
                if arguments is not None and (len(tools.calls) != 1 or tools.calls[0][1] != arguments):
                    checks.append("unexpected_tool_arguments")
                if arguments is None and tools.calls:
                    checks.append("unexpected_business_call")
                if name == "interrupt" and len(state.dialogue.suspended) != 1:
                    checks.append("original_task_not_suspended")
                row.update({"model_calls": actual_calls, "source": output.source if output else "rule",
                            "act": output.dialogue_act if output else "inform", "action": result.decision_action,
                            "active_tool": state.active_tool, "tool_calls": len(tools.calls),
                            "parsed_values": output.tool_arguments if output else {},
                            "target_frame": output.target_frame_id if output else None})
            except Exception as exc:
                checks.append(type(exc).__name__)
            row.update({"latency_ms": round((time.perf_counter() - started) * 1000, 2), "passed": not checks, "failures": checks})
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        report = {"model": settings.effective_understanding_model, "timeout_seconds": settings.understanding_timeout_seconds,
                  "reasoning": understanding._get_llm().reasoning,
                  "prompt_source": understanding.prompt_registry.source, "business_tools": "test doubles",
                  "passed": sum(r["passed"] for r in rows), "total": len(rows), "cases": rows}
        destination = Path("evaluation/reports") / f"context-live-{stamp}.json"
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"REPORT={destination}", flush=True)
        assert all(r["passed"] for r in rows), json.dumps([{"case": r["case"], "failures": r["failures"]} for r in rows if not r["passed"]], ensure_ascii=False)

    asyncio.run(scenario())
