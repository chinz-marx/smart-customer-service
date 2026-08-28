from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.learning.domain import LearningSignalCreate, LearningSignalType, PendingLearningSignal


class LearningRepository(Protocol):
    """问题学习持久化接口；内存测试和 PostgreSQL 使用同一套调用方式。"""

    async def initialize(self) -> None: ...
    async def add_signals(self, signals: Sequence[LearningSignalCreate]) -> int: ...
    async def claim_pending(self, limit: int) -> list[PendingLearningSignal]: ...
    async def recover_stale(self, stale_after_minutes: int) -> int: ...
    def daily_job_lock(self) -> AbstractAsyncContextManager[bool]: ...
    async def complete(
        self,
        signal: PendingLearningSignal,
        embedding: list[float],
        embedding_model: str,
        distance_threshold: float,
        review_occurrence_threshold: int,
        review_user_threshold: int,
    ) -> int: ...
    async def fail(self, signal_id: int, error_message: str, max_retries: int) -> None: ...
    async def close(self) -> None: ...


class DisabledLearningRepository:
    """功能关闭时的空实现，聊天主流程无需散落开关判断。"""

    async def initialize(self) -> None: pass
    async def add_signals(self, signals: Sequence[LearningSignalCreate]) -> int: return 0
    async def claim_pending(self, limit: int) -> list[PendingLearningSignal]: return []
    async def recover_stale(self, stale_after_minutes: int) -> int: return 0
    @asynccontextmanager
    async def daily_job_lock(self):
        yield False
    async def complete(
        self,
        signal: PendingLearningSignal,
        embedding: list[float],
        embedding_model: str,
        distance_threshold: float,
        review_occurrence_threshold: int,
        review_user_threshold: int,
    ) -> int: return 0
    async def fail(self, signal_id: int, error_message: str, max_retries: int) -> None: pass
    async def close(self) -> None: pass


class InMemoryLearningRepository:
    """不连接数据库的可观察实现，供单元测试验证收集范围。"""

    def __init__(self) -> None:
        self.signals: list[LearningSignalCreate] = []
        self._daily_lock = asyncio.Lock()

    async def initialize(self) -> None: pass

    async def add_signals(self, signals: Sequence[LearningSignalCreate]) -> int:
        existing = {item.signal_key for item in self.signals}
        fresh = [item for item in signals if item.signal_key not in existing]
        self.signals.extend(fresh)
        return len(fresh)

    async def claim_pending(self, limit: int) -> list[PendingLearningSignal]: return []
    async def recover_stale(self, stale_after_minutes: int) -> int: return 0
    @asynccontextmanager
    async def daily_job_lock(self):
        """测试环境模拟非阻塞分布式锁，已有任务运行时直接跳过。"""
        if self._daily_lock.locked():
            yield False
            return
        await self._daily_lock.acquire()
        try:
            yield True
        finally:
            self._daily_lock.release()
    async def complete(
        self,
        signal: PendingLearningSignal,
        embedding: list[float],
        embedding_model: str,
        distance_threshold: float,
        review_occurrence_threshold: int,
        review_user_threshold: int,
    ) -> int: return 0
    async def fail(self, signal_id: int, error_message: str, max_retries: int) -> None: pass
    async def close(self) -> None: pass


class PostgresLearningRepository:
    """通过参数化 SQL 使用 pgvector，避免手工拼接用户文本。"""

    def __init__(self, database_url: str, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url, echo=echo, pool_pre_ping=True, pool_size=3, max_overflow=2
        )

    async def initialize(self) -> None:
        async with self.engine.connect() as connection:
            extension = await connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
            halfvec = await connection.scalar(text("SELECT to_regtype('halfvec')::text"))
            table_name = await connection.scalar(text("SELECT to_regclass('learning.learning_signal')::text"))
            if not extension or halfvec != "halfvec":
                raise RuntimeError("PostgreSQL vector扩展或halfvec类型不可用")
            if table_name != "learning.learning_signal":
                raise RuntimeError("问题学习表尚未创建，请先执行Java Flyway V8迁移")

    async def add_signals(self, signals: Sequence[LearningSignalCreate]) -> int:
        if not signals:
            return 0
        statement = text("""
            INSERT INTO learning.learning_signal (
                signal_key, source_type, source_id, conversation_id,
                trigger_message_id, target_assistant_message_id, user_id,
                question_text, answer_text, intent_code, confidence,
                tool_name, failure_code
            ) VALUES (
                :signal_key, :source_type, :source_id, :conversation_id,
                :trigger_message_id, :target_assistant_message_id, :user_id,
                :question_text, :answer_text, :intent_code, :confidence,
                :tool_name, :failure_code
            ) ON CONFLICT (signal_key) DO NOTHING
        """)
        rows = []
        for item in signals:
            row = asdict(item)
            row["source_type"] = int(item.source_type)
            rows.append(row)
        async with self.engine.begin() as connection:
            result = await connection.execute(statement, rows)
            return max(result.rowcount or 0, 0)

    async def claim_pending(self, limit: int) -> list[PendingLearningSignal]:
        statement = text("""
            WITH claimed AS (
                SELECT id FROM learning.learning_signal
                WHERE process_status IN (0, 3) AND next_retry_at <= CURRENT_TIMESTAMP
                ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED
            )
            UPDATE learning.learning_signal AS signal
            SET process_status = 1,
                processing_started_at = CURRENT_TIMESTAMP,
                error_message = NULL
            FROM claimed WHERE signal.id = claimed.id
            RETURNING signal.id, signal.source_type, signal.conversation_id, signal.trigger_message_id,
                      signal.user_id, signal.question_text, signal.answer_text,
                      signal.intent_code, signal.occurred_at
        """)
        async with self.engine.begin() as connection:
            rows = (await connection.execute(statement, {"limit": limit})).mappings().all()
        return [
            PendingLearningSignal(
                **{
                    **dict(row),
                    "source_type": LearningSignalType(int(row["source_type"])),
                }
            )
            for row in rows
        ]

    async def recover_stale(self, stale_after_minutes: int) -> int:
        """把Python任务中断留下的处理中记录恢复为待重试，避免永久卡死。"""
        statement = text("""
            UPDATE learning.learning_signal
            SET process_status = 3,
                next_retry_at = CURRENT_TIMESTAMP,
                processing_started_at = NULL,
                error_message = '任务执行中断，已自动恢复'
            WHERE process_status = 1
              AND (
                  processing_started_at IS NULL
                  OR processing_started_at < CURRENT_TIMESTAMP
                      - (:minutes * INTERVAL '1 minute')
              )
        """)
        async with self.engine.begin() as connection:
            result = await connection.execute(statement, {"minutes": stale_after_minutes})
            return max(result.rowcount or 0, 0)

    @asynccontextmanager
    async def daily_job_lock(self):
        """使用PostgreSQL advisory lock保证多个Python实例中只有一个执行每日任务。

        锁绑定当前数据库连接。进程崩溃、网络断开或连接正常关闭时，PostgreSQL都会
        自动释放锁，不需要Redis，也不会遗留需要人工清理的锁记录。
        """
        lock_key = 734_202_608_120_301
        async with self.engine.connect() as connection:
            acquired = bool(await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            ))
            try:
                yield acquired
            finally:
                if acquired:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    )

    async def complete(
        self,
        signal: PendingLearningSignal,
        embedding: list[float],
        embedding_model: str,
        distance_threshold: float,
        review_occurrence_threshold: int,
        review_user_threshold: int,
    ) -> int:
        vector_literal = self._vector_literal(embedding)
        async with self.engine.begin() as connection:
            nearest = (await connection.execute(
                text("""
                    SELECT id, centroid_embedding <=> CAST(:embedding AS halfvec) AS distance
                    FROM learning.learning_problem
                    WHERE status IN (0, 1)
                      AND intent_code IS NOT DISTINCT FROM :intent_code
                    ORDER BY centroid_embedding <=> CAST(:embedding AS halfvec) LIMIT 1
                """),
                {"embedding": vector_literal, "intent_code": signal.intent_code},
            )).mappings().first()

            if nearest is None or float(nearest["distance"]) > distance_threshold:
                problem_id = await connection.scalar(
                    text("""
                        INSERT INTO learning.learning_problem (
                            problem_code, representative_question, problem_summary,
                            intent_code, centroid_embedding, embedding_model,
                            first_seen_at, last_seen_at
                        ) VALUES (
                            :problem_code, :question, :question, :intent_code,
                            CAST(:embedding AS halfvec), :embedding_model,
                            :occurred_at, :occurred_at
                        ) RETURNING id
                    """),
                    {
                        "problem_code": f"PB-{uuid.uuid4().hex[:20].upper()}",
                        "question": signal.question_text,
                        "intent_code": signal.intent_code,
                        "embedding": vector_literal,
                        "embedding_model": embedding_model,
                        "occurred_at": signal.occurred_at,
                    },
                )
                distance = None
            else:
                problem_id = int(nearest["id"])
                distance = float(nearest["distance"])

            await connection.execute(
                text("""
                    INSERT INTO learning.learning_sample (
                        signal_id, problem_id, root_question, original_answer,
                        embedding, embedding_model, cluster_distance
                    ) VALUES (
                        :signal_id, :problem_id, :question, :answer,
                        CAST(:embedding AS halfvec), :embedding_model, :distance
                    ) ON CONFLICT (signal_id, sample_no) DO NOTHING
                """),
                {
                    "signal_id": signal.id, "problem_id": problem_id,
                    "question": signal.question_text, "answer": signal.answer_text,
                    "embedding": vector_literal, "embedding_model": embedding_model,
                    "distance": distance,
                },
            )
            # 同一回答同时触发“没帮助”和“差评”时，只统计一次发生次数。
            # 只有“收集中”的问题可以被门槛自动推进；人工已经处理过的状态不会被任务覆盖。
            await connection.execute(
                text("""
                    UPDATE learning.learning_problem AS problem
                    SET occurrence_count = stats.occurrence_count,
                        affected_user_count = stats.affected_user_count,
                        conversation_count = stats.conversation_count,
                        last_seen_at = stats.last_seen_at,
                        status = CASE
                            WHEN problem.status = 0 AND (
                                stats.has_complaint
                                OR stats.occurrence_count >= :occurrence_threshold
                                OR stats.affected_user_count >= :user_threshold
                            ) THEN 1
                            ELSE problem.status
                        END,
                        priority = CASE
                            WHEN stats.has_complaint THEN 3
                            WHEN stats.occurrence_count >= :occurrence_threshold * 3 THEN 3
                            WHEN stats.occurrence_count >= :occurrence_threshold THEN 2
                            ELSE problem.priority
                        END,
                        processed_at = CURRENT_TIMESTAMP,
                        updated_by = 'python-learning-worker'
                    FROM (
                        SELECT sample.problem_id,
                               COUNT(DISTINCT signal.trigger_message_id)::INTEGER AS occurrence_count,
                               COUNT(DISTINCT signal.user_id)::INTEGER AS affected_user_count,
                               COUNT(DISTINCT signal.conversation_id)::INTEGER AS conversation_count,
                               BOOL_OR(signal.source_type = 4) AS has_complaint,
                               MAX(signal.occurred_at) AS last_seen_at
                        FROM learning.learning_sample AS sample
                        JOIN learning.learning_signal AS signal ON signal.id = sample.signal_id
                        WHERE sample.problem_id = :problem_id GROUP BY sample.problem_id
                    ) AS stats WHERE problem.id = stats.problem_id
                """),
                {
                    "problem_id": problem_id,
                    "occurrence_threshold": max(1, review_occurrence_threshold),
                    "user_threshold": max(1, review_user_threshold),
                },
            )
            await connection.execute(
                text("""
                    UPDATE learning.learning_signal
                    SET process_status = 2,
                        processing_started_at = NULL,
                        processed_at = CURRENT_TIMESTAMP,
                        error_message = NULL
                    WHERE id = :signal_id
                """),
                {"signal_id": signal.id},
            )
            return int(problem_id)

    async def fail(self, signal_id: int, error_message: str, max_retries: int) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                text("""
                    UPDATE learning.learning_signal
                    SET retry_count = retry_count + 1,
                        process_status = CASE WHEN retry_count + 1 >= :max_retries THEN 4 ELSE 3 END,
                        next_retry_at = CURRENT_TIMESTAMP + INTERVAL '30 seconds',
                        processing_started_at = NULL,
                        error_message = :error_message,
                        processed_at = CASE WHEN retry_count + 1 >= :max_retries
                                            THEN CURRENT_TIMESTAMP ELSE NULL END
                    WHERE id = :signal_id
                """),
                {"signal_id": signal_id, "max_retries": max_retries, "error_message": error_message[:1000]},
            )

    async def close(self) -> None:
        await self.engine.dispose()

    def _vector_literal(self, embedding: list[float]) -> str:
        if len(embedding) != 2048:
            raise ValueError(f"问题向量维度必须是2048，实际为{len(embedding)}")
        return "[" + ",".join(format(value, ".9g") for value in embedding) + "]"
