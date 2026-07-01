from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from app.config import Settings
from app.configs.loader import load_runtime_config
from app.errors import ChatFlowError
from app.intent.classifier import IntentClassifier
from app.intent.schemas import IntentResult
from app.llm.generator import GenerateAnswerResult, AnswerGenerator
from app.observability.logger import ChatTrace, log_chat_trace, mask_message, mask_slots
from app.preprocessing.normalizer import PreprocessResult, TextPreprocessor
from app.rules.engine import RouteDecision, RuleEngine
from app.schemas import ChatHistoryItem
from app.session.store import ConversationState, session_store
from app.slots.extractor import SlotExtractor
from app.slots.manager import SlotManager
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolRequest, ToolResult


@dataclass(slots=True)
class ChatOrchestrationResult:
    """主编排流程最终返回给接口层的数据。"""

    answer: str
    session_id: str
    provider: str
    suggestions: list[str]


class CustomerServiceOrchestrator:
    """文字输入链路的主编排器。

    它不亲自做意图识别、槽位抽取或模型调用，而是把各个模块按生产链路串起来：
    预处理 -> 意图识别 -> 槽位抽取 -> 会话状态 -> 规则决策 -> Tool -> LLM/本地回复。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.preprocessor = TextPreprocessor()
        self.intent_classifier = IntentClassifier()
        self.slot_extractor = SlotExtractor()
        self.slot_manager = SlotManager()
        self.rule_engine = RuleEngine(self.slot_manager)
        self.tool_registry = ToolRegistry()
        self.answer_generator = AnswerGenerator(settings)

    async def handle(
        self,
        message: str,
        session_id: str | None,
        history: list[ChatHistoryItem],
    ) -> ChatOrchestrationResult:
        """处理用户的一轮输入。"""
        started_at = time.perf_counter()
        current_session_id = session_id or str(uuid.uuid4())
        state = session_store.get_or_create(current_session_id)

        # 1. 先把原始文本清洗成统一格式，并提前抽取订单号/尾号等基础实体。
        preprocess = self.preprocessor.normalize(message)

        # 2. 判断用户这句话的业务意图，比如奖励未到账、积分查询、转人工。
        intent = self.intent_classifier.classify(preprocess.normalized_text)

        # 3. 如果用户第二轮只说“订单号是 xxx”，这句话本身没有意图，
        #    但上一轮已经确认过意图，就复用上一轮意图继续抽槽。
        extraction_intent = intent.intent
        if intent.intent == "unknown" and state.current_intent:
            extraction_intent = state.current_intent

        extracted_slots = self.slot_extractor.extract(preprocess, extraction_intent)
        if intent.intent == "unknown" and extracted_slots and state.current_intent:
            intent = IntentResult(intent=state.current_intent, confidence=0.88)

        # 4. 把本轮抽到的槽位合并到会话状态里，形成多轮记忆。
        state = self.slot_manager.merge(state, intent.intent, extracted_slots)

        # 5. 规则引擎决定下一步：澄清、追问槽位、转人工，还是继续生成答案。
        decision = self.rule_engine.decide(preprocess, intent, state)
        if decision.action != "generate":
            provider = self._provider()
            session_store.save(state)
            self._log_trace(
                started_at=started_at,
                session_id=current_session_id,
                message=message,
                preprocess=preprocess,
                intent=intent,
                state=state,
                decision=decision,
                provider=provider,
                tool_result=None,
                flow_error=None,
                fallback_used=False,
            )
            return ChatOrchestrationResult(
                answer=decision.answer or "",
                session_id=current_session_id,
                provider=provider,
                suggestions=decision.suggestions,
            )

        # 6. 槽位满足后，按配置里的 tool 名称调用业务工具。
        tool_result = await self._call_business_tool(current_session_id, state)

        # 7. 最后把意图、槽位、工具结果交给回答生成器组织成客服话术。
        generate_result = await self.answer_generator.generate(message, state, history, tool_result)
        session_store.save(state)
        self._log_trace(
            started_at=started_at,
            session_id=current_session_id,
            message=message,
            preprocess=preprocess,
            intent=intent,
            state=state,
            decision=decision,
            provider=generate_result.provider,
            tool_result=tool_result,
            flow_error=self._flow_error(tool_result, generate_result),
            fallback_used=generate_result.fallback_used or bool(tool_result and not tool_result.success),
        )
        return ChatOrchestrationResult(
            answer=generate_result.answer,
            session_id=current_session_id,
            provider=generate_result.provider,
            suggestions=decision.suggestions,
        )

    async def _call_business_tool(self, session_id: str, state: ConversationState) -> ToolResult | None:
        """根据当前意图配置调用业务工具。

        现在 registry 里是 mock tool；未来替换成 Java HTTP Tool 时，这里不用改。
        """
        if not state.current_intent:
            return None

        intent_config = load_runtime_config().intents.get(state.current_intent)
        tool_name = intent_config.tool if intent_config else None
        request = ToolRequest(
            session_id=session_id,
            intent=state.current_intent,
            slots={code: slot.value for code, slot in state.slots.items()},
            state=state,
        )
        return await self.tool_registry.call(tool_name, request)

    def _flow_error(
        self,
        tool_result: ToolResult | None,
        generate_result: GenerateAnswerResult,
    ) -> ChatFlowError | None:
        """把工具失败或模型失败统一转换成日志错误对象。"""
        if generate_result.error:
            return generate_result.error
        if tool_result and not tool_result.success:
            return ChatFlowError(
                stage=tool_result.failed_stage or "tool",
                error_type=tool_result.error_type or tool_result.error_code or "ToolFailed",
                message=tool_result.message,
                fallback_used=True,
            )
        return None

    def _log_trace(
        self,
        started_at: float,
        session_id: str,
        message: str,
        preprocess: PreprocessResult,
        intent: IntentResult,
        state: ConversationState,
        decision: RouteDecision,
        provider: str,
        tool_result: ToolResult | None,
        flow_error: ChatFlowError | None,
        fallback_used: bool,
    ) -> None:
        """记录一轮对话的结构化链路日志。

        这里集中生成 trace，避免各个业务模块到处直接写日志。
        """
        slot_values = {code: slot.value for code, slot in state.slots.items()}
        trace = ChatTrace(
            session_id=session_id,
            message_preview=mask_message(message),
            intent=intent.intent,
            intent_confidence=intent.confidence,
            slots=mask_slots(slot_values),
            decision_action=decision.action,
            decision_reason=decision.reason,
            provider=provider,
            latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
            tool_name=tool_result.tool_name if tool_result else None,
            tool_success=tool_result.success if tool_result else None,
            tool_error_code=tool_result.error_code if tool_result else None,
            failed_stage=flow_error.stage if flow_error else None,
            error_type=flow_error.error_type if flow_error else None,
            error_message=flow_error.message if flow_error else None,
            fallback_used=fallback_used,
            emotion=preprocess.emotion,
            sensitive=preprocess.sensitive,
        )
        log_chat_trace(trace)

    def _provider(self) -> str:
        """返回当前回答来源。"""
        return "doubao" if self.settings.has_real_api_key else "local-fallback"