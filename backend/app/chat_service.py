from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress

from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.learning.domain import LearningSignalCreate, LearningSignalType
from app.learning.repository import LearningRepository
from app.learning.service import save_signals_safely
from app.llm.generator import AnswerChunkCallback
from app.orchestrator import ChatOrchestrationResult
from app.persistence.domain import ConversationRecord, FeedbackRecord, MessageRecord
from app.persistence.repository import ChatRepository
from app.prompts.registry import PromptRegistry
from app.retrieval.service import DisabledSemanticAnswerService, SemanticAnswerService
from app.schemas import ChatRequest, ChatResponse, FeedbackRequest
from app.session.store import SessionStore
from app.tools.mcp_client import McpToolClient


logger = logging.getLogger("smart_customer_service.chat_service")


class ChatApplicationService:
    """协调聊天编排、Redis会话和PostgreSQL持久化。

    意图识别等AI逻辑仍在orchestrator中，本类只负责一次请求的数据闭环。
    """

    def __init__(
        self,
        settings: Settings,
        session_store: SessionStore,
        repository: ChatRepository,
        semantic_answer_service: SemanticAnswerService | None = None,
        prompt_registry: PromptRegistry | None = None,
        mcp_tool_client: McpToolClient | None = None,
        learning_repository: LearningRepository | None = None,
    ) -> None:
        self.settings = settings
        self.session_store = session_store
        self.repository = repository
        self.learning_repository = learning_repository
        self.agent = CustomerServiceAgent(
            settings,
            session_store=session_store,
            semantic_answer_service=(
                semantic_answer_service or DisabledSemanticAnswerService()
            ),
            prompt_registry=prompt_registry,
            mcp_tool_client=mcp_tool_client,
        )

    async def chat(
        self,
        payload: ChatRequest,
        on_answer_chunk: AnswerChunkCallback | None = None,
    ) -> ChatResponse:
        """保存用户消息、执行客服流程、保存AI回答并按需创建工单。"""
        user_id = self.settings.demo_user_id
        session_id = payload.session_id or str(uuid.uuid4())
        conversation = await self.repository.get_or_create_conversation(
            user_id=user_id,
            session_id=session_id,
            conversation_id=payload.conversation_id,
            title=self._build_title(payload.message),
        )

        # 先保存用户原始问题，即使后续模型失败也能在后台追查。
        user_message = await self.repository.add_message(
            conversation_id=conversation.id,
            role="user",
            content=payload.message,
            request_id=payload.request_id,
        )

        result = await self.agent.handle(
            message=payload.message,
            session_id=session_id,
            history=payload.history,
            conversation_id=conversation.id,
            user_id=user_id,
            on_answer_chunk=on_answer_chunk,
        )

        assistant_message = await self.repository.add_message(
            conversation_id=conversation.id,
            role="assistant",
            content=result.answer,
            request_id=str(uuid.uuid4()),
            intent=result.intent,
            intent_confidence=result.intent_confidence,
            provider=result.provider,
            latency_ms=result.latency_ms,
        )

        ticket_id: str | None = None
        if result.decision_action == "handoff":
            # 工单保存当前意图和槽位快照，人工坐席无需让用户重新描述问题。
            priority = "high" if result.emotion == "negative" else "normal"
            ticket = await self.repository.create_ticket(
                conversation_id=conversation.id,
                user_id=user_id,
                reason=result.decision_reason,
                summary=self._build_ticket_summary(payload.message, result.answer),
                context_snapshot={
                    "session_id": result.session_id,
                    "intent": result.intent,
                    "intent_confidence": result.intent_confidence,
                    "slots": result.slots,
                    "emotion": result.emotion,
                },
                priority=priority,
            )
            ticket_id = ticket.id

        if self.learning_repository is not None:
            await save_signals_safely(
                self.learning_repository,
                self._chat_learning_signals(
                    result=result,
                    user_id=user_id,
                    conversation_id=conversation.id,
                    user_message_id=user_message.id,
                    assistant_message_id=assistant_message.id,
                    question=payload.message,
                    answer=result.answer,
                    ticket_id=ticket_id,
                ),
            )

        return ChatResponse(
            answer=result.answer,
            session_id=result.session_id,
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            ticket_id=ticket_id,
            provider=result.provider,
            suggestions=result.suggestions,
        )

    async def chat_stream(self, payload: ChatRequest) -> AsyncIterator[str]:
        """以SSE事件输出回答增量，并在完成后发送持久化后的完整元数据。get_or_create_conversation

        delta事件只包含本次新增文本；done事件包含普通ChatResponse的全部字段。
        如果是追问、转人工或本地策略回答，没有模型增量时会把完整答案作为一个delta发送。
        """
        chunks: asyncio.Queue[str] = asyncio.Queue()
        streamed = False
        task = asyncio.create_task(self.chat(payload, on_answer_chunk=chunks.put))

        try:
            # 模型生成与HTTP输出解耦：生成任务写队列，SSE生成器持续读取队列。
            while not task.done() or not chunks.empty():
                try:
                    chunk = await asyncio.wait_for(chunks.get(), timeout=0.1)
                except TimeoutError:
                    continue
                streamed = True
                yield self._sse_event("delta", {"content": chunk})

            response = await task
            if not streamed:
                yield self._sse_event("delta", {"content": response.answer})
            yield self._sse_event("done", response.model_dump(mode="json"))
        except asyncio.CancelledError:
            # 浏览器主动断开时取消模型调用，避免继续消耗Token和服务资源。
            task.cancel()
            raise
        except Exception:
            logger.exception("流式聊天请求处理失败")
            yield self._sse_event(
                "error",
                {"message": "客服服务暂时繁忙，请稍后再试或联系人工客服。"},
            )
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def _sse_event(self, event: str, payload: dict[str, object]) -> str:
        """把事件编码成标准SSE文本，JSON保留中文并确保每个事件以空行结束。"""
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return f"event: {event}\ndata: {data}\n\n"

    async def save_feedback(self, payload: FeedbackRequest) -> FeedbackRecord:
        """保存当前测试用户对AI回答的评价。"""
        record = await self.repository.save_feedback(
            conversation_id=payload.conversation_id,
            message_id=payload.message_id,
            user_id=self.settings.demo_user_id,
            feedback_type=payload.feedback_type,
            rating=payload.rating,
            comment=payload.comment,
        )
        if self.learning_repository is not None:
            messages = await self.repository.list_messages(
                payload.conversation_id,
                self.settings.demo_user_id,
                limit=100,
            )
            assistant_index = next(
                (index for index, item in enumerate(messages) if item.id == payload.message_id),
                -1,
            )
            assistant = messages[assistant_index] if assistant_index >= 0 else None
            user_message = next(
                (
                    messages[index]
                    for index in range(assistant_index - 1, -1, -1)
                    if messages[index].role == "user"
                ),
                None,
            )
            question = user_message.content if user_message else (payload.comment or "用户反馈当前回答无效")
            signals: list[LearningSignalCreate] = []
            if payload.feedback_type == "unhelpful":
                signals.append(self._feedback_signal(
                    LearningSignalType.UNHELPFUL, record.id, payload, question,
                    assistant.content if assistant else None,
                    user_message.id if user_message else payload.message_id,
                    assistant.intent if assistant else None,
                    assistant.intent_confidence if assistant else None,
                ))
            if payload.rating is not None and payload.rating <= 2:
                signals.append(self._feedback_signal(
                    LearningSignalType.NEGATIVE_RATING, record.id, payload, question,
                    assistant.content if assistant else None,
                    user_message.id if user_message else payload.message_id,
                    assistant.intent if assistant else None,
                    assistant.intent_confidence if assistant else None,
                ))
            await save_signals_safely(self.learning_repository, signals)
        return record

    def _chat_learning_signals(
        self,
        result: ChatOrchestrationResult,
        user_id: str,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        question: str,
        answer: str,
        ticket_id: str | None,
    ) -> list[LearningSignalCreate]:
        """把编排结果转换成明确问题信号；这里只包含本期确认的四种聊天触发。"""
        signals: list[LearningSignalCreate] = []

        def append(source_type: LearningSignalType, source_id: str, failure_code: str | None = None) -> None:
            signals.append(LearningSignalCreate(
                signal_key=f"{int(source_type)}:{source_id}",
                source_type=source_type,
                source_id=source_id,
                conversation_id=conversation_id,
                trigger_message_id=user_message_id,
                target_assistant_message_id=assistant_message_id,
                user_id=user_id,
                question_text=question,
                answer_text=answer,
                intent_code=result.intent,
                confidence=result.intent_confidence,
                tool_name=result.tool_name,
                failure_code=failure_code,
            ))

        if result.intent == "human_handoff" and result.decision_action == "handoff":
            append(LearningSignalType.HUMAN_HANDOFF, ticket_id or assistant_message_id)
        if result.intent == "complaint":
            append(LearningSignalType.COMPLAINT, assistant_message_id)
        if result.tool_success is False:
            append(LearningSignalType.TOOL_FAILURE, assistant_message_id, result.tool_error_code)
        if result.knowledge_requested and result.knowledge_attempted and not result.knowledge_hit:
            append(LearningSignalType.RAG_MISS, assistant_message_id, "RAG_NO_MATCH")
        return signals

    def _feedback_signal(
        self,
        source_type: LearningSignalType,
        feedback_id: str,
        payload: FeedbackRequest,
        question: str,
        answer: str | None,
        user_message_id: str,
        intent: str | None,
        confidence: float | None,
    ) -> LearningSignalCreate:
        """反馈已经绑定具体AI回答，因此可以准确定位对应的用户问题。"""
        return LearningSignalCreate(
            signal_key=f"{int(source_type)}:{feedback_id}",
            source_type=source_type,
            source_id=feedback_id,
            conversation_id=payload.conversation_id,
            trigger_message_id=user_message_id,
            target_assistant_message_id=payload.message_id,
            user_id=self.settings.demo_user_id,
            question_text=question,
            answer_text=answer,
            intent_code=intent,
            confidence=confidence,
        )

    async def list_conversations(self, limit: int = 20) -> list[ConversationRecord]:
        """查询当前测试用户最近的对话。"""
        return await self.repository.list_conversations(self.settings.demo_user_id, limit=limit)

    async def list_messages(self, conversation_id: str, limit: int = 100) -> list[MessageRecord]:
        """查询当前测试用户指定对话的消息。"""
        return await self.repository.list_messages(
            conversation_id=conversation_id,
            user_id=self.settings.demo_user_id,
            limit=limit,
        )

    def _build_title(self, message: str) -> str:
        """用首条问题生成简短历史对话标题。"""
        compact = " ".join(message.strip().split())
        return compact[:40] or "新对话"

    def _build_ticket_summary(self, message: str, answer: str) -> str:
        """生成供人工坐席快速浏览的第一版工单摘要。"""
        return f"用户问题：{message[:500]}\n系统处理：{answer[:500]}"
