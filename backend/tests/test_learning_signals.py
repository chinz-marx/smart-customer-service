import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.chat_service import ChatApplicationService
from app.config import Settings
from app.learning.domain import LearningSignalType, PendingLearningSignal
from app.learning.repository import InMemoryLearningRepository
from app.learning.scheduler import LearningDailyScheduler
from app.learning.service import LearningJobResult, LearningSignalProcessor
from app.orchestrator import ChatOrchestrationResult
from app.persistence.repository import InMemoryChatRepository
from app.schemas import ChatRequest, FeedbackRequest
from app.session.store import InMemorySessionStore


def _service() -> tuple[ChatApplicationService, InMemoryLearningRepository]:
    settings = Settings(
        doubao_api_key="YOUR_TEST_KEY",
        understanding_api_key="YOUR_TEST_KEY",
        persistence_backend="memory",
        session_store_backend="memory",
        learning_enabled=True,
        demo_user_id="learning-test-user",
    )
    learning = InMemoryLearningRepository()
    service = ChatApplicationService(
        settings,
        InMemorySessionStore(),
        InMemoryChatRepository(),
        learning_repository=learning,
    )
    return service, learning


def test_unhelpful_and_negative_rating_keep_two_evidences() -> None:
    """同一回答可以同时拥有没帮助和差评证据，但后续数据库按消息去重统计。"""

    async def scenario() -> None:
        service, learning = _service()
        response = await service.chat(ChatRequest(message="你好"))
        await service.save_feedback(FeedbackRequest(
            conversation_id=response.conversation_id or "",
            message_id=response.message_id or "",
            feedback_type="unhelpful",
            rating=2,
            comment="没有回答我的问题",
        ))

        assert {item.source_type for item in learning.signals} == {
            LearningSignalType.UNHELPFUL,
            LearningSignalType.NEGATIVE_RATING,
        }
        assert all(item.question_text == "你好" for item in learning.signals)

    asyncio.run(scenario())


def test_chat_signal_scope_only_contains_confirmed_sources() -> None:
    """本期不收集普通unknown和连续澄清，只接受已确认的四种聊天侧来源。"""
    service, _ = _service()
    result = ChatOrchestrationResult(
        answer="暂时无法完成查询",
        session_id="session-1",
        provider="test",
        suggestions=[],
        intent="complaint",
        intent_confidence=0.95,
        decision_action="generate",
        decision_reason="ready_for_answer",
        latency_ms=10,
        tool_name="order_query",
        tool_success=False,
        tool_error_code="TOOL_TIMEOUT",
        knowledge_requested=True,
        knowledge_attempted=True,
        knowledge_hit=False,
    )

    signals = service._chat_learning_signals(
        result=result,
        user_id="user-1",
        conversation_id="conversation-1",
        user_message_id="user-message-1",
        assistant_message_id="assistant-message-1",
        question="我要投诉，订单也查不到",
        answer=result.answer,
        ticket_id=None,
    )

    assert {item.source_type for item in signals} == {
        LearningSignalType.COMPLAINT,
        LearningSignalType.TOOL_FAILURE,
        LearningSignalType.RAG_MISS,
    }


class _BatchLearningRepository:
    """模拟数据库的原子领取行为，避免单元测试依赖真实PostgreSQL。"""

    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.pending = [
            PendingLearningSignal(
                id=1,
                source_type=LearningSignalType.UNHELPFUL,
                conversation_id="conversation-1",
                trigger_message_id="message-1",
                user_id="user-1",
                question_text="回答没有帮助",
                answer_text="旧回答",
                intent_code="refund_policy",
                occurred_at=now,
            ),
            PendingLearningSignal(
                id=2,
                source_type=LearningSignalType.TOOL_FAILURE,
                conversation_id="conversation-2",
                trigger_message_id="message-2",
                user_id="user-2",
                question_text="向量生成失败",
                answer_text="旧回答",
                intent_code="refund_policy",
                occurred_at=now,
            ),
        ]
        self.completed: list[int] = []
        self.failed: list[int] = []

    async def recover_stale(self, stale_after_minutes: int) -> int:
        assert stale_after_minutes == 30
        return 1

    async def claim_pending(self, limit: int) -> list[PendingLearningSignal]:
        claimed, self.pending = self.pending[:limit], self.pending[limit:]
        return claimed

    async def complete(
        self,
        signal,
        embedding,
        embedding_model,
        distance_threshold,
        review_occurrence_threshold,
        review_user_threshold,
    ) -> int:
        assert len(embedding) == 2048
        assert review_occurrence_threshold == 3
        assert review_user_threshold == 2
        self.completed.append(signal.id)
        return 100 + signal.id

    async def fail(self, signal_id: int, error_message: str, max_retries: int) -> None:
        assert max_retries == 3
        self.failed.append(signal_id)


class _FakeEmbedding:
    async def embed(self, text: str) -> list[float]:
        if "失败" in text:
            raise RuntimeError("模拟Embedding故障")
        return [0.1] * 2048

    async def close(self) -> None:
        return None


def test_python_learning_job_aggregates_batch_result() -> None:
    """一次Python任务应返回可审计的领取、成功、失败与恢复数量。"""

    async def scenario() -> None:
        repository = _BatchLearningRepository()
        processor = LearningSignalProcessor(
            Settings(learning_embedding_concurrency=2), repository
        )
        processor.embedding = _FakeEmbedding()

        result = await processor.process_job(max_batches=10, batch_size=2)

        assert result == LearningJobResult(
            claimed=2, succeeded=1, failed=1, recovered=1, batches=1
        )
        assert repository.completed == [1]
        assert repository.failed == [2]
        await processor.close()

    asyncio.run(scenario())


class _SchedulerProcessor:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def process_job(self, max_batches: int, batch_size: int) -> LearningJobResult:
        self.calls.append((max_batches, batch_size))
        return LearningJobResult(
            claimed=20, succeeded=20, failed=0, recovered=2, batches=1
        )


def test_python_daily_scheduler_runs_once_with_configured_batch() -> None:
    """获得分布式锁的Python实例按照配置批量执行。"""

    async def scenario() -> None:
        settings = Settings(
            learning_max_batches=5,
            learning_batch_size=20,
            learning_schedule_timezone="Asia/Shanghai",
            learning_schedule_hour=3,
            learning_schedule_minute=0,
        )
        repository = InMemoryLearningRepository()
        processor = _SchedulerProcessor()
        scheduler = LearningDailyScheduler(settings, repository, processor)

        result = await scheduler.run_once()

        assert result is not None
        assert result.succeeded == 20
        assert processor.calls == [(5, 20)]

    asyncio.run(scenario())


def test_python_daily_scheduler_skips_when_another_instance_holds_lock() -> None:
    """另一个实例已持有任务锁时，本实例应立即跳过而不是重复聚类。"""

    async def scenario() -> None:
        settings = Settings(learning_schedule_timezone="Asia/Shanghai")
        repository = InMemoryLearningRepository()
        processor = _SchedulerProcessor()
        scheduler = LearningDailyScheduler(settings, repository, processor)

        async with repository.daily_job_lock() as acquired:
            assert acquired is True
            result = await scheduler.run_once()

        assert result is None
        assert processor.calls == []

    asyncio.run(scenario())


def test_python_daily_scheduler_calculates_next_three_am() -> None:
    settings = Settings(
        learning_schedule_timezone="Asia/Shanghai",
        learning_schedule_hour=3,
        learning_schedule_minute=0,
    )
    scheduler = LearningDailyScheduler(
        settings, InMemoryLearningRepository(), _SchedulerProcessor()
    )
    timezone = ZoneInfo("Asia/Shanghai")

    before = scheduler.next_run_time(datetime(2026, 8, 12, 2, 30, tzinfo=timezone))
    after = scheduler.next_run_time(datetime(2026, 8, 12, 3, 30, tzinfo=timezone))

    assert before == datetime(2026, 8, 12, 3, 0, tzinfo=timezone)
    assert after == datetime(2026, 8, 13, 3, 0, tzinfo=timezone)
