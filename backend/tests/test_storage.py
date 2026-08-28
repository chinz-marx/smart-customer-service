import asyncio

from app.chat_service import ChatApplicationService
from app.config import Settings
from app.persistence.repository import InMemoryChatRepository
from app.schemas import ChatRequest, FeedbackRequest
from app.session.store import ConversationState, InMemorySessionStore
from app.slots.schemas import SlotValue


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


def test_memory_storage_completes_chat_feedback_and_ticket_flow() -> None:
    """没有安装Redis和PostgreSQL时，内存模式也能跑完整数据闭环。"""

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
        assert response.ticket_id
        assert len(repository.conversations) == 1
        assert len(repository.messages) == 2
        assert len(repository.tickets) == 1
        assert repository.tickets[response.ticket_id].context_snapshot["intent"] == "human_handoff"

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
        assert conversations[0].status == "handoff"
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
