from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from app.config import Settings
from app.configs.loader import load_runtime_config
from app.errors import ChatFlowError
from app.intent.schemas import IntentResult
from app.llm.generator import AnswerChunkCallback, AnswerGenerator, GenerateAnswerResult
from app.observability.logger import ChatTrace, log_chat_trace, mask_message, mask_slots
from app.preprocessing.normalizer import PreprocessResult, TextPreprocessor
from app.prompts.registry import PromptRegistry
from app.retrieval.schemas import SemanticLookup
from app.retrieval.service import DisabledSemanticAnswerService, SemanticAnswerService
from app.rules.engine import RouteDecision, RuleEngine
from app.rules.quick_reply import QuickReply, QuickReplyMatcher
from app.schemas import ChatHistoryItem
from app.session.store import ConversationState, InMemorySessionStore, SessionStore
from app.slots.extractor import SlotExtractor
from app.slots.manager import SlotManager
from app.slots.schemas import SlotValue
from app.tools.registry import ToolRegistry
from app.tools.argument_resolver import ToolArgumentResolver
from app.tools.mcp_client import McpToolClient
from app.tools.schemas import ToolRequest, ToolResult
from app.understanding.schemas import UnderstandingResult
from app.understanding.service import UnderstandingService


@dataclass(slots=True)
class ChatOrchestrationResult:
    """主编排流程返回给应用服务的完整结果。"""

    answer: str
    session_id: str
    provider: str
    suggestions: list[str]
    intent: str
    intent_confidence: float
    decision_action: str
    decision_reason: str
    latency_ms: float
    slots: dict[str, str] = field(default_factory=dict)
    emotion: str = "normal"
    understanding_source: str = "keyword"
    tool_name: str | None = None
    tool_success: bool | None = None
    tool_error_code: str | None = None
    knowledge_requested: bool = False
    knowledge_attempted: bool = False
    knowledge_hit: bool = False


class CustomerServiceOrchestrator:
    """文字输入链路的主编排器。

    新链路为：预处理 -> LLM统一理解 -> 精确槽位补充 -> Redis会话 ->
    策略路由 -> Tool -> Redis Search知识库 -> LangCache -> LLM回答。
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
        self.settings = settings
        self.session_store = session_store or InMemorySessionStore()
        self.preprocessor = TextPreprocessor()
        self.prompt_registry = prompt_registry or PromptRegistry(settings, None)
        self.mcp_tool_client = mcp_tool_client
        self.tool_argument_resolver = ToolArgumentResolver()
        self.understanding_service = understanding_service or UnderstandingService(
            settings,
            prompt_registry=self.prompt_registry,
            mcp_tool_client=mcp_tool_client,
        )
        self.semantic_answer_service = (
            semantic_answer_service or DisabledSemanticAnswerService()
        )
        self.slot_extractor = SlotExtractor()
        self.slot_manager = SlotManager()
        self.rule_engine = RuleEngine(
            self.slot_manager,
            confidence_threshold=settings.understanding_confidence_threshold,
        )
        self.quick_reply_matcher = QuickReplyMatcher()
        self.tool_registry = ToolRegistry(settings)
        self.answer_generator = AnswerGenerator(settings, self.prompt_registry)

    async def handle(
        self,
        message: str,
        session_id: str | None,
        history: list[ChatHistoryItem],
        conversation_id: str | None = None,
        user_id: str | None = None,
        on_answer_chunk: AnswerChunkCallback | None = None,
    ) -> ChatOrchestrationResult:
        """处理用户的一轮输入，并异步读写Redis或内存会话。"""
        started_at = time.perf_counter()
        current_session_id = session_id or str(uuid.uuid4())
        state = await self.session_store.get_or_create(
            current_session_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )

        # 1. 预处理只做文本清洗、敏感词识别和格式明确的基础实体抽取。
        preprocess = self.preprocessor.normalize(message)

        # “不查了”等完整短句只取消当前待补参数的 Tool；“取消订单”等业务表达不会
        # 在这里命中，仍交给正常意图理解判断。
        if state.active_tool:
            cancellation = self.quick_reply_matcher.match_pending_cancellation(
                preprocess.normalized_text
            )
            if cancellation is not None:
                self._clear_active_tool(state)
                understanding = UnderstandingResult(
                    intent=cancellation.intent,
                    confidence=1.0,
                    route_type="direct",
                    source="keyword",
                )
                return await self._complete_quick_reply(
                    quick_reply=cancellation,
                    provider="local-quick-reply",
                    started_at=started_at,
                    session_id=current_session_id,
                    message=message,
                    state=state,
                    preprocess=preprocess,
                    understanding=understanding,
                    on_answer_chunk=on_answer_chunk,
                )

        # 纯寒暄和系统身份问题答案固定、风险很低，不需要等待意图模型和回答模型。
        # 匹配器只接受完整短句，因此“你好，我要查订单”仍会继续进入后面的业务编排。
        quick_reply = self.quick_reply_matcher.match(preprocess.normalized_text)
        if quick_reply is not None:
            understanding = UnderstandingResult(
                intent=quick_reply.intent,
                confidence=1.0,
                needs_clarification=False,
                source="keyword",
            )
            return await self._complete_quick_reply(
                quick_reply=quick_reply,
                provider="local-quick-reply",
                started_at=started_at,
                session_id=current_session_id,
                message=message,
                state=state,
                preprocess=preprocess,
                understanding=understanding,
                on_answer_chunk=on_answer_chunk,
            )
        # 2. 当前 Tool 正在等待参数时，先用公共 Schema 解析器处理结构化续填。
        #    唯一且无额外诉求的值直接继续当前 Tool；其余输入只把当前 Tool 交给轻量
        #    模型做槽位理解，确认切换话题后才执行完整意图识别和 Tool 语义召回。
        understanding = await self._understand_with_pending_tool(
            preprocess=preprocess,
            history=history,
            state=state,
        )
        intent = understanding.to_intent_result()

        # 精确短句没有命中时，DeepSeek仍可识别更自然的寒暄、身份或能力表达。
        # 这三类意图使用同一套标准话术直接回复，不再调用第二次回答模型。
        direct_reply = self.quick_reply_matcher.for_intent(intent.intent)
        if direct_reply is not None:
            return await self._complete_quick_reply(
                quick_reply=direct_reply,
                provider=f"{understanding.source}-direct-reply",
                started_at=started_at,
                session_id=current_session_id,
                message=message,
                state=state,
                preprocess=preprocess,
                understanding=understanding,
                on_answer_chunk=on_answer_chunk,
            )

        # 当前 Tool 只代表“正在等待参数的任务”。模型明确识别出另一项业务时终止
        # 旧任务；unknown、低置信度和寒暄不会误清理待办状态。
        self._clear_active_tool_on_explicit_switch(state, understanding)
        # 3. 正则继续负责订单号、手机号等精确字段；LLM负责活动名称等语义字段。
        #    exact_slots后合并，因此模型抄错编号时，正则结果具有更高优先级。
        extraction_intent = intent.intent
        if intent.intent == "unknown" and state.current_intent:
            extraction_intent = state.current_intent

        semantic_slots = self._semantic_slot_values(understanding, preprocess.raw_text)
        exact_slots = self.slot_extractor.extract(preprocess, extraction_intent)
        extracted_slots = {**semantic_slots, **exact_slots}

        # 用户第二轮可能只补充订单号等槽位。关键词降级模式容易把“订单号”误判成
        # 订单查询，因此只要该槽位属于上一轮意图，就继续原流程；真实LLM给出的明确
        # 新意图仍然保留，避免用户主动切换业务时被旧会话状态锁住。
        should_continue_current_intent = (
            state.current_intent
            and extracted_slots
            and (intent.intent == "unknown" or understanding.source == "keyword")
            and self._slots_belong_to_intent(state.current_intent, extracted_slots)
        )
        if should_continue_current_intent:
            intent = IntentResult(intent=state.current_intent, confidence=0.88)
            understanding = understanding.model_copy(
                update={
                    "intent": state.current_intent,
                    "confidence": 0.88,
                    "needs_clarification": False,
                }
            )

        # 4. SlotManager仍负责白名单过滤、格式校验和多轮槽位合并。
        state = self.slot_manager.merge(state, intent.intent, extracted_slots)

        # MCP Tool Schema成为动态业务参数的唯一来源。会话中保存参数，支持用户下一轮
        # 只补订单号；切换工具时清空旧参数，避免把上一笔业务数据带到新工具。
        self._merge_mcp_arguments(
            state,
            understanding,
            extracted_slots,
            preprocess.raw_text,
        )

        # 5. 策略层不再理解文本，只根据风险、置信度和槽位完整性做确定性决策。
        decision = self.rule_engine.decide(
            preprocess,
            intent,
            state,
            risk_level=understanding.risk_level,
            # 即使供应商模型错误标记澄清，明确且高置信度的意图也必须进入槽位完整性检查。
            needs_clarification=(
                understanding.needs_clarification
                and (
                    intent.intent == "unknown"
                    or intent.confidence < self.settings.understanding_confidence_threshold
                )
            ),
        )
        if (
            understanding.route_type in {"tool", "composite"}
            and understanding.tool_name
            and intent.confidence >= self.settings.understanding_confidence_threshold
            and decision.action not in {"handoff"}
        ):
            # 意图已经明确时，缺少多少业务参数都由MCP Schema追问，不再由通用意图
            # 澄清或YAML槽位规则覆盖。安全转人工仍然拥有最高优先级。
            decision = self._decide_mcp_route(state, understanding)
        if decision.action != "generate":
            provider = self._provider()
            await self.session_store.save(state)
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
                fallback_used=bool(understanding.error_message),
                understanding=understanding,
            )
            return self._build_result(
                started_at=started_at,
                answer=decision.answer or "",
                session_id=current_session_id,
                provider=provider,
                suggestions=decision.suggestions,
                intent=intent,
                decision=decision,
                state=state,
                preprocess=preprocess,
                understanding=understanding,
            )

        # 6. composite表示实时业务数据和知识规则都需要。两路互不依赖时并发执行，
        #    总耗时接近较慢的一路，而不是两次耗时相加。
        knowledge_requested = understanding.route_type in {"knowledge", "composite"}
        mcp_requested = understanding.route_type in {"tool", "composite"}
        if understanding.route_type == "legacy":
            # 保留旧意图配置的兼容路径，尚未迁移的奖励和积分Tool仍然可用。
            legacy_config = load_runtime_config().intents.get(state.current_intent or "")
            knowledge_requested = not bool(legacy_config and legacy_config.tool)

        async def call_tool() -> ToolResult | None:
            if mcp_requested and understanding.tool_name:
                return await self._call_mcp_business_tool(
                    current_session_id,
                    state,
                    understanding.tool_name,
                )
            if understanding.route_type == "legacy":
                return await self._call_business_tool(current_session_id, state)
            return None

        async def lookup_knowledge() -> SemanticLookup:
            if not knowledge_requested:
                return SemanticLookup()
            return await self.semantic_answer_service.lookup(
                understanding.knowledge_query or preprocess.normalized_text,
                intent.intent,
            )

        if mcp_requested and knowledge_requested:
            tool_result, semantic_lookup = await asyncio.gather(
                call_tool(),
                lookup_knowledge(),
            )
        else:
            tool_result = await call_tool()
            semantic_lookup = await lookup_knowledge()

        both_sources_available = bool(
            tool_result
            and tool_result.success
            and semantic_lookup.hit
        )
        if both_sources_available:
            # 组合查询只有这里调用回答模型：它不能新增事实，只把实时结果和规则合并。
            generate_result = await self.answer_generator.generate(
                message,
                state,
                history,
                tool_result,
                knowledge_answer=semantic_lookup.hit.answer,
                on_chunk=on_answer_chunk,
            )
        elif semantic_lookup.hit and understanding.route_type != "composite":
            if on_answer_chunk:
                await on_answer_chunk(semantic_lookup.hit.answer)
            generate_result = GenerateAnswerResult(
                answer=semantic_lookup.hit.answer,
                provider=semantic_lookup.hit.provider,
            )
        elif tool_result and tool_result.success and tool_result.direct_answer and tool_result.message:
            # Tool已经提供完整话术时直接返回，省去第二次LLM调用和对应等待时间。
            if on_answer_chunk:
                await on_answer_chunk(tool_result.message)
            generate_result = GenerateAnswerResult(
                answer=tool_result.message,
                provider=f"tool:{tool_result.tool_name}",
            )
        else:
            # 双检索未命中或Tool只返回原始数据时，由回答模型组织最终话术。
            generate_result = await self.answer_generator.generate(
                message,
                state,
                history,
                tool_result,
                knowledge_answer=(
                    semantic_lookup.hit.answer if semantic_lookup.hit else None
                ),
                on_chunk=on_answer_chunk,
            )

            # 只记录成功生成、未降级、无Tool的静态答案。达到不同会话频次门槛后，
            # 服务会写入unreviewed LangCache；投诉、转人工和动态业务不会进入缓存。
            if (
                tool_result is None
                and understanding.route_type != "composite"
                and semantic_lookup.hit is None
                and generate_result.provider == "doubao"
                and not generate_result.fallback_used
            ):
                await self.semantic_answer_service.record_generated_answer(
                    question=preprocess.normalized_text,
                    answer=generate_result.answer,
                    intent=intent.intent,
                    actor_id=current_session_id,
                    lookup=semantic_lookup,
                )
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
            fallback_used=(
                generate_result.fallback_used
                or bool(tool_result and not tool_result.success)
                or bool(understanding.error_message)
            ),
            understanding=understanding,
        )
        result = self._build_result(
            started_at=started_at,
            answer=generate_result.answer,
            session_id=current_session_id,
            provider=generate_result.provider,
            suggestions=decision.suggestions,
            intent=intent,
            decision=decision,
            state=state,
            preprocess=preprocess,
            understanding=understanding,
            tool_result=tool_result,
            semantic_lookup=semantic_lookup,
            knowledge_requested=knowledge_requested,
        )
        if (
            tool_result is not None
            and tool_result.success
            and understanding.tool_name
            and state.active_tool == understanding.tool_name
        ):
            self._complete_active_tool(state, understanding.tool_name)
        await self.session_store.save(state)
        return result

    async def _complete_quick_reply(
        self,
        quick_reply: QuickReply,
        provider: str,
        started_at: float,
        session_id: str,
        message: str,
        state: ConversationState,
        preprocess: PreprocessResult,
        understanding: UnderstandingResult,
        on_answer_chunk: AnswerChunkCallback | None,
    ) -> ChatOrchestrationResult:
        """统一完成快捷回复的流式输出、会话保存和日志埋点。"""
        intent = understanding.to_intent_result()
        decision = RouteDecision(
            action="quick_reply",
            answer=quick_reply.answer,
            suggestions=list(quick_reply.suggestions),
            reason=quick_reply.reason,
        )
        # 寒暄不会覆盖上一轮业务意图和槽位，只刷新当前会话的轮次与有效期。
        state.touch()

        # 流式接口先把固定话术交给浏览器，再完成Redis会话保存，降低首字等待时间。
        if on_answer_chunk:
            await on_answer_chunk(quick_reply.answer)
        await self.session_store.save(state)
        self._log_trace(
            started_at=started_at,
            session_id=session_id,
            message=message,
            preprocess=preprocess,
            intent=intent,
            state=state,
            decision=decision,
            provider=provider,
            tool_result=None,
            flow_error=None,
            fallback_used=bool(understanding.error_message),
            understanding=understanding,
        )
        return self._build_result(
            started_at=started_at,
            answer=quick_reply.answer,
            session_id=session_id,
            provider=provider,
            suggestions=list(quick_reply.suggestions),
            intent=intent,
            decision=decision,
            state=state,
            preprocess=preprocess,
            understanding=understanding,
        )

    async def _understand_with_pending_tool(
        self,
        preprocess: PreprocessResult,
        history: list[ChatHistoryItem],
        state: ConversationState,
    ) -> UnderstandingResult:
        """优先续填当前 Tool 参数，必要时才回到完整意图识别。"""
        current_slots = {code: slot.value for code, slot in state.slots.items()}
        if state.active_tool and self.mcp_tool_client is not None:
            definition = self.mcp_tool_client.get_tool(state.active_tool)
            if definition is not None:
                missing = self.tool_argument_resolver.missing_fields(
                    definition,
                    state.tool_arguments,
                )
                # 旧版本会在成功调用后把完整参数留在Redis，且没有tool_status。这样
                # 的状态不可能再处于“等待参数”，首次读到时按已完成任务迁移并清理。
                if state.tool_status is None:
                    if missing:
                        state.tool_status = "awaiting_args"
                    else:
                        self._complete_active_tool(state, state.active_tool)
                if missing:
                    resolution = self.tool_argument_resolver.resolve_structured(
                        preprocess.normalized_text,
                        definition,
                        state.tool_arguments,
                    )
                    if resolution.matched:
                        return UnderstandingResult(
                            intent=state.active_tool,
                            confidence=0.99,
                            requires_tool=True,
                            route_type="tool",
                            tool_name=state.active_tool,
                            tool_arguments=resolution.arguments,
                            source="keyword",
                        )

                    pending_understander = getattr(
                        self.understanding_service,
                        "understand_pending_tool",
                        None,
                    )
                    if callable(pending_understander):
                        pending = await pending_understander(
                            message=preprocess.normalized_text,
                            history=history,
                            current_intent=state.current_intent,
                            current_slots=current_slots,
                            current_tool=state.active_tool,
                        )
                        if pending is not None:
                            return pending

        return await self.understanding_service.understand(
            message=preprocess.normalized_text,
            history=history,
            current_intent=state.current_intent,
            current_slots=current_slots,
            current_tool=state.active_tool,
        )

    def _semantic_slot_values(
        self,
        understanding: UnderstandingResult,
        source_text: str,
    ) -> dict[str, SlotValue]:
        """把LLM字符串槽位转换成现有SlotValue对象。

        这里只生成候选值；允许哪些槽位、格式是否正确仍由SlotManager按YAML配置校验。
        """
        return {
            code: SlotValue(
                value=value,
                confidence=understanding.confidence,
                source_text=source_text,
                validated=False,
            )
            for code, value in understanding.slots.items()
        }

    def _slots_belong_to_intent(
        self,
        intent: str,
        extracted_slots: dict[str, SlotValue],
    ) -> bool:
        """判断本轮抽取出的槽位是否可用于当前多轮意图。"""
        intent_config = load_runtime_config().intents.get(intent)
        if not intent_config or not intent_config.slot_config:
            return False
        allowed_slots = set(intent_config.slot_config.slots)
        return bool(allowed_slots.intersection(extracted_slots))

    def _build_result(
        self,
        started_at: float,
        answer: str,
        session_id: str,
        provider: str,
        suggestions: list[str],
        intent: IntentResult,
        decision: RouteDecision,
        state: ConversationState,
        preprocess: PreprocessResult,
        understanding: UnderstandingResult,
        tool_result: ToolResult | None = None,
        semantic_lookup: SemanticLookup | None = None,
        knowledge_requested: bool = False,
    ) -> ChatOrchestrationResult:
        """统一生成应用层需要保存到PostgreSQL的结果。"""
        effective_emotion = (
            understanding.emotion
            if understanding.emotion != "normal"
            else preprocess.emotion
        )
        return ChatOrchestrationResult(
            answer=answer,
            session_id=session_id,
            provider=provider,
            suggestions=suggestions,
            intent=intent.intent,
            intent_confidence=intent.confidence,
            decision_action=decision.action,
            decision_reason=decision.reason,
            latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
            slots={code: slot.value for code, slot in state.slots.items()},
            emotion=effective_emotion,
            understanding_source=understanding.source,
            tool_name=tool_result.tool_name if tool_result else None,
            tool_success=tool_result.success if tool_result else None,
            tool_error_code=tool_result.error_code if tool_result else None,
            knowledge_requested=knowledge_requested,
            knowledge_attempted=bool(semantic_lookup and semantic_lookup.attempted),
            knowledge_hit=bool(semantic_lookup and semantic_lookup.hit),
        )

    def _merge_mcp_arguments(
        self,
        state: ConversationState,
        understanding: UnderstandingResult,
        extracted_slots: dict[str, SlotValue],
        source_text: str,
    ) -> None:
        """把本轮LLM参数和精确正则槽位合并到MCP多轮状态。"""
        tool_name = understanding.tool_name
        if not tool_name or self.mcp_tool_client is None:
            return
        definition = self.mcp_tool_client.get_tool(tool_name)
        if definition is None:
            return

        if state.active_tool and state.active_tool != tool_name:
            self._clear_active_tool(state)
        state.active_tool = tool_name
        state.tool_status = "awaiting_args"

        # 禁止模型覆盖可信系统字段；sessionId、userId、requestId只在调用前由代码注入。
        safe_model_arguments = self.tool_argument_resolver.sanitize_model_arguments(
            source_text,
            definition,
            understanding.tool_arguments,
        )
        for name, value in safe_model_arguments.items():
            state.tool_arguments[name] = value

        properties = definition.input_schema.get("properties", {})
        for slot_name, slot in extracted_slots.items():
            if not slot.validated:
                continue
            camel_name = self._snake_to_camel(slot_name)
            if camel_name in properties:
                state.tool_arguments[camel_name] = slot.value

    def _clear_active_tool_on_explicit_switch(
        self,
        state: ConversationState,
        understanding: UnderstandingResult,
    ) -> None:
        """明确的新业务终止旧待办；含糊输入继续保留上下文等待澄清。"""
        if not state.active_tool:
            return
        if (
            understanding.tool_name == state.active_tool
            and understanding.route_type in {"tool", "composite"}
        ):
            return
        if (
            understanding.intent == "unknown"
            or understanding.route_type == "unknown"
            or understanding.needs_clarification
            or understanding.confidence < self.settings.understanding_confidence_threshold
        ):
            return
        self._clear_active_tool(state)

    @staticmethod
    def _clear_active_tool(state: ConversationState) -> None:
        """结束当前待处理 Tool，同时销毁尚未消费的业务参数。"""
        state.active_tool = None
        state.tool_status = None
        state.tool_arguments.clear()

    def _complete_active_tool(
        self,
        state: ConversationState,
        tool_name: str,
    ) -> None:
        """成功调用后只保留 Tool 名作为历史上下文，不保留上次业务参数。"""
        state.last_tool = tool_name
        self._clear_active_tool(state)

    def _decide_mcp_route(
        self,
        state: ConversationState,
        understanding: UnderstandingResult,
    ) -> RouteDecision:
        """根据Java提供的Tool Schema判断参数是否完整并生成追问。"""
        definition = (
            self.mcp_tool_client.get_tool(understanding.tool_name)
            if self.mcp_tool_client is not None
            else None
        )
        if definition is None:
            return RouteDecision(
                action="generate",
                reason="mcp_tool_unavailable",
            )

        missing = [
            field
            for field in definition.user_required_fields
            if not str(state.tool_arguments.get(field, "")).strip()
        ]
        if not missing:
            return RouteDecision(
                action="generate",
                reason=(
                    "mcp_composite_ready"
                    if understanding.route_type == "composite"
                    else "mcp_tool_ready"
                ),
            )

        field = missing[0]
        properties = definition.input_schema.get("properties", {})
        description = str(properties.get(field, {}).get("description", "")).strip()
        if field == "orderId":
            question = "请提供需要查询的订单号。"
        elif description:
            question = f"为了继续办理，请提供{description}。"
        else:
            question = f"为了继续办理，请补充参数：{field}。"
        return RouteDecision(
            action="ask_slot",
            answer=question,
            reason=f"missing_mcp_argument:{field}",
        )

    async def _call_mcp_business_tool(
        self,
        session_id: str,
        state: ConversationState,
        tool_name: str,
    ) -> ToolResult:
        """通过MCP调用Java Tool；连接不可用时订单查询降级到原REST适配器。"""
        if self.mcp_tool_client is None:
            return ToolResult.skipped(tool_name, "MCP客户端尚未初始化。")
        result = await self.mcp_tool_client.call_tool(
            tool_name,
            state.tool_arguments,
            session_id=session_id,
            user_id=state.user_id or self.settings.demo_user_id,
            request_id=str(uuid.uuid4()),
        )
        if result.error_code == "TOOL_SKIPPED" and tool_name == "order_query":
            fallback = await self._call_business_tool(session_id, state)
            return fallback or result
        return result

    @staticmethod
    def _snake_to_camel(value: str) -> str:
        """把Python槽位名转换为Java Tool常用的camelCase参数名。"""
        head, *tail = value.split("_")
        return head + "".join(part[:1].upper() + part[1:] for part in tail)

    async def _call_business_tool(self, session_id: str, state: ConversationState) -> ToolResult | None:
        """根据当前意图配置调用业务工具。"""
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
        """把工具失败或回答模型失败统一转换成日志错误对象。"""
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
        understanding: UnderstandingResult,
    ) -> None:
        """记录一轮对话的结构化链路日志，包括语义理解来源和降级原因。"""
        slot_values = {code: slot.value for code, slot in state.slots.items()}
        effective_emotion = (
            understanding.emotion
            if understanding.emotion != "normal"
            else preprocess.emotion
        )
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
            emotion=effective_emotion,
            sensitive=preprocess.sensitive,
            understanding_source=understanding.source,
            understanding_error=understanding.error_message,
        )
        log_chat_trace(trace)

    def _provider(self) -> str:
        """返回当前回答来源。"""
        return "doubao" if self.settings.has_real_api_key else "local-fallback"
