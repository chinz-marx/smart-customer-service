from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import timedelta

from app.config import Settings
from app.observability.timing import bind_request_id, timed_lock
from app.errors import DialogueConflictError
from app.customer_service import CustomerServiceAgent
from app.learning.domain import LearningSignalCreate, LearningSignalType
from app.learning.repository import LearningRepository
from app.learning.service import save_signals_safely
from app.llm.generator import AnswerChunkCallback
from app.orchestrator import ChatOrchestrationResult
from app.persistence.domain import ConversationRecord, FeedbackRecord, MessageRecord, utc_now
from app.persistence.repository import ChatRepository
from app.prompts.registry import PromptRegistry
from app.retrieval.service import DisabledSemanticAnswerService, SemanticAnswerService
from app.rules.local_routing import LocalRoutingConfigRegistry
from app.schemas import ChatHistoryItem, ChatRequest, ChatResponse, FeedbackRequest
from app.session.store import ConversationState, SessionStore, receipt_key
from app.tools.mcp_client import McpToolClient


logger = logging.getLogger("smart_customer_service.chat_service")
CONVERSATION_HISTORY_DAYS = 3


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
        local_routing_registry: LocalRoutingConfigRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.session_store = session_store
        self.repository = repository
        self.learning_repository = learning_repository
        self._learning_tasks: set[asyncio.Task[None]] = set()
        self._chat_tasks: set[asyncio.Task] = set()
        self._message_tasks: set[asyncio.Task] = set()
        self._chat_capacity = asyncio.Semaphore(128)
        self.agent = CustomerServiceAgent(
            settings,
            session_store=session_store,
            semantic_answer_service=(
                semantic_answer_service or DisabledSemanticAnswerService()
            ),
            prompt_registry=prompt_registry,
            mcp_tool_client=mcp_tool_client,
            local_routing_registry=local_routing_registry,
        )

    async def chat(
        self,
        payload: ChatRequest,
        on_answer_chunk: AnswerChunkCallback | None = None,
    ) -> ChatResponse:
        """Return the prepared answer while the tracked worker finishes message writes."""
        bind_request_id(payload.request_id)
        await self._chat_capacity.acquire()
        ready = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(self._run_chat(payload, on_answer_chunk, ready), name="chat-and-persist")
        self._track_task(task, self._chat_tasks)
        # Release capacity even if cancellation happens before the worker starts.
        task.add_done_callback(lambda _: self._chat_capacity.release())
        try:
            return await asyncio.shield(ready)
        except asyncio.CancelledError:
            if not ready.done():
                ready.cancel()
                task.cancel()
            raise

    async def _run_chat(self, payload, on_answer_chunk, ready):
        user_id = self.settings.demo_user_id
        session_id = payload.session_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:{payload.request_id}"))
        try:
            # Keep the distributed lock until writes finish: another worker must
            # not parse the next turn against partially persisted history.
            async with timed_lock(self.session_store.lock(session_id)):
                response = await self._chat_in_session(payload, on_answer_chunk, session_id, user_id, ready)
            if not ready.done():
                ready.set_result(response)
        except BaseException as exc:
            if not ready.done():
                if isinstance(exc, asyncio.CancelledError):
                    ready.cancel()
                else:
                    ready.set_exception(exc)
            raise

    async def _chat_in_session(self, payload, on_answer_chunk, session_id, user_id, ready) -> ChatResponse:
        conversation = await self.repository.get_or_create_conversation(
            user_id=user_id, session_id=session_id, conversation_id=payload.conversation_id,
            title=self._build_title(payload.message),
        )
        if payload.session_id and conversation.session_id != payload.session_id:
            raise ValueError("会话与对话不匹配")
        session_id = conversation.session_id
        payload = payload.model_copy(update={"session_id": session_id, "conversation_id": conversation.id})
        key = receipt_key(session_id, user_id, payload.request_id)
        fingerprint = hashlib.sha256(payload.message.encode()).hexdigest()
        async with timed_lock(self.session_store.lock(session_id)):
            receipt = await self.session_store.get_receipt(key)
            if receipt:
                if receipt["fingerprint"] != fingerprint:
                    raise DialogueConflictError("同一个request_id不能用于不同消息")
                if receipt["status"] == "completed":
                    response = ChatResponse.model_validate(receipt["response"])
                    if on_answer_chunk:
                        await on_answer_chunk(response.answer)
                    return response
                raise DialogueConflictError("该请求尚未确认完成，请先核实处理结果，避免重复办理")
            # Check ownership before persisting any user content or invoking a model.
            state = await self.session_store.get_or_create(session_id, conversation.id, user_id)
            await self.session_store.save_receipt(key, {"status": "processing", "fingerprint": fingerprint})
            response = await self._chat_locked(payload, on_answer_chunk, conversation, state, ready)
            await self.session_store.save_receipt(key, {
                "status": "completed", "fingerprint": fingerprint, "response": response.model_dump(mode="json"),
            })
            return response

    async def _chat_locked(
        self,
        payload: ChatRequest,
        on_answer_chunk: AnswerChunkCallback | None = None,
        conversation: ConversationRecord | None = None,
        state: ConversationState | None = None,
        ready: asyncio.Future | None = None,
    ) -> ChatResponse:
        """保存用户消息、执行客服流程、保存AI回答并按需创建工单。"""
        user_id = self.settings.demo_user_id
        session_id = payload.session_id or str(uuid.uuid4())
        conversation = conversation or await self.repository.get_or_create_conversation(
            user_id=user_id,
            session_id=session_id,
            conversation_id=payload.conversation_id,
            title=self._build_title(payload.message),
        )

        recent = await self.repository.list_messages(conversation.id, user_id, limit=8)
        history = [ChatHistoryItem(role=m.role, content=m.content[:4000]) for m in recent if m.role in {"user", "assistant"} and m.content]
        # Reserve IDs and timestamps before writing; current input goes straight
        # to the parser while the independent database write is in flight.
        user_message = MessageRecord(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            role="user",
            content=payload.message,
            request_id=payload.request_id,
        )
        user_write = asyncio.create_task(self._save_message(user_message), name="persist-user-message")
        self._track_task(user_write, self._message_tasks)

        result = await self.agent.handle(
            message=payload.message,
            session_id=session_id,
            history=history,
            conversation_id=conversation.id,
            user_id=user_id,
            on_answer_chunk=on_answer_chunk,
            request_id=payload.request_id,
            state=state,
        )

        assistant_message = MessageRecord(
            id=str(uuid.uuid4()),
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

        response = ChatResponse(
            answer=result.answer,
            session_id=result.session_id,
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            ticket_id=ticket_id,
            provider=result.provider,
            suggestions=result.suggestions,
        )
        if ready is not None and not ready.done():
            ready.set_result(response)

        # IDs in the response are already final. Preserve user/assistant write
        # ordering and complete references before learning/feedback consumes them.
        await asyncio.shield(user_write)
        await self._save_message(assistant_message)
        if self.learning_repository is not None:
            self._schedule_learning_signals(
                self._chat_learning_signals(
                    result=result,
                    user_id=user_id,
                    conversation_id=conversation.id,
                    user_message_id=user_message.id,
                    assistant_message_id=assistant_message.id,
                    question=payload.message,
                    answer=result.answer,
                    ticket_id=ticket_id,
                )
            )

        return response

    async def _save_message(self, message: MessageRecord):
        return await self.repository.add_message(
            conversation_id=message.conversation_id, role=message.role,
            content=message.content, request_id=message.request_id,
            intent=message.intent, intent_confidence=message.intent_confidence,
            provider=message.provider, latency_ms=message.latency_ms,
            message_id=message.id, created_at=message.created_at,
        )

    def _track_task(self, task, tasks):
        tasks.add(task)
        def finished(done):
            tasks.discard(done)
            if not done.cancelled():
                error = done.exception()
                if error is not None:
                    logger.error("Background chat task failed: task=%s error=%s",
                                 done.get_name(), type(error).__name__)
        task.add_done_callback(finished)

    async def chat_stream(self, payload: ChatRequest) -> AsyncIterator[str]:
        """输出回答增量和预分配的消息ID；聊天记录由受管理的后台任务保存。

        delta事件只包含本次新增文本；done事件包含普通ChatResponse的全部字段。
        如果是追问、转人工或本地策略回答，没有模型增量时会把完整答案作为一个delta发送。
        """
        chunks: asyncio.Queue[str] = asyncio.Queue()
        quick_reply = self.agent.match_quick_reply(payload.message)
        streamed = quick_reply is not None
        # 确定性回复不把回调传入完整链路，避免orchestrator再次输出同一段文本。
        # chat任务仍会在SSE首包发送后完成Redis刷新和PostgreSQL持久化。
        task = asyncio.create_task(
            self.chat(
                payload,
                on_answer_chunk=None if quick_reply is not None else chunks.put,
            )
        )

        try:
            if quick_reply is not None:
                # 本地匹配不依赖Redis、PostgreSQL或模型，先把答案交给ASGI服务器。
                yield self._sse_event("delta", {"content": quick_reply.answer})

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
        except DialogueConflictError as exc:
            yield self._sse_event("error", {"message": str(exc), "retryable": False})
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
        conversation = await self._resolve_existing_conversation(payload.conversation_id)
        async with timed_lock(self.session_store.lock(conversation.session_id)):
            return await self._save_feedback_locked(payload)

    async def _save_feedback_locked(self, payload: FeedbackRequest) -> FeedbackRecord:
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
        """把编排结果转换成明确问题信号。"""
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

        if (
            result.intent == "human_handoff"
            and result.decision_action in {"handoff", "human_unavailable"}
        ):
            append(LearningSignalType.HUMAN_HANDOFF, ticket_id or assistant_message_id)
        if result.intent == "complaint":
            append(LearningSignalType.COMPLAINT, assistant_message_id)
        if result.tool_success is False:
            append(LearningSignalType.TOOL_FAILURE, assistant_message_id, result.tool_error_code)
        if result.knowledge_requested and result.knowledge_attempted and not result.knowledge_hit:
            append(LearningSignalType.RAG_MISS, assistant_message_id, "RAG_NO_MATCH")
        return signals

    def _schedule_learning_signals(
        self,
        signals: list[LearningSignalCreate],
    ) -> None:
        """客服回答完成后异步落原始信号；凌晨任务继续负责Embedding和问题聚类。"""
        if self.learning_repository is None or not signals:
            return
        task = asyncio.create_task(
            save_signals_safely(self.learning_repository, signals),
            name="save-chat-learning-signals",
        )
        self._learning_tasks.add(task)
        task.add_done_callback(self._learning_tasks.discard)

    async def close(self) -> None:
        """先排空聊天和消息写入，再排空依赖消息ID的问题信号。"""
        if self._chat_tasks:
            await asyncio.gather(*tuple(self._chat_tasks), return_exceptions=True)
        if self._message_tasks:
            await asyncio.gather(*tuple(self._message_tasks), return_exceptions=True)
        if self._learning_tasks:
            await asyncio.gather(*tuple(self._learning_tasks), return_exceptions=True)

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
        """查询当前测试用户近三天内有更新的对话。"""
        updated_after = utc_now() - timedelta(days=CONVERSATION_HISTORY_DAYS)
        return await self.repository.list_conversations(
            self.settings.demo_user_id,
            limit=limit,
            updated_after=updated_after,
        )

    async def list_messages(self, conversation_id: str, limit: int = 100) -> list[MessageRecord]:
        """查询当前测试用户指定对话的消息。"""
        conversation = await self._resolve_existing_conversation(conversation_id)
        async with timed_lock(self.session_store.lock(conversation.session_id)):
            return await self.repository.list_messages(
                conversation_id=conversation_id,
                user_id=self.settings.demo_user_id,
                limit=limit,
            )

    async def _resolve_existing_conversation(self, conversation_id: str) -> ConversationRecord:
        # A supplied conversation ID is lookup-only; unknown IDs are rejected by
        # the repository rather than creating a conversation with an empty session.
        return await self.repository.get_or_create_conversation(
            user_id=self.settings.demo_user_id, session_id="",
            conversation_id=conversation_id, title="",
        )

    def _build_title(self, message: str) -> str:
        """用首条问题生成简短历史对话标题。"""
        compact = " ".join(message.strip().split())
        return compact[:40] or "新对话"

    def _build_ticket_summary(self, message: str, answer: str) -> str:
        """生成供人工坐席快速浏览的第一版工单摘要。"""
        return f"用户问题：{message[:500]}\n系统处理：{answer[:500]}"
