from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class PreprocessResult:
    """文本预处理结果。

    后续意图识别、槽位抽取、规则判断都会读取这个结构。
    """

    raw_text: str
    normalized_text: str
    entities: dict[str, str] = field(default_factory=dict)
    emotion: str = "normal"
    sensitive: bool = False


class TextPreprocessor:
    """文本预处理器。

    这一层只做低风险的清洗和基础实体抽取，不做复杂业务判断。
    """

    def normalize(self, text: str) -> PreprocessResult:
        """清洗用户输入，并输出结构化预处理结果。"""
        normalized = text.strip()
        normalized = normalized.replace("？", "?").replace("，", ",").replace("。", ".")

        # 把换行、Tab、多个空格统一成一个空格，方便正则和关键词识别。
        normalized = re.sub(r"\s+", " ", normalized)
        return PreprocessResult(
            raw_text=text,
            normalized_text=normalized,
            entities=self._extract_basic_entities(normalized),
            emotion=self._detect_emotion(normalized),
            sensitive=self._has_sensitive_risk(normalized),
        )

    def _extract_basic_entities(self, text: str) -> dict[str, str]:
        """抽取跨意图通用的基础实体。"""
        entities: dict[str, str] = {}

        # 订单号格式先放宽，真实生产可以按业务订单规则再收紧。
        order_match = re.search(r"(?:订单号|订单|单号)[:：是\s]*([A-Za-z0-9_-]{6,64})", text)
        if order_match:
            entities["order_id"] = order_match.group(1)

        phone_tail_match = re.search(r"(?:手机号后四位|手机尾号|尾号)[:：是\s]*(\d{4})", text)
        if phone_tail_match:
            entities["phone_tail"] = phone_tail_match.group(1)

        return entities

    def _detect_emotion(self, text: str) -> str:
        """非常轻量的情绪识别，后续可替换为模型或规则库。"""
        angry_words = ("投诉", "差评", "生气", "骗人", "垃圾", "退钱", "人工")
        if any(word in text for word in angry_words):
            return "negative"
        return "normal"

    def _has_sensitive_risk(self, text: str) -> bool:
        """识别敏感信息风险，命中后由规则引擎引导转人工或安全兜底。"""
        sensitive_words = ("身份证", "银行卡", "密码", "验证码")
        return any(word in text for word in sensitive_words)