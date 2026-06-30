from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class IntentCandidate:
    """一个候选意图及其置信度。"""

    intent: str
    confidence: float


@dataclass(slots=True)
class IntentResult:
    """意图识别结果。"""

    intent: str
    confidence: float
    candidates: list[IntentCandidate] = field(default_factory=list)

    @property
    def is_high_confidence(self) -> bool:
        """高置信度：可以直接进入业务流程。"""
        return self.confidence >= 0.85

    @property
    def is_medium_confidence(self) -> bool:
        """中置信度：需要让用户确认或补充。"""
        return 0.60 <= self.confidence < 0.85