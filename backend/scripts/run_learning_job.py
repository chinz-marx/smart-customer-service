"""手动执行一次问题学习任务，不需要Java或XXL-JOB。

Windows和Linux都在backend目录执行：
    uv run python scripts/run_learning_job.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from app.config import get_settings
from app.infrastructure import create_learning_repository
from app.learning.scheduler import LearningDailyScheduler
from app.learning.service import LearningSignalProcessor


async def main() -> None:
    settings = get_settings()
    if not settings.learning_enabled:
        raise RuntimeError("请先设置LEARNING_ENABLED=true")

    repository = create_learning_repository(settings)
    processor = LearningSignalProcessor(settings, repository)
    try:
        await repository.initialize()
        scheduler = LearningDailyScheduler(settings, repository, processor)
        result = await scheduler.run_once()
        payload = {"status": "skipped", "reason": "another_instance_is_running"}
        if result is not None:
            payload = {"status": "completed", **asdict(result)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        await processor.close()
        await repository.close()


if __name__ == "__main__":
    asyncio.run(main())
