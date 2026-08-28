from __future__ import annotations

from dataclasses import dataclass, field

from app.configs.loader import load_runtime_config
from app.intent.schemas import IntentResult
from app.preprocessing.normalizer import PreprocessResult
from app.session.store import ConversationState
from app.slots.manager import SlotManager


@dataclass(slots=True)
class RouteDecision:
    """策略路由器的决策结果。"""

    action: str
    answer: str | None = None
    suggestions: list[str] = field(default_factory=list)
    reason: str = ""


class RuleEngine:
    """安全和业务策略路由层。

    意图和语义槽位现在由UnderstandingService负责；这里不重复理解用户文本，
    只根据风险、置信度和槽位完整性决定下一步，保证业务执行可控。
    """

    def __init__(self, slot_manager: SlotManager, confidence_threshold: float = 0.65) -> None:
        self.slot_manager = slot_manager
        self.confidence_threshold = confidence_threshold

    def decide(
        self,
        preprocess: PreprocessResult,
        intent: IntentResult,
        state: ConversationState,
        risk_level: str = "low",
        needs_clarification: bool = False,
    ) -> RouteDecision:
        """根据安全风险、意图置信度和槽位状态做确定性路由。"""
        # 本地敏感词和LLM高风险判断任意一个命中，都不继续调用业务工具。
        if preprocess.sensitive or risk_level == "high":
            return RouteDecision(
                action="handoff",
                answer="这个问题可能涉及敏感信息。为了保护您的账户安全，建议转人工客服处理。",
                suggestions=["联系人工客服", "重新描述问题", "查看帮助中心"],
                reason="sensitive_risk" if preprocess.sensitive else "llm_high_risk",
            )

        # 明确的人工诉求属于执行策略，优先于普通澄清，避免让用户重复要求转人工。
        if intent.intent == "human_handoff":
            return RouteDecision(
                action="handoff",
                answer="好的，我已为您记录转人工诉求。稍后会把当前问题和上下文一并交给人工客服继续处理。",
                suggestions=self._suggestions_for_intent(intent.intent),
                reason="human_handoff_intent",
            )

        # 模型明确表示需要澄清时，即使给出了猜测意图，也不能贸然执行Tool。
        if (
            needs_clarification
            or intent.intent == "unknown"
            or intent.confidence < self.confidence_threshold
        ):
            return RouteDecision(
                action="clarify",
                answer="我还没完全理解您的问题。您可以补充说明是奖励、积分、权益、订单还是人工客服相关吗？",
                suggestions=["奖励未到账怎么办?", "积分怎么查询?", "联系人工客服"],
                reason="low_intent_confidence",
            )


        # 中等置信度先让用户确认，避免误调用查询、退款等业务接口。
        if intent.confidence < 0.85:
            return RouteDecision(
                action="confirm_intent",
                answer="我理解您可能是在咨询奖励、积分或人工客服相关问题。您可以再补充一句具体想处理的事项吗？",
                suggestions=self._suggestions_for_intent(intent.intent),
                reason="medium_intent_confidence",
            )

        if not self.slot_manager.is_ready(state):
            return RouteDecision(
                action="ask_slot",
                answer=self.slot_manager.build_missing_slot_question(state),
                suggestions=self._suggestions_for_intent(intent.intent),
                reason="missing_required_slots",
            )

        return RouteDecision(
            action="generate",
            suggestions=self._suggestions_for_intent(intent.intent),
            reason="ready_for_answer",
        )

    def _suggestions_for_intent(self, intent: str) -> list[str]:
        """从意图配置读取推荐问题，避免把业务话术散落在代码里。"""
        intent_config = load_runtime_config().intents.get(intent)
        if intent_config and intent_config.suggestions:
            return list(intent_config.suggestions)
        return ["奖励未到账怎么办?", "积分怎么查询?", "联系人工客服"]