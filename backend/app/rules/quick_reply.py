from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuickReply:
    """无需调用模型即可确定的低风险回复。"""

    intent: str
    answer: str
    suggestions: tuple[str, ...]
    reason: str


class QuickReplyMatcher:
    """识别纯寒暄和系统身份问题。

    这里故意使用整句匹配，而不是判断句子里是否包含“你好”。这样“你好，我要查订单”
    仍会进入正常的意图识别和业务流程，不会被寒暄回复提前截断。
    """

    _END_PUNCTUATION = re.compile(r"[\s，。！？!?、,.；;：:～~]+$")
    _GREETINGS = frozenset(
        {
            "你好",
            "您好",
            "你好呀",
            "您好呀",
            "嗨",
            "哈喽",
            "hello",
            "hi",
            "在吗",
            "早上好",
            "上午好",
            "中午好",
            "下午好",
            "晚上好",
        }
    )
    _IDENTITY_QUESTIONS = frozenset(
        {
            "你是谁",
            "您是谁",
            "你叫什么",
            "你叫什么名字",
            "你是什么",
            "你是机器人吗",
            "你是真人吗",
            "介绍一下自己",
        }
    )
    _CAPABILITY_QUESTIONS = frozenset(
        {
            "你能做什么",
            "你会做什么",
            "你有什么功能",
            "你能帮我什么",
            "你能帮我做什么",
        }
    )
    _PENDING_CANCELLATIONS = frozenset(
        {
            "不查了",
            "不用查了",
            "先不查了",
            "取消",
            "取消查询",
            "算了",
        }
    )

    def match(self, text: str) -> QuickReply | None:
        """返回整句命中的快捷回复；业务复合句返回 ``None``。"""
        normalized = self._END_PUNCTUATION.sub("", text.strip()).lower()

        if normalized in self._GREETINGS:
            return self.for_intent("greeting")
        if normalized in self._IDENTITY_QUESTIONS:
            return self.for_intent("system_identity")
        if normalized in self._CAPABILITY_QUESTIONS:
            return self.for_intent("system_capability")
        return None

    def match_pending_cancellation(self, text: str) -> QuickReply | None:
        """只在存在待补参数的 Tool 时识别明确取消，避免把“取消订单”误拦截。"""
        normalized = self._END_PUNCTUATION.sub("", text.strip()).lower()
        if normalized not in self._PENDING_CANCELLATIONS:
            return None
        return QuickReply(
            intent="cancel_current_operation",
            answer="好的，已取消当前操作。",
            suggestions=(),
            reason="pending_tool_cancelled",
        )

    def for_intent(self, intent: str) -> QuickReply | None:
        """把DeepSeek识别出的交互意图转换为统一标准话术。

        精确短句未命中时仍会进入DeepSeek。模型只负责理解表达，最终话术继续由本地
        确定性配置提供，因此不会再调用第二次回答模型，也不会产生身份描述漂移。
        """
        if intent == "greeting":
            return QuickReply(
                intent="greeting",
                answer=(
                    "您好，我是智能客服小智，很高兴为您服务。"
                    "您可以直接告诉我想咨询的问题，例如订单、退款、积分、会员权益或活动规则。"
                ),
                suggestions=("查询订单", "咨询退款规则", "了解会员权益"),
                reason="greeting_direct_reply",
            )
        if intent == "system_identity":
            return QuickReply(
                intent="system_identity",
                answer=(
                    "我是智能客服小智，可以协助您查询订单，并解答退款、积分、会员权益和活动规则等问题。"
                    "遇到需要人工判断的投诉或复杂问题时，我也会协助您转接人工客服。"
                ),
                suggestions=("你能做什么", "查询订单", "联系人工客服"),
                reason="identity_direct_reply",
            )
        if intent == "system_capability":
            return QuickReply(
                intent="system_capability",
                answer=(
                    "我可以协助查询订单，解答退款、积分、会员权益和活动规则等问题，"
                    "也可以记录投诉或协助转接人工客服。您可以直接说出想办理的事情。"
                ),
                suggestions=("查询订单", "了解积分规则", "联系人工客服"),
                reason="capability_direct_reply",
            )
        return None
