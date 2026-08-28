from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.errors import ChatFlowError, safe_error_message
from app.prompts.registry import PromptRegistry
from app.schemas import ChatHistoryItem
from app.session.store import ConversationState
from app.tools.schemas import ToolResult


# 流式回调接收模型本次产生的文本增量，应用层通过它转发给浏览器。
AnswerChunkCallback = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class GenerateAnswerResult:
    """回答生成结果。"""

    answer: str
    provider: str
    fallback_used: bool = False
    error: ChatFlowError | None = None


class AnswerGenerator:
    """回答生成器。

    有真实 API Key 时调用豆包/OpenAI 兼容接口；没有 Key 时走本地兜底，方便开发测试。
    """

    def __init__(
        self,
        settings: Settings,
        prompt_registry: PromptRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.prompt_registry = prompt_registry or PromptRegistry(settings, None)
        # CustomerServiceAgent会复用本生成器，因此客户端也可以复用HTTP连接池。
        self._llm: ChatOpenAI | None = None

    async def generate(
        self,
        message: str,
        state: ConversationState,
        history: list[ChatHistoryItem],
        tool_result: ToolResult | None = None,
        knowledge_answer: str | None = None,
        on_chunk: AnswerChunkCallback | None = None,
    ) -> GenerateAnswerResult:
        """根据会话状态和业务工具结果生成最终回复。

        模型调用失败时不会抛出异常，而是返回本地兜底答案。
        """
        if not self.settings.has_real_api_key:
            answer = self._local_answer(state, tool_result, knowledge_answer)
            if on_chunk:
                await on_chunk(answer)
            return GenerateAnswerResult(
                answer=answer,
                provider="local-fallback",
            )

        streamed_parts: list[str] = []
        try:
            llm = self._get_llm()

            # Prompt 中显式给出“业务工具结果”，约束 LLM 基于事实组织语言。
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        self.prompt_registry.get("smart-customer-answer-system"),
                    ),
                    MessagesPlaceholder("history"),
                    (
                        "human",
                        self.prompt_registry.get("smart-customer-answer-user"),
                    ),
                ]
            )
            prompt_values = {
                "message": message,
                "intent": state.current_intent or "unknown",
                "slots": {code: slot.value for code, slot in state.slots.items()},
                "tool_result": self._tool_result_payload(tool_result),
                "knowledge_result": knowledge_answer,
                "history": self._to_langchain_history(history),
            }
            chain = prompt | llm

            # 这里限制的是“包含SDK重试在内”的总时间，确保Windows和Linux都不会无限等待。
            async with asyncio.timeout(self.settings.doubao_timeout_seconds):
                if on_chunk is None:
                    result = await chain.ainvoke(prompt_values)
                    answer = self._message_content_to_text(result.content)
                else:
                    # astream会在模型每次返回新内容时立即产生AIMessageChunk。
                    async for chunk in chain.astream(prompt_values):
                        text = self._message_content_to_text(chunk.content)
                        if not text:
                            continue
                        streamed_parts.append(text)
                        await on_chunk(text)
                    answer = "".join(streamed_parts)

            if not answer.strip():
                raise ValueError("回答模型没有返回文本内容")
            return GenerateAnswerResult(answer=answer, provider="doubao")
        except Exception as exc:
            error = ChatFlowError(
                stage="llm",
                error_type=exc.__class__.__name__,
                message=safe_error_message(exc),
                fallback_used=True,
            )
            if streamed_parts:
                # 浏览器已经看到部分内容时无法撤回，因此追加明确的中断提示并按完整文本落库。
                suffix = "\n\n抱歉，回答生成中断，请稍后重试或联系人工客服。"
                if on_chunk is not None:
                    await on_chunk(suffix)
                return GenerateAnswerResult(
                    answer="".join(streamed_parts) + suffix,
                    provider="doubao-partial",
                    fallback_used=True,
                    error=error,
                )

            answer = self._local_answer(state, tool_result, knowledge_answer)
            if on_chunk:
                await on_chunk(answer)
            return GenerateAnswerResult(
                answer=answer,
                provider="local-fallback",
                fallback_used=True,
                error=error,
            )

    def _get_llm(self) -> ChatOpenAI:
        """延迟创建并复用回答模型客户端，减少连续对话的连接开销。"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=self.settings.doubao_api_key,
                base_url=self.settings.doubao_base_url,
                model=self.settings.doubao_model,
                temperature=self.settings.doubao_temperature,
                # 回答模型同样设置超时和有限重试，防止外部接口故障拖住整个聊天请求。
                timeout=self.settings.doubao_timeout_seconds,
                max_retries=self.settings.doubao_max_retries,
            )
        return self._llm

    def _local_answer(
        self,
        state: ConversationState,
        tool_result: ToolResult | None,
        knowledge_answer: str | None = None,
    ) -> str:
        """本地兜底回答，用于没有真实模型 Key 或模型失败时。"""
        if tool_result and tool_result.success and knowledge_answer:
            # 模型不可用时仍保留组合查询的两份事实，不丢失已完成的业务查询。
            return f"{tool_result.message}\n\n相关规则：{knowledge_answer}"
        if tool_result and tool_result.success:
            return tool_result.message
        if knowledge_answer:
            return knowledge_answer
        if tool_result and not tool_result.success:
            return f"业务工具暂时不可用：{tool_result.message}。建议稍后重试或转人工处理。"

        if state.current_intent == "reward_not_received":
            slot_summary = self._slot_summary(state)
            return (
                f"已记录您的奖励查询信息：{slot_summary}。"
                "目前业务查询接口还未接入，我可以先说明常见规则：奖励通常会在满足活动条件后的3个工作日内发放。"
                "如果超过预计时间仍未到账，建议继续补充活动信息或转人工处理。"
            )
        if state.current_intent == "points_query":
            return (
                "积分通常可通过消费、参与活动、完成任务等方式获得。"
                "目前积分查询工具还未接入，后续会根据手机号后四位或用户ID查询具体积分状态。"
            )
        return "抱歉，客服服务暂时繁忙。我已记录您的问题，建议稍后再试或联系人工客服。"

    def _slot_summary(self, state: ConversationState) -> str:
        """把当前会话槽位转成方便阅读的文本。"""
        if not state.slots:
            return "暂无"
        return "，".join(f"{code}={slot.value}" for code, slot in state.slots.items())

    def _tool_result_payload(self, tool_result: ToolResult | None) -> dict[str, object] | None:
        """把 ToolResult 转成可以放进 prompt 的普通字典。"""
        if not tool_result:
            return None
        return {
            "tool_name": tool_result.tool_name,
            "success": tool_result.success,
            "data": tool_result.data,
            "message": tool_result.message,
            "error_code": tool_result.error_code,
        }

    def _message_content_to_text(self, content: Any) -> str:
        """兼容 LangChain 可能返回字符串或多模态分块列表的情况。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "".join(parts)
        return str(content)

    def _to_langchain_history(self, history: list[ChatHistoryItem]) -> list[HumanMessage | AIMessage]:
        """把前端历史消息转换成 LangChain 消息对象。"""
        messages: list[HumanMessage | AIMessage] = []
        for item in history[-12:]:
            if item.role == "user":
                messages.append(HumanMessage(content=item.content))
            else:
                messages.append(AIMessage(content=item.content))
        return messages
