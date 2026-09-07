from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.intent.schemas import IntentCandidate, IntentResult
from app.dialogue.schemas import DialogueAct


UnderstandingRoute = Literal[
    "greeting",
    "system_identity",
    "system_capability",
    "complaint",
    "human_handoff",
    "tool",
    "knowledge",
    "composite",
    "unknown",
]


class UnderstandingModelOutput(BaseModel):
    """理解模型通过JSON Schema返回的最小决策结构。"""

    model_config = ConfigDict(extra="forbid")

    route: UnderstandingRoute = Field(description="系统路由编码或执行来源")
    tool: str | None = Field(description="选中的MCP工具名；不需要工具时为null")
    arguments: dict[str, str] = Field(description="用户明确提供的工具参数")
    knowledge_query: str | None = Field(max_length=1000, description="需要检索的知识问题")
    confidence: float = Field(ge=0.0, le=1.0, description="路由置信度")
    risk: Literal["low", "medium", "high"] = Field(description="敏感信息风险")

    @field_validator("arguments", mode="before")
    @classmethod
    def normalize_nullable_arguments(cls, value: object) -> object:
        """兼容null并把动态参数值转换成内部统一字符串。"""
        if value is None:
            return {}
        if isinstance(value, dict):
            return {str(name): str(argument) for name, argument in value.items()}
        return value

    @field_validator("arguments")
    @classmethod
    def normalize_arguments(cls, arguments: dict[str, str]) -> dict[str, str]:
        """清理动态MCP参数，避免模型输出直接进入业务工具。"""
        normalized: dict[str, str] = {}
        for name, value in arguments.items():
            clean_name = str(name).strip()[:128]
            clean_value = str(value).strip()[:512]
            if clean_name and clean_value:
                normalized[clean_name] = clean_value
        return normalized


def understanding_output_json_schema() -> dict[str, object]:
    """生成DeepSeek Responses兼容的六字段JSON Schema。

    MCP参数名由Java目录动态决定，无法在静态Schema中枚举。DeepSeek要求
    additionalProperties是布尔值，因此供应商侧允许动态键，再由Pydantic和
    MCP Schema在Python侧完成值清理与参数白名单校验。
    """
    schema = UnderstandingModelOutput.model_json_schema()
    arguments_schema = schema["properties"]["arguments"]
    arguments_schema["additionalProperties"] = True
    return schema


class UnderstandingResult(BaseModel):
    """LLM或关键词兜底返回的统一语义理解结果。

    主编排器只依赖这个结构，不关心结果究竟来自LLM还是关键词规则。
    """

    intent: str = Field(default="unknown", min_length=1, max_length=64)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    slots: dict[str, str] = Field(default_factory=dict)
    emotion: Literal["normal", "negative", "urgent"] = "normal"
    risk_level: Literal["low", "medium", "high"] = "low"
    needs_clarification: bool = False
    # Tool和知识需求独立判断，再由代码合成route_type，可显著减少组合诉求被压成单一路由。
    requires_tool: bool = False
    requires_knowledge: bool = False
    # legacy兼容现有YAML意图路由；tool/knowledge/composite是新的执行计划。
    route_type: Literal[
        "legacy", "tool", "knowledge", "composite", "direct", "system", "unknown"
    ] = "legacy"
    tool_name: str | None = Field(default=None, max_length=128)
    tool_arguments: dict[str, str] = Field(default_factory=dict)
    knowledge_query: str | None = Field(default=None, max_length=1000)
    source: Literal["llm", "keyword", "llm-error"] = "llm"
    error_message: str | None = None
    dialogue_act: DialogueAct = "start"
    target_frame_id: str | None = None
    # Set by code only; never included in the model output schema.
    dialogue_answer: str | None = None

    @field_validator("slots", "tool_arguments", mode="before")
    @classmethod
    def normalize_nullable_mappings(cls, value: object) -> object:
        """兼容模型把空对象输出为null，避免合法路由进入异常降级链路。"""
        return {} if value is None else value

    @field_validator("slots")
    @classmethod
    def normalize_slots(cls, slots: dict[str, str]) -> dict[str, str]:
        """清理模型返回的槽位，丢弃空值并限制单个值的长度。

        LLM输出属于不可信输入，即使JSON格式正确，也不能未经处理直接进入业务工具。
        """
        normalized: dict[str, str] = {}
        for code, value in slots.items():
            clean_code = str(code).strip()[:64]
            clean_value = str(value).strip()[:256]
            if clean_code and clean_value:
                normalized[clean_code] = clean_value
        return normalized

    @field_validator("tool_arguments")
    @classmethod
    def normalize_tool_arguments(cls, arguments: dict[str, str]) -> dict[str, str]:
        """MCP参数同样来自不可信模型输出，调用Java前先做基础清理。"""
        normalized: dict[str, str] = {}
        for name, value in arguments.items():
            clean_name = str(name).strip()[:128]
            clean_value = str(value).strip()[:512]
            if clean_name and clean_value:
                normalized[clean_name] = clean_value
        return normalized

    def to_intent_result(self) -> IntentResult:
        """转换成现有规则引擎使用的IntentResult，减少其他模块改动。"""
        return IntentResult(
            intent=self.intent,
            confidence=self.confidence,
            candidates=[IntentCandidate(intent=self.intent, confidence=self.confidence)],
        )
