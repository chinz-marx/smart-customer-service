from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.slots.schemas import IntentSlotConfig, SlotDefinition


CONFIG_DIR = Path(__file__).resolve().parent
INTENTS_CONFIG_PATH = CONFIG_DIR / "intents.yaml"


@dataclass(slots=True)
class IntentRuntimeConfig:
    """单个意图的运行时配置。"""

    code: str
    name: str
    description: str = ""
    examples: tuple[str, ...] = ()
    response_strategy: str = "TOOL_LLM"
    keywords: tuple[str, ...] = ()
    priority_keywords: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()
    tool: str | None = None
    slot_config: IntentSlotConfig | None = None


@dataclass(slots=True)
class CustomerServiceRuntimeConfig:
    """客服系统的全部运行时配置。"""

    intents: dict[str, IntentRuntimeConfig] = field(default_factory=dict)
    slot_configs: dict[str, IntentSlotConfig] = field(default_factory=dict)
    multiple_intent_priority: tuple[str, ...] = ()
    high_risk_action: str = "human_handoff"


@lru_cache
def load_runtime_config() -> CustomerServiceRuntimeConfig:
    """读取并缓存业务配置。

    YAML只在进程内第一次使用时读取，避免每次聊天请求都访问磁盘。
    """
    raw_config = _read_yaml(INTENTS_CONFIG_PATH)
    raw_intents = raw_config.get("intents", {})
    if not isinstance(raw_intents, dict):
        raise ValueError("intents.yaml must contain an 'intents' mapping")

    raw_routing_policy = raw_config.get("routing_policy", {})
    if not isinstance(raw_routing_policy, dict):
        raise ValueError("routing_policy must be a mapping")

    runtime_config = CustomerServiceRuntimeConfig(
        multiple_intent_priority=_as_str_tuple(
            raw_routing_policy.get("multiple_intent_priority", [])
        ),
        high_risk_action=str(
            raw_routing_policy.get("high_risk_action", "human_handoff")
        ),
    )
    for intent_code, intent_data in raw_intents.items():
        if not isinstance(intent_data, dict):
            raise ValueError(f"Intent config for {intent_code!r} must be a mapping")

        slot_config = _build_slot_config(intent_code, intent_data)
        intent_config = IntentRuntimeConfig(
            code=intent_code,
            name=str(intent_data.get("name", intent_code)),
            description=str(intent_data.get("description", "")),
            examples=_as_str_tuple(intent_data.get("examples", [])),
            response_strategy=str(intent_data.get("response_strategy", "TOOL_LLM")),
            keywords=_as_str_tuple(intent_data.get("keywords", [])),
            priority_keywords=_as_str_tuple(intent_data.get("priority_keywords", [])),
            suggestions=_as_str_tuple(intent_data.get("suggestions", [])),
            tool=intent_data.get("tool"),
            slot_config=slot_config,
        )
        runtime_config.intents[intent_code] = intent_config
        runtime_config.slot_configs[intent_code] = slot_config

    _validate_routing_policy(runtime_config)
    return runtime_config


def _validate_routing_policy(runtime_config: CustomerServiceRuntimeConfig) -> None:
    """保证多意图优先级没有遗漏、重复或引用不存在的意图。"""
    priority = runtime_config.multiple_intent_priority
    if len(priority) != len(set(priority)):
        raise ValueError("multiple_intent_priority contains duplicate intents")

    configured = set(runtime_config.intents)
    prioritized = set(priority)
    if configured != prioritized:
        missing = sorted(configured - prioritized)
        unknown = sorted(prioritized - configured)
        raise ValueError(
            "multiple_intent_priority must contain every configured intent exactly once; "
            f"missing={missing}, unknown={unknown}"
        )
    if runtime_config.high_risk_action not in configured:
        raise ValueError("high_risk_action must reference a configured intent")


def _read_yaml(path: Path) -> dict[str, Any]:
    """安全读取YAML配置文件。"""
    with path.open("r", encoding="utf-8") as file:
        content = yaml.safe_load(file) or {}
    if not isinstance(content, dict):
        raise ValueError(f"{path.name} must contain a YAML mapping")
    return content


def _build_slot_config(intent_code: str, intent_data: dict[str, Any]) -> IntentSlotConfig:
    """把YAML中的槽位配置转换成代码里使用的dataclass。"""
    raw_slots = intent_data.get("slots", {})
    if not isinstance(raw_slots, dict):
        raise ValueError(f"slots for {intent_code!r} must be a mapping")

    slots: dict[str, SlotDefinition] = {}
    for slot_code, slot_data in raw_slots.items():
        if not isinstance(slot_data, dict):
            raise ValueError(f"slot {slot_code!r} for {intent_code!r} must be a mapping")
        slots[slot_code] = SlotDefinition(
            code=slot_code,
            name=str(slot_data.get("name", slot_code)),
            ask_prompt=str(slot_data.get("ask_prompt", "")),
            required=bool(slot_data.get("required", False)),
            validation=slot_data.get("validation"),
            denied_values=_as_str_tuple(slot_data.get("denied_values", [])),
        )

    raw_policy = intent_data.get("ready_policy", {})
    if not isinstance(raw_policy, dict):
        raise ValueError(f"ready_policy for {intent_code!r} must be a mapping")

    return IntentSlotConfig(
        intent=intent_code,
        name=str(intent_data.get("name", intent_code)),
        slots=slots,
        ready_policy_type=str(raw_policy.get("type", "all_of")),
        ready_policy_slots=_as_str_tuple(raw_policy.get("slots", [])),
        tool=intent_data.get("tool"),
    )


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """把YAML列表统一转换成不可变tuple。"""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"Expected a list, got {type(value).__name__}")
    return tuple(str(item) for item in value)