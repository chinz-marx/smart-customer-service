from __future__ import annotations

from app.configs.loader import load_runtime_config
from app.intent.schemas import IntentCandidate, IntentResult


class IntentClassifier:
    """基于配置关键词的轻量意图识别器。

    生产后可以替换成小模型或 LLM 分类，但返回结构保持 IntentResult 即可。
    """

    def classify(self, text: str) -> IntentResult:
        runtime_config = load_runtime_config()
        scores: dict[str, float] = {}

        # 关键词来自 intents.yaml，新增意图时不需要改这里的分类逻辑。
        for intent_code, intent_config in runtime_config.intents.items():
            scores[intent_code] = self._score(
                text=text,
                keywords=intent_config.keywords,
                priority_keywords=intent_config.priority_keywords,
            )

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return self._unknown_result()

        best_intent, best_score = ranked[0]
        if best_score <= 0:
            return self._unknown_result()

        candidates = [IntentCandidate(intent=intent, confidence=score) for intent, score in ranked if score > 0]
        return IntentResult(intent=best_intent, confidence=best_score, candidates=candidates)

    def _score(
        self,
        text: str,
        keywords: tuple[str, ...],
        priority_keywords: tuple[str, ...],
    ) -> float:
        """根据命中的关键词数量给一个简单置信度分数。"""
        if any(keyword in text for keyword in priority_keywords):
            return 0.95

        hits = sum(1 for keyword in keywords if keyword in text)
        if hits >= 2:
            return 0.92
        if hits == 1:
            return 0.78
        return 0.0

    def _unknown_result(self) -> IntentResult:
        """统一生成未知意图结果，方便规则引擎走澄清分支。"""
        return IntentResult(
            intent="unknown",
            confidence=0.30,
            candidates=[IntentCandidate(intent="unknown", confidence=0.30)],
        )