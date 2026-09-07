import asyncio
import json

from app.chat_service import ChatApplicationService
from app.config import Settings
from app.persistence.repository import InMemoryChatRepository
from app.schemas import ChatRequest, FeedbackRequest
from app.session.store import InMemorySessionStore
from test_dialogue import Interpreter, Tools, plan
from test_mcp_composite import FakeSemanticAnswerService


def make_service(store, repository, interpreter, tools):
    service = ChatApplicationService(
        Settings(understanding_mode="keyword", doubao_api_key="YOUR_TEST_KEY"),
        store, repository, mcp_tool_client=tools,
        semantic_answer_service=FakeSemanticAnswerService(),
    )
    service.agent.orchestrator.dialogue_manager.understanding = interpreter
    return service


def test_blocked_user_write_does_not_block_reply_but_serializes_next_worker():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class SlowRepository(InMemoryChatRepository):
            async def add_message(self, **kwargs):
                if kwargs["role"] == "user":
                    entered.set()
                    await release.wait()
                return await super().add_message(**kwargs)

        class CountingStore(InMemorySessionStore):
            reads = 0
            async def get_or_create(self, *args, **kwargs):
                self.reads += 1
                return await super().get_or_create(*args, **kwargs)

        store, repository, interpreter, tools = CountingStore(), SlowRepository(), Interpreter(plan()), Tools()
        first = make_service(store, repository, interpreter, tools)
        second = make_service(store, repository, interpreter, tools)
        next_turn = None
        try:
            # Even SSE done is sent while the first message insert is blocked.
            events = await asyncio.wait_for(
                collect(first.chat_stream(ChatRequest(message="查订单", session_id="background"))), 1,
            )
            assert entered.is_set()
            assert not repository.messages
            assert "订单号" in events[0]
            assert events[-1].startswith("event: done\n")
            response = json.loads(events[-1].split("data: ", 1)[1])
            assert store.reads == 1  # Same snapshot reaches the orchestrator.
            assert interpreter.calls[0]["message"] == "查订单"

            next_turn = asyncio.create_task(second.chat(ChatRequest(
                message="ORDER_123456", session_id="background",
                conversation_id=response["conversation_id"],
            )))
            await asyncio.sleep(0)
            assert not next_turn.done()
            assert not tools.calls
            release.set()
            result = await asyncio.wait_for(next_turn, 2)
            assert result.provider == "tool:order_query"
            await first.close()
            await second.close()
            rows = await repository.list_messages(response["conversation_id"], first.settings.demo_user_id)
            assert [r.role for r in rows] == ["user", "assistant", "user", "assistant"]
            assert rows[1].id == response["message_id"]
            assert store.reads == 2
            assert len(interpreter.calls) == 1
            assert tools.calls[0][1] == {"orderId": "ORDER_123456"}
        finally:
            release.set()
            if next_turn:
                await next_turn
            await first.close()
            await second.close()
    asyncio.run(scenario())


def test_immediate_feedback_and_shutdown_wait_for_background_answer():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class SlowRepository(InMemoryChatRepository):
            async def add_message(self, **kwargs):
                if kwargs["role"] == "assistant":
                    entered.set()
                    await release.wait()
                return await super().add_message(**kwargs)

        store, repository = InMemorySessionStore(), SlowRepository()
        service = make_service(store, repository, Interpreter(plan()), Tools())
        feedback_task = None
        try:
            response = await asyncio.wait_for(service.chat(ChatRequest(message="查订单")), 1)
            await asyncio.wait_for(entered.wait(), 1)
            assert response.message_id not in repository.messages
            feedback_task = asyncio.create_task(service.save_feedback(FeedbackRequest(
                conversation_id=response.conversation_id, message_id=response.message_id,
                feedback_type="helpful",
            )))
            closing = asyncio.create_task(service.close())
            await asyncio.sleep(0)
            assert not feedback_task.done()
            assert not closing.done()
            release.set()
            feedback = await asyncio.wait_for(feedback_task, 2)
            await asyncio.wait_for(closing, 2)
            assert feedback.message_id == response.message_id
            assert response.message_id in repository.messages
        finally:
            release.set()
            if feedback_task:
                await feedback_task
            await service.close()
    asyncio.run(scenario())


async def collect(stream):
    return [event async for event in stream]
