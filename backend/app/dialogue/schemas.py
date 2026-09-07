from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


DialogueAct = Literal["start", "inform", "correct", "cancel", "interrupt", "resume", "followup", "unknown"]


class ContextModelOutput(BaseModel):
    """Only this turn's interpretation, never a model-generated state snapshot."""

    model_config = ConfigDict(extra="forbid")
    act: DialogueAct
    target: str | None = Field(max_length=128, description="工具名、系统路由、knowledge或给定的frame:ID；不明确为null")
    values: dict[Annotated[str, Field(min_length=1, max_length=128)], Annotated[str, Field(min_length=1, max_length=512)]] = Field(max_length=32, description="仅本轮原文明确提供的参数，不能复制历史参数")
    query: str | None = Field(max_length=1000, description="知识问题；没有为null")


class PendingQuestion(BaseModel):
    kind: Literal["slot", "selection", "confirmation"] = "slot"
    field: str | None = None
    candidates: list[str] = Field(default_factory=list, max_length=20)
    answer: str = ""


class TaskFrame(BaseModel):
    id: str
    tool: str
    arguments: dict[str, str] = Field(default_factory=dict)
    pending: PendingQuestion | None = None
    knowledge_query: str | None = None
    saved_at: float


class DialogueContext(BaseModel):
    """Bounded code-owned context. Active tool/arguments live in ConversationState."""

    frame_id: str | None = None
    pending: PendingQuestion | None = None
    knowledge_query: str | None = None
    suspended: list[TaskFrame] = Field(default_factory=list, max_length=5)
    recent: list[TaskFrame] = Field(default_factory=list, max_length=5)
    last_action: str | None = None
    argument_sources: dict[str, dict[str, str | int]] = Field(default_factory=dict)


def context_output_json_schema() -> dict:
    schema = ContextModelOutput.model_json_schema()
    schema["properties"]["values"]["additionalProperties"] = True
    return schema
