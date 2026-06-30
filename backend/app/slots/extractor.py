from __future__ import annotations

import re

from app.preprocessing.normalizer import PreprocessResult
from app.slots.schemas import SlotValue


class SlotExtractor:
    """槽位抽取器。

    它根据当前意图，从用户文本里抽取业务字段，比如订单号、活动名、手机号后四位。
    """

    def extract(self, preprocess: PreprocessResult, intent: str) -> dict[str, SlotValue]:
        """抽取当前轮次的槽位。"""
        text = preprocess.normalized_text

        # 预处理层已经抽到的通用实体直接转成槽位候选。
        slots: dict[str, SlotValue] = {
            code: SlotValue(value=value, confidence=0.95, source_text=preprocess.raw_text)
            for code, value in preprocess.entities.items()
        }

        # 奖励未到账额外关心活动名称，这里先用轻量规则抽取。
        if intent == "reward_not_received":
            activity = self._extract_activity_name(text)
            if activity and "activity_name" not in slots:
                slots["activity_name"] = SlotValue(
                    value=activity,
                    confidence=0.72,
                    source_text=preprocess.raw_text,
                )

        return slots

    def _extract_activity_name(self, text: str) -> str | None:
        """抽取活动名称。

        这里故意不把“我的奖励”这类泛词当活动名，避免误抽。
        """
        explicit = re.search(r"(?:活动名称|活动)[:：是\s]*([\u4e00-\u9fa5A-Za-z0-9_-]{2,30})", text)
        if explicit:
            return explicit.group(1)

        activity_like = re.search(r"([\u4e00-\u9fa5A-Za-z0-9_-]{2,20}(?:返现|返利|活动))", text)
        if activity_like:
            return activity_like.group(1)

        return None