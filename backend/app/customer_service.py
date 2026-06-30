from __future__ import annotations

from app.config import Settings
from app.orchestrator import CustomerServiceOrchestrator
from app.schemas import ChatHistoryItem


class CustomerServiceAgent:
    """兼容旧代码的客服入口。

    main.py 仍然调用 CustomerServiceAgent；内部再转给新的 orchestrator。
    这样前端接口不用变化，后端可以逐步演进。
    """

    def __init__(self, settings: Settings) -> None:
        self.orchestrator = CustomerServiceOrchestrator(settings)

    async def reply(
        self,
        message: str,
        session_id: str | None,
        history: list[ChatHistoryItem],
    ) -> tuple[str, str, str, list[str]]:
        """返回旧接口需要的四元组：答案、会话ID、模型来源、推荐问题。"""
        result = await self.orchestrator.handle(
            message=message,
            session_id=session_id,
            history=history,
        )
        return result.answer, result.session_id, result.provider, result.suggestions