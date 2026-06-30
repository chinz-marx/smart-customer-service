from __future__ import annotations

from dataclasses import dataclass, field

from app.configs.loader import load_runtime_config
from app.intent.schemas import IntentResult
from app.preprocessing.normalizer import PreprocessResult
from app.session.store import ConversationState
from app.slots.manager import SlotManager


@dataclass(slots=True)
class RouteDecision:
    """规则引擎的决策结果。"""

    action: str
    answer: str | None = None
    suggestions: list[str] = field(default_factory=list)
    reason: str = ""


class RuleEngine:
    """规则决策层。

    这里决定当前轮应该追问、澄清、转人工，还是继续调用业务工具和生成答案。
    """

    def __init__(self, slot_manager: SlotManager) -> None:
        self.slot_manager = slot_manager

    def decide(
        self,
        preprocess: PreprocessResult,
        intent: IntentResult,
        state: ConversationState,
    ) -> RouteDecision:
        """根据预处理、意图和槽位状态做路由决策。"""
        if preprocess.sensitive:
            return RouteDecision(
                action="handoff",
                answer="这个问题可能涉及敏感信息。为了保护您的账户安全，建议转人工客服处理。",
                suggestions=["联系人工客服", "重新描述问题", "查看帮助中心"],
                reason="sensitive_risk",
            )

        if intent.intent == "unknown" or intent.confidence < 0.60:
            return RouteDecision(
                action="clarify",
                answer="我还没完全理解您的问题。您可以补充说明是奖励、积分、权益、订单还是人工客服相关吗？",
                suggestions=["奖励未到账怎么办?", "积分怎么查询?", "联系人工客服"],
                reason="low_intent_confidence",
            )

        if intent.is_medium_confidence:
            return RouteDecision(
                action="confirm_intent",
                answer="我理解您可能是在咨询奖励、积分或人工客服相关问题。您可以再补充一句具体想处理的事项吗？",
                suggestions=self._suggestions_for_intent(intent.intent),
                reason="medium_intent_confidence",
            )

        if intent.intent == "human_handoff":
            return RouteDecision(
                action="handoff",
                answer="好的，我已为您记录转人工诉求。稍后会把当前问题和上下文一并交给人工客服继续处理。",
                suggestions=self._suggestions_for_intent(intent.intent),
                reason="human_handoff_intent",
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
        """从配置里读取当前意图的推荐问题。"""
        intent_config = load_runtime_config().intents.get(intent)
        if intent_config and intent_config.suggestions:
            return list(intent_config.suggestions)
        return ["奖励未到账怎么办?", "积分怎么查询?", "联系人工客服"]