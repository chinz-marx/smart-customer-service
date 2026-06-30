from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SlotDefinition:
    """槽位定义，来自 intents.yaml。"""

    code: str
    name: str
    ask_prompt: str
    required: bool = False
    validation: str | None = None


@dataclass(slots=True)
class IntentSlotConfig:
    """某个意图对应的槽位配置和满足条件。"""

    intent: str
    name: str
    slots: dict[str, SlotDefinition]
    ready_policy_type: str = "all_of"
    ready_policy_slots: tuple[str, ...] = ()
    tool: str | None = None


@dataclass(slots=True)
class SlotValue:
    """运行时抽取到的槽位值。"""

    value: str
    confidence: float
    source_text: str
    validated: bool = True