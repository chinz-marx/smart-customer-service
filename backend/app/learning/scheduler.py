from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings
from app.learning.repository import LearningRepository
from app.learning.service import LearningJobResult, LearningSignalProcessor


logger = logging.getLogger("smart_customer_service.learning.scheduler")


class LearningDailyScheduler:
    """每天按配置时间执行问题向量化和聚类，并支持Python多实例部署。"""

    def __init__(
        self,
        settings: Settings,
        repository: LearningRepository,
        processor: LearningSignalProcessor,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.processor = processor
        self.timezone = ZoneInfo(settings.learning_schedule_timezone)
        self._validate_schedule()
        self._stopped = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """在当前FastAPI事件循环中启动调度协程，重复调用不会创建多个任务。"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run_forever(), name="learning-daily-scheduler"
            )

    async def close(self) -> None:
        """应用关闭时停止等待，不会留下后台协程。"""
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def run_once(self) -> LearningJobResult | None:
        """执行一次任务；没有获得PG锁表示其他Python实例正在处理。"""
        async with self.repository.daily_job_lock() as acquired:
            if not acquired:
                logger.info("问题学习任务跳过：其他Python实例已获得PostgreSQL任务锁")
                return None
            logger.info("问题学习任务开始")
            result = await self.processor.process_job(
                self.settings.learning_max_batches,
                self.settings.learning_batch_size,
            )
            logger.info(
                "问题学习任务完成: claimed=%s, succeeded=%s, failed=%s, "
                "recovered=%s, batches=%s",
                result.claimed,
                result.succeeded,
                result.failed,
                result.recovered,
                result.batches,
            )
            return result

    def next_run_time(self, now: datetime | None = None) -> datetime:
        """计算下一次03:00；使用ZoneInfo确保Windows和Linux时区行为一致。"""
        current = now.astimezone(self.timezone) if now else datetime.now(self.timezone)
        candidate = current.replace(
            hour=self.settings.learning_schedule_hour,
            minute=self.settings.learning_schedule_minute,
            second=0,
            microsecond=0,
        )
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate

    async def _run_forever(self) -> None:
        while not self._stopped.is_set():
            now = datetime.now(self.timezone)
            next_run = self.next_run_time(now)
            delay = max(0.0, (next_run - now).total_seconds())
            logger.info("问题学习任务下一次执行时间: %s", next_run.isoformat())
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=delay)
                break
            except TimeoutError:
                pass

            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # 单次失败只记录日志，第二天仍会正常继续调度。
                logger.exception("问题学习定时任务执行失败")

    def _validate_schedule(self) -> None:
        if not 0 <= self.settings.learning_schedule_hour <= 23:
            raise ValueError("LEARNING_SCHEDULE_HOUR必须在0到23之间")
        if not 0 <= self.settings.learning_schedule_minute <= 59:
            raise ValueError("LEARNING_SCHEDULE_MINUTE必须在0到59之间")
