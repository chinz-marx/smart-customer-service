from __future__ import annotations

import re

from app.session.store import ConversationState
from app.slots.definitions import INTENT_SLOT_CONFIGS
from app.slots.schemas import SlotValue


class SlotManager:
    """槽位状态管理器。

    负责把本轮抽到的槽位合并到会话状态，并判断槽位是否满足业务调用条件。
    """

    def merge(
        self,
        state: ConversationState,
        intent: str,
        extracted_slots: dict[str, SlotValue],
    ) -> ConversationState:
        """把本轮槽位合并进会话。

        如果用户切换到新的明确意图，就清空旧意图槽位，避免订单号串到别的业务里。
        """
        if state.current_intent and state.current_intent != intent and intent != "unknown":
            state.slots.clear()

        if intent != "unknown":
            state.current_intent = intent

        config = INTENT_SLOT_CONFIGS.get(state.current_intent or intent)
        for code, slot in extracted_slots.items():
            if config and code in config.slots:
                definition = config.slots[code]

                # 配置里有 validation 时，必须校验通过才算有效槽位。
                if definition.validation:
                    slot.validated = bool(re.fullmatch(definition.validation, slot.value))
                else:
                    # 没有正则的语义槽位（如活动名称）已通过当前意图的槽位白名单，
                    # 可以标记为有效；业务真实性仍应由后续Tool接口校验。
                    slot.validated = True

                # LLM有时会把“返现、奖励”等业务类别词误当成具体活动名称。
                # denied_values放在YAML中，运营调整业务词时不需要修改Python代码。
                if slot.value.strip() in definition.denied_values:
                    slot.validated = False
                state.slots[code] = slot

        state.touch()
        return state

    def is_ready(self, state: ConversationState) -> bool:
        """判断当前会话的槽位是否足够调用业务工具。"""
        if not state.current_intent:
            return False

        config = INTENT_SLOT_CONFIGS.get(state.current_intent)
        if not config:
            return False
        if config.ready_policy_type == "none":
            return True
        if config.ready_policy_type == "any_of":
            return any(self._has_valid_slot(state, slot) for slot in config.ready_policy_slots)
        if config.ready_policy_type == "all_of":
            return all(self._has_valid_slot(state, slot) for slot in config.ready_policy_slots)
        return False

    def build_missing_slot_question(self, state: ConversationState) -> str:
        """根据配置生成缺槽追问话术。"""
        if not state.current_intent:
            return "我还没理解您的具体问题。您可以补充说明是奖励、积分、权益、订单还是人工客服相关吗？"

        config = INTENT_SLOT_CONFIGS.get(state.current_intent)
        if not config:
            return "我还需要您补充一下具体问题类型，方便继续处理。"

        missing_prompts = [
            config.slots[slot].ask_prompt
            for slot in config.ready_policy_slots
            if slot in config.slots and not self._has_valid_slot(state, slot)
        ]

        # any_of 表示任意一个槽位满足即可，所以追问时把可选项一次性告诉用户。
        if config.ready_policy_type == "any_of" and missing_prompts:
            slot_names = "、".join(config.slots[slot].name for slot in config.ready_policy_slots if slot in config.slots)
            return f"为了帮您处理{config.name}，请提供{slot_names}中的任意一项。"
        if missing_prompts:
            return missing_prompts[0]
        return "我还需要您补充更多信息，方便继续处理。"

    def _has_valid_slot(self, state: ConversationState, slot_code: str) -> bool:
        """判断某个槽位是否存在且校验通过。"""
        slot = state.slots.get(slot_code)
        return bool(slot and slot.value and slot.validated)