from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.errors import ChatFlowError, safe_error_message
from app.schemas import ChatHistoryItem
from app.session.store import ConversationState
from app.tools.schemas import ToolResult


SYSTEM_PROMPT = """你是智能客服小智，负责为用户解答权益、积分、奖励到账、活动规则、订单、账单等问题。
要求：
1. 使用简洁、礼貌、可信的中文回复。
2. 优先给出明确结论，再补充处理步骤。
3. 不编造用户账户的真实数据；涉及具体账户状态时，必须基于业务工具结果回答。
4. 如果业务工具返回 mock 数据，需要说明当前是业务查询结果摘要，不要扩大解释为最终人工审核结论。
5. 如果用户情绪焦急，先安抚，再给出可执行方案。
"""


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

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def generate(
        self,
        message: str,
        state: ConversationState,
        history: list[ChatHistoryItem],
        tool_result: ToolResult | None = None,
    ) -> GenerateAnswerResult:
        """根据会话状态和业务工具结果生成最终回复。

        模型调用失败时不会抛出异常，而是返回本地兜底答案。
        """
        if not self.settings.has_real_api_key:
            return GenerateAnswerResult(
                answer=self._local_answer(state, tool_result),
                provider="local-fallback",
            )

        try:
            llm = ChatOpenAI(
                api_key=self.settings.doubao_api_key,
                base_url=self.settings.doubao_base_url,
                model=self.settings.doubao_model,
                temperature=self.settings.doubao_temperature,
            )

            # Prompt 中显式给出“业务工具结果”，约束 LLM 基于事实组织语言。
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", SYSTEM_PROMPT),
                    MessagesPlaceholder("history"),
                    (
                        "human",
                        "用户原始问题：{message}\n"
                        "当前意图：{intent}\n"
                        "已确认槽位：{slots}\n"
                        "业务工具结果：{tool_result}\n"
                        "请基于以上信息生成客服回复。",
                    ),
                ]
            )
            result = await (prompt | llm).ainvoke(
                {
                    "message": message,
                    "intent": state.current_intent or "unknown",
                    "slots": {code: slot.value for code, slot in state.slots.items()},
                    "tool_result": self._tool_result_payload(tool_result),
                    "history": self._to_langchain_history(history),
                }
            )
            return GenerateAnswerResult(
                answer=self._message_content_to_text(result.content),
                provider="doubao",
            )
        except Exception as exc:
            error = ChatFlowError(
                stage="llm",
                error_type=exc.__class__.__name__,
                message=safe_error_message(exc),
                fallback_used=True,
            )
            return GenerateAnswerResult(
                answer=self._local_answer(state, tool_result),
                provider="local-fallback",
                fallback_used=True,
                error=error,
            )

    def _local_answer(self, state: ConversationState, tool_result: ToolResult | None) -> str:
        """本地兜底回答，用于没有真实模型 Key 或模型失败时。"""
        if tool_result and tool_result.success:
            return tool_result.message
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