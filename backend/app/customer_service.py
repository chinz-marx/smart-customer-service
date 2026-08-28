from __future__ import annotations

from app.config import Settings
from app.llm.generator import AnswerChunkCallback
from app.prompts.registry import PromptRegistry
from app.orchestrator import ChatOrchestrationResult, CustomerServiceOrchestrator
from app.retrieval.service import SemanticAnswerService
from app.schemas import ChatHistoryItem
from app.session.store import SessionStore
from app.tools.mcp_client import McpToolClient
from app.understanding.service import UnderstandingService


class CustomerServiceAgent:
    """兼容旧接口的客服入口。

    新代码可以调用handle取得完整编排结果；旧测试继续调用reply取得四元组。
    """

    def __init__(
        self,
        settings: Settings,
        session_store: SessionStore | None = None,
        understanding_service: UnderstandingService | None = None,
        semantic_answer_service: SemanticAnswerService | None = None,
        prompt_registry: PromptRegistry | None = None,
        mcp_tool_client: McpToolClient | None = None,
    ) -> None:
        # 允许测试注入假的理解服务，避免单元测试发起真实模型请求。
        self.orchestrator = CustomerServiceOrchestrator(
            settings,
            session_store=session_store,
            understanding_service=understanding_service,
            semantic_answer_service=semantic_answer_service,
            prompt_registry=prompt_registry,
            mcp_tool_client=mcp_tool_client,
        )

    async def handle(
        self,
        message: str,
        session_id: str | None,
        history: list[ChatHistoryItem],
        conversation_id: str | None = None,
        user_id: str | None = None,
        on_answer_chunk: AnswerChunkCallback | None = None,
    ) -> ChatOrchestrationResult:
        """返回包含意图、决策和耗时的完整结果，供持久化层使用。"""
        return await self.orchestrator.handle(
            message=message,
            session_id=session_id,
            history=history,
            conversation_id=conversation_id,
            user_id=user_id,
            on_answer_chunk=on_answer_chunk,
        )

    async def reply(
        self,
        message: str,
        session_id: str | None,
        history: list[ChatHistoryItem],
    ) -> tuple[str, str, str, list[str]]:
        """保留旧调用方式：答案、会话ID、模型来源、推荐问题。"""
        result = await self.handle(
            message=message,
            session_id=session_id,
            history=history,
        )
        return result.answer, result.session_id, result.provider, result.suggestions
