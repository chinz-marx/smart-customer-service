from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.config import Settings
from app.learning.domain import LearningSignalCreate, PendingLearningSignal
from app.learning.repository import LearningRepository
from app.retrieval.embedding import DoubaoEmbeddingClient


logger = logging.getLogger("smart_customer_service.learning")


@dataclass(frozen=True, slots=True)
class LearningJobResult:
    """一次Python定时任务的可审计处理结果。"""

    claimed: int
    succeeded: int
    failed: int
    recovered: int
    batches: int


class LearningSignalProcessor:
    """后台批量生成向量并写入 pgvector；任何失败都不会阻塞客服回答。"""

    def __init__(self, settings: Settings, repository: LearningRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.embedding = DoubaoEmbeddingClient(settings)

    async def process_job(self, max_batches: int, batch_size: int) -> LearningJobResult:
        """处理本次调度可领取的全部数据，并设置上限防止任务无限运行。"""
        recovered = await self.repository.recover_stale(self.settings.learning_stale_after_minutes)
        claimed = succeeded = failed = batches = 0
        for _ in range(max_batches):
            signals = await self.repository.claim_pending(batch_size)
            if not signals:
                break
            batches += 1
            claimed += len(signals)
            batch_succeeded, batch_failed = await self._process_claimed(signals)
            succeeded += batch_succeeded
            failed += batch_failed
            if len(signals) < batch_size:
                break
        return LearningJobResult(
            claimed=claimed,
            succeeded=succeeded,
            failed=failed,
            recovered=recovered,
            batches=batches,
        )

    async def _process_claimed(
        self, signals: Sequence[PendingLearningSignal]
    ) -> tuple[int, int]:
        """限制Embedding并发，防止一次任务把模型供应商或本机连接池打满。"""
        semaphore = asyncio.Semaphore(self.settings.learning_embedding_concurrency)

        async def process(signal: PendingLearningSignal) -> bool:
            async with semaphore:
                try:
                    vector = await self.embedding.embed(signal.question_text)
                    await self.repository.complete(
                        signal, vector, self.settings.embedding_model,
                        self.settings.learning_cluster_distance_threshold,
                        self.settings.learning_review_occurrence_threshold,
                        self.settings.learning_review_user_threshold,
                    )
                    return True
                except Exception as exc:
                    logger.exception("问题信号处理失败: signal_id=%s", signal.id)
                    await self.repository.fail(signal.id, str(exc), self.settings.learning_max_retries)
                    return False

        results = await asyncio.gather(*(process(signal) for signal in signals))
        succeeded = sum(results)
        return succeeded, len(results) - succeeded

    async def close(self) -> None:
        await self.embedding.close()


async def save_signals_safely(repository: LearningRepository, signals: Sequence[LearningSignalCreate]) -> None:
    """问题收集失败只记录日志，不能让客服已经生成的回答整体失败。"""
    if not signals:
        return
    try:
        await repository.add_signals(signals)
    except Exception:
        logger.exception("问题信号写入PostgreSQL失败")
