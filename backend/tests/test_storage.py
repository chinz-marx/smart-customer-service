import asyncio
from datetime import timedelta

from app.chat_service import ChatApplicationService
from app.config import Settings
from app.persistence.domain import ConversationRecord, utc_now
from app.persistence.repository import InMemoryChatRepository
from app.schemas import ChatRequest, FeedbackRequest
from app.session.store import ConversationState, InMemorySessionStore
from app.slots.schemas import SlotValue


class BlockingChatRepository(InMemoryChatRepository):
    """模拟PostgreSQL首个查询变慢，用于验证快速回复首包不等待持久化。"""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def get_or_create_conversation(self, *args, **kwargs):
        self.started.set()
        await self.release.wait()
        return await super().get_or_create_conversation(*args, **kwargs)


class BlockingSessionStore(InMemorySessionStore):
    """模拟Redis读取变慢，用于验证快速回复首包不等待会话状态。"""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def get_or_create(self, *args, **kwargs):
        self.started.set()
        await self.release.wait()
        return await super().get_or_create(*args, **kwargs)


def _quick_reply_settings(user_id: str) -> Settings:
    return Settings(
        doubao_api_key="YOUR_TEST_KEY",
        session_store_backend="memory",
        persistence_backend="memory",
        demo_user_id=user_id,
        nacos_enabled=False,
        mcp_enabled=False,
    )


def test_conversation_state_json_round_trip() -> None:
    """Redis序列化后应完整保留意图、槽位和关联ID。"""
    state = ConversationState(
        session_id="session-1",
        conversation_id="conversation-1",
        user_id="user-1",
        current_intent="reward_not_received",
        active_tool="reward_query",
        tool_status="awaiting_args",
        tool_arguments={"rewardNo": "REWARD_123456"},
        last_tool="order_query",
        slots={
            "order_id": SlotValue(
                value="123456789",
                confidence=0.95,
                source_text="订单号是123456789",
            )
        },
        turn_count=2,
    )

    restored = ConversationState.from_dict(state.to_dict())

    assert restored.session_id == state.session_id
    assert restored.conversation_id == state.conversation_id
    assert restored.current_intent == "reward_not_received"
    assert restored.active_tool == "reward_query"
    assert restored.tool_status == "awaiting_args"
    assert restored.tool_arguments == {"rewardNo": "REWARD_123456"}
    assert restored.last_tool == "order_query"
    assert restored.slots["order_id"].value == "123456789"
    assert restored.turn_count == 2


def test_memory_storage_keeps_chat_active_when_human_is_unavailable() -> None:
    """人工功能未启用时只返回忙碌提示，不创建工单或锁定当前会话。"""

    async def scenario() -> None:
        settings = Settings(
            doubao_api_key="YOUR_TEST_KEY",
            session_store_backend="memory",
            persistence_backend="memory",
            demo_user_id="test-user",
        )
        session_store = InMemorySessionStore()
        repository = InMemoryChatRepository()
        await session_store.initialize()
        await repository.initialize()
        service = ChatApplicationService(settings, session_store, repository)

        response = await service.chat(ChatRequest(message="我要转人工"))

        assert response.conversation_id
        assert response.message_id
        assert response.ticket_id is None
        assert len(repository.conversations) == 1
        await service.list_messages(response.conversation_id)
        assert len(repository.messages) == 2
        assert len(repository.tickets) == 0

        feedback = await service.save_feedback(
            FeedbackRequest(
                conversation_id=response.conversation_id,
                message_id=response.message_id,
                feedback_type="unhelpful",
                rating=2,
                comment="还需要人工处理",
            )
        )
        assert feedback.feedback_type == "unhelpful"
        assert feedback.rating == 2
        assert len(repository.feedback) == 1

        conversations = await service.list_conversations()
        messages = await service.list_messages(response.conversation_id)
        assert conversations[0].status == "active"
        assert [message.role for message in messages] == ["user", "assistant"]

    asyncio.run(scenario())


def test_memory_storage_keeps_multi_turn_conversation() -> None:
    """第二轮提供槽位时应复用同一个Redis会话和PostgreSQL对话。"""

    async def scenario() -> None:
        settings = Settings(
            doubao_api_key="YOUR_TEST_KEY",
            session_store_backend="memory",
            persistence_backend="memory",
            demo_user_id="test-user",
        )
        session_store = InMemorySessionStore()
        repository = InMemoryChatRepository()
        service = ChatApplicationService(settings, session_store, repository)

        first = await service.chat(ChatRequest(message="我的奖励还没到账"))
        second = await service.chat(
            ChatRequest(
                message="订单号是 123456789",
                session_id=first.session_id,
                conversation_id=first.conversation_id,
            )
        )

        assert second.session_id == first.session_id
        assert second.conversation_id == first.conversation_id
        assert "奖励正在处理中" in second.answer
        messages = await service.list_messages(first.conversation_id)
        assert len(messages) == 4

    asyncio.run(scenario())


def test_quick_reply_stream_does_not_wait_for_postgres() -> None:
    """PostgreSQL变慢时，“你好”的delta仍应先到，随后再发送持久化元数据。"""

    async def scenario() -> None:
        repository = BlockingChatRepository()
        service = ChatApplicationService(
            _quick_reply_settings("slow-postgres-user"),
            InMemorySessionStore(),
            repository,
        )
        stream = service.chat_stream(ChatRequest(message="你好"))

        first_event = await asyncio.wait_for(anext(stream), timeout=0.2)
        assert first_event.startswith("event: delta\n")
        assert "智能客服小智" in first_event

        await asyncio.wait_for(repository.started.wait(), timeout=0.2)
        assert not repository.conversations
        repository.release.set()

        remaining = [event async for event in stream]
        assert remaining[-1].startswith("event: done\n")
        assert len(repository.conversations) == 1
        assert len(repository.messages) == 2

    asyncio.run(scenario())


def test_quick_reply_stream_does_not_wait_for_redis() -> None:
    """Redis读取变慢时，“你好”的delta仍应先到，完成事件等待会话刷新成功。"""

    async def scenario() -> None:
        session_store = BlockingSessionStore()
        repository = InMemoryChatRepository()
        service = ChatApplicationService(
            _quick_reply_settings("slow-redis-user"),
            session_store,
            repository,
        )
        request = ChatRequest(message="你好", session_id="slow-redis-session")
        stream = service.chat_stream(request)

        first_event = await asyncio.wait_for(anext(stream), timeout=0.2)
        assert first_event.startswith("event: delta\n")
        assert "智能客服小智" in first_event

        await asyncio.wait_for(session_store.started.wait(), timeout=0.2)
        assert "slow-redis-session" not in session_store._sessions
        session_store.release.set()

        remaining = [event async for event in stream]
        assert remaining[-1].startswith("event: done\n")
        assert session_store._sessions["slow-redis-session"].turn_count == 1
        assert len(repository.messages) == 2

    asyncio.run(scenario())


def test_conversation_history_only_returns_last_three_days() -> None:
    """历史列表按最后更新时间过滤，旧数据仍保留在仓储中。"""

    async def scenario() -> None:
        settings = Settings(
            doubao_api_key="YOUR_TEST_KEY",
            session_store_backend="memory",
            persistence_backend="memory",
            demo_user_id="test-user",
        )
        repository = InMemoryChatRepository()
        now = utc_now()
        recent = ConversationRecord(
            id="recent",
            user_id="test-user",
            session_id="recent-session",
            title="近三天会话",
            updated_at=now - timedelta(days=2),
        )
        expired = ConversationRecord(
            id="expired",
            user_id="test-user",
            session_id="expired-session",
            title="超过三天会话",
            updated_at=now - timedelta(days=3, seconds=1),
        )
        repository.conversations = {recent.id: recent, expired.id: expired}
        service = ChatApplicationService(settings, InMemorySessionStore(), repository)

        conversations = await service.list_conversations()

        assert [item.id for item in conversations] == ["recent"]
        assert "expired" in repository.conversations

    asyncio.run(scenario())
