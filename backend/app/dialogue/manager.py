from __future__ import annotations

import re
import time
import uuid
from dataclasses import fields, replace
from typing import TYPE_CHECKING

from app.dialogue.schemas import PendingQuestion, TaskFrame
from app.understanding.schemas import UnderstandingResult

if TYPE_CHECKING:
    from app.session.store import ConversationState


class DialogueManager:
    """Rule-first interpretation and code-owned transitions. No tool execution here."""

    def __init__(self, understanding, tools, resolver, ttl_seconds: int = 1800, confidence_threshold: float = 0.65):
        self.understanding = understanding
        self.tools = tools
        self.resolver = resolver
        self.ttl_seconds = ttl_seconds
        self.confidence_threshold = confidence_threshold

    def prepare(self, state: ConversationState) -> None:
        cutoff = time.time() - self.ttl_seconds
        ctx = state.dialogue
        ctx.suspended = [f for f in ctx.suspended if f.saved_at > cutoff]
        ctx.recent = [f for f in ctx.recent if f.saved_at > cutoff]
        if state.active_tool and not ctx.frame_id:
            ctx.frame_id = uuid.uuid4().hex
        definition = self.tools.get_tool(state.active_tool) if self.tools else None
        if definition and state.tool_status is None:
            if self.resolver.missing_fields(definition, state.tool_arguments):
                state.tool_status = "awaiting_args"
            else:
                self.complete(state)

    @staticmethod
    def clear(state: ConversationState) -> None:
        state.active_tool = None
        state.tool_status = None
        state.tool_arguments.clear()
        state.slots.clear()
        state.current_intent = None
        ctx = state.dialogue
        ctx.frame_id = None
        ctx.pending = None
        ctx.knowledge_query = None
        ctx.argument_sources.clear()

    @staticmethod
    def snapshot(state: ConversationState) -> TaskFrame:
        return TaskFrame(
            id=state.dialogue.frame_id or uuid.uuid4().hex,
            tool=state.active_tool,
            arguments={k: v for k, v in state.tool_arguments.items() if k != "confirmed"},
            pending=state.dialogue.pending,
            knowledge_query=state.dialogue.knowledge_query,
            saved_at=time.time(),
        )

    def activate(self, state: ConversationState, frame: TaskFrame) -> None:
        self.clear(state)
        state.active_tool = frame.tool
        state.current_intent = frame.tool
        state.tool_status = "awaiting_args"
        state.tool_arguments = dict(frame.arguments)
        state.dialogue.frame_id = frame.id
        state.dialogue.pending = frame.pending
        state.dialogue.knowledge_query = frame.knowledge_query
        state.dialogue.argument_sources = {
            key: {"source": "frame", "frame_id": frame.id} for key in frame.arguments
        }

    def complete(self, state: ConversationState) -> None:
        if state.active_tool:
            frame = self.snapshot(state)
            frame.pending = None
            state.dialogue.recent = ([f for f in state.dialogue.recent if f.id != frame.id] + [frame])[-5:]
            state.last_tool = state.active_tool
        self.clear(state)
        state.dialogue.last_action = "completed"
        if state.dialogue.suspended:
            self.activate(state, state.dialogue.suspended.pop())

    @staticmethod
    def reply(answer: str, act="unknown") -> UnderstandingResult:
        return UnderstandingResult(
            intent="unknown", confidence=0, source="keyword", route_type="direct",
            dialogue_act=act, dialogue_answer=answer,
        )

    @staticmethod
    def continuation(state: ConversationState, values=None, act="inform") -> UnderstandingResult:
        query = state.dialogue.knowledge_query
        return UnderstandingResult(
            intent=state.active_tool, confidence=1.0, source="keyword",
            route_type="composite" if query else "tool", requires_tool=True,
            requires_knowledge=bool(query), knowledge_query=query,
            tool_name=state.active_tool, tool_arguments=values or {}, dialogue_act=act,
        )

    def resolve_rules(self, message: str, state: ConversationState) -> UnderstandingResult | None:
        self.prepare(state)
        text = message.strip().rstrip("。！？!?，,. ")
        if text in {"继续", "继续刚才的", "继续刚才的查询", "继续刚才的任务"}:
            if state.active_tool:
                return self.continuation(state, act="resume")
            if state.dialogue.suspended:
                self.activate(state, state.dialogue.suspended.pop())
                return self.continuation(state, act="resume")
            return self.reply("当前没有待继续的任务，请说明需要办理的业务。")
        if text in {"不查了", "不办了", "取消", "算了", "取消当前任务"}:
            if state.active_tool:
                self.clear(state)
                return self.reply("已取消当前任务。", "cancel")
            return self.reply("当前没有待取消的任务。", "cancel")
        pending = state.dialogue.pending
        if pending and pending.kind == "confirmation":
            if text in {"确认", "确认提交", "确认办理", "是的，确认", "是的,确认"}:
                state.tool_arguments["confirmed"] = "true"
                state.dialogue.argument_sources["confirmed"] = {"source": "confirmation", "turn": state.turn_count + 1}
                state.dialogue.pending = None
                return self.continuation(state)
            if text in {"否", "不确认", "不要提交"}:
                self.clear(state)
                return self.reply("已取消本次提交。", "cancel")
        if pending and text in {"好的", "好", "是的", "确认", "不是", "不对"}:
            # A bare acknowledgement cannot fill a business field or authorize a new operation.
            return self.reply(pending.answer or "请补充具体信息，方便继续处理。")
        if not state.active_tool or not self.tools:
            return None
        definition = self.tools.get_tool(state.active_tool)
        if definition is None:
            self.clear(state)
            return self.reply("该业务当前不可用，请重新说明需要办理的事项。")
        if pending and pending.kind == "selection":
            match = re.fullmatch(r"第([一二三四五六七八九十]|\d{1,2})个", text)
            if match:
                number = match[1]
                index = int(number) if number.isdigit() else "一二三四五六七八九十".index(number) + 1
                if not 1 <= index <= len(pending.candidates):
                    return self.reply(pending.answer)
                value = pending.candidates[index - 1]
                values = self.resolver.sanitize_model_arguments(value, definition, {pending.field: value})
                if values:
                    state.tool_arguments.update(values)
                    state.dialogue.argument_sources[pending.field] = {"source": "selection", "turn": state.turn_count + 1}
                    return self.continuation(state)
                return self.reply("所选信息已不可用，请重新提供。")
        correction = re.match(r"^(?:不对[，,]?|更正[：:]?|改成|换成|不是这个[，,]?)\s*(.+)$", text)
        candidate_text = correction[1] if correction else text
        existing = {} if correction else state.tool_arguments
        if pending and pending.kind == "slot" and pending.field and not correction and re.fullmatch(r"[A-Za-z0-9_.-]+", candidate_text):
            definition = replace(definition, input_schema={**definition.input_schema, "required": [pending.field]})
        resolution = self.resolver.resolve_structured(candidate_text, definition, existing)
        if resolution.matched:
            # Do not bind one unlabelled value to multiple similarly shaped fields.
            if len(resolution.arguments) > 1 and len(set(resolution.arguments.values())) < len(resolution.arguments):
                return self.reply("这条信息对应哪个字段？请带上字段名称说明。")
            return self.continuation(state, resolution.arguments, "correct" if correction else "inform")
        return None

    def prompt_context(self, state: ConversationState) -> dict:
        ctx = state.dialogue
        return {
            "tool": state.active_tool,
            "arguments": state.tool_arguments,
            "pending": ctx.pending.model_dump(exclude_none=True) if ctx.pending else None,
            "frames": [
                {"ref": f"frame:{f.id}", "tool": f.tool, "arguments": f.arguments,
                 "status": "suspended" if f in ctx.suspended else "completed"}
                for f in ctx.suspended + ctx.recent
            ],
        }

    async def understand(self, message: str, state: ConversationState, history) -> UnderstandingResult:
        if state.tool_status in {"executing", "uncertain"}:
            return self.reply("上一笔操作的处理结果尚未确认，请先核实结果，避免重复提交。")
        local = self.resolve_rules(message, state)
        if local is not None:
            return local
        context_understander = getattr(self.understanding, "understand_context", None)
        if callable(context_understander):
            result = await context_understander(
                message=message, history=history[-4:], current_intent=state.current_intent,
                current_slots={k: v.value for k, v in state.slots.items()},
                current_tool=state.active_tool, context=self.prompt_context(state),
            )
        else:
            # Compatibility for integrations that implement the old understanding interface.
            result = await self.understanding.understand(
                message=message, history=history, current_intent=state.current_intent,
                current_slots={k: v.value for k, v in state.slots.items()}, current_tool=state.active_tool,
            )
        return self.apply_interpretation(message, state, result)

    def apply_interpretation(self, message: str, state: ConversationState, result: UnderstandingResult) -> UnderstandingResult:
        # Validate against a detached state so an invalid correction/reference cannot
        # partially switch the live task before returning a clarification.
        candidate = type(state).from_dict(state.to_dict())
        resolved = self._apply_interpretation(message, candidate, result)
        if not resolved.dialogue_answer or resolved.dialogue_act == "cancel":
            for field in fields(state):
                setattr(state, field.name, getattr(candidate, field.name))
        return resolved

    def _apply_interpretation(self, message: str, state: ConversationState, result: UnderstandingResult) -> UnderstandingResult:
        if result.risk_level == "high" or result.intent in {"human_handoff", "complaint"}:
            return result
        if result.confidence < self.confidence_threshold and result.intent != "unknown":
            return self.reply("暂时无法确定您的意思，请补充具体问题。")
        if result.target_frame_id:
            frames = state.dialogue.suspended + state.dialogue.recent
            frame = next((f for f in frames if f.id == result.target_frame_id), None)
            if frame is None or not self.tools or not self.tools.get_tool(frame.tool):
                return self.reply("无法确定您指的是哪项业务，请补充说明。")
            if result.requires_knowledge and not result.requires_tool:
                # Do not send account IDs/tokens into a shared static knowledge index.
                return result
            if result.dialogue_act not in {"resume", "correct", "followup"}:
                return self.reply("请说明要如何处理刚才的业务。")
            if frame in state.dialogue.recent and result.dialogue_act == "resume":
                return self.reply("该任务已经完成；如需重新查询，请明确说明。")
            if state.active_tool and state.dialogue.frame_id != frame.id:
                if len(state.dialogue.suspended) >= 5:
                    return self.reply("待办任务较多，请先完成或取消当前任务。")
                state.dialogue.suspended.append(self.snapshot(state))
            state.dialogue.suspended = [f for f in state.dialogue.suspended if f.id != frame.id]
            self.activate(state, frame)
            result = result.model_copy(update={"tool_name": frame.tool, "intent": frame.tool})
        if result.dialogue_act == "cancel":
            if not state.active_tool:
                return self.reply("当前没有待取消的任务。", "cancel")
            self.clear(state)
            return self.reply("已取消当前任务。", "cancel")
        if result.needs_clarification or result.intent == "unknown":
            return self.reply("请说明是继续当前业务，还是需要办理其他事项。" if state.active_tool else "请补充具体问题，方便为您处理。")
        if result.dialogue_act == "correct" and result.requires_tool:
            definition = self.tools.get_tool(result.tool_name) if self.tools else None
            valid = self.resolver.sanitize_model_arguments(message, definition, result.tool_arguments) if definition else {}
            if not valid or set(valid) != set(result.tool_arguments):
                return self.reply("请提供更正后的具体信息。")
        elif result.requires_tool and state.active_tool == result.tool_name:
            definition = self.tools.get_tool(result.tool_name) if self.tools else None
            if definition:
                valid = self.resolver.sanitize_model_arguments(message, definition, result.tool_arguments)
                if any(key in state.tool_arguments and key not in valid for key in result.tool_arguments):
                    return self.reply("新提供的信息未通过校验，请核对后重新提供。")
        if result.dialogue_act == "interrupt" and state.active_tool != result.tool_name and len(state.dialogue.suspended) >= 5:
            return self.reply("待办任务较多，请先完成或取消当前任务。")
        return result

    def switch(self, state: ConversationState, result: UnderstandingResult) -> None:
        if not state.active_tool or not result.requires_tool:
            return
        if state.active_tool == result.tool_name and result.dialogue_act != "start":
            return
        if result.dialogue_act == "interrupt":
            state.dialogue.suspended = (state.dialogue.suspended + [self.snapshot(state)])[-5:]
        self.clear(state)

    def record_arguments(self, state: ConversationState, values: dict[str, str]) -> None:
        if not state.dialogue.frame_id:
            state.dialogue.frame_id = uuid.uuid4().hex
        for key, value in values.items():
            state.dialogue.argument_sources[key] = {
                "source": "message", "turn": state.turn_count, "evidence": value,
            }

    @staticmethod
    def ask(state: ConversationState, field: str, answer: str) -> None:
        state.dialogue.pending = PendingQuestion(field=field, answer=answer)
        state.dialogue.last_action = "ask_slot"

    def ask_selection(self, state: ConversationState, field: str, values: list[str]) -> str:
        """Only trusted schema/adapter values can create a displayed selection."""
        definition = self.tools.get_tool(state.active_tool) if self.tools else None
        if not definition or not 1 <= len(values) <= 20:
            raise ValueError("无效的候选列表")
        if any(field not in self.resolver.sanitize_model_arguments(v, definition, {field: v}) for v in values):
            raise ValueError("候选项未通过工具Schema校验")
        schema = definition.input_schema.get("properties", {}).get(field, {})
        label = schema.get("description") or "需要的信息"
        answer = f"请选择{label}：\n" + "\n".join(f"{i}. {v}" for i, v in enumerate(values, 1))
        state.dialogue.pending = PendingQuestion(kind="selection", field=field, candidates=values, answer=answer)
        state.dialogue.last_action = "ask_selection"
        return answer
