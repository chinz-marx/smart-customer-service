from __future__ import annotations

from app.preprocessing.normalizer import PreprocessResult
from app.slots.schemas import SlotValue


class SlotExtractor:
    """精确槽位抽取器。

    这里只接收预处理层通过正则提取的订单号、手机号后四位等格式明确字段。
    活动名称等语义字段由UnderstandingService中的LLM负责，避免两套逻辑互相覆盖。
    """

    def extract(self, preprocess: PreprocessResult, intent: str) -> dict[str, SlotValue]:
        """把预处理得到的精确实体转换成运行时槽位。"""
        return {
            code: SlotValue(
                value=value,
                confidence=0.95,
                source_text=preprocess.raw_text,
            )
            for code, value in preprocess.entities.items()
        }