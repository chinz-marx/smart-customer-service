from __future__ import annotations

import json

from app.configs.loader import CustomerServiceRuntimeConfig
from app.schemas import ChatHistoryItem


# 这些路由不属于 Java 业务 Tool，仍由 Python 负责识别和执行安全策略。
# 业务查询、试算和写操作不放在这里，它们只能来自运行时 MCP Tool Schema。
SYSTEM_ROUTE_CODES = frozenset(
    {
        "greeting",
        "system_identity",
        "system_capability",
        "complaint",
        "human_handoff",
    }
)


def build_user_payload(
    message: str,
    history: list[ChatHistoryItem],
    current_intent: str | None,
    current_slots: dict[str, str],
    runtime_config: CustomerServiceRuntimeConfig,
    available_tools: list[dict[str, object]] | None = None,
    current_tool: str | None = None,
) -> str:
    """把系统路由、MCP Tool和会话上下文序列化为LLM输入。

    Java MCP Schema是业务能力的唯一来源；intents.yaml中的业务配置只保留给
    关键词兜底和旧链路，不再重复发送给LLM。使用JSON可以清楚区分系统指令与
    用户提供的数据，避免聊天文本伪装成系统规则。
    """
    system_routes = []
    for code in runtime_config.multiple_intent_priority:
        if code not in SYSTEM_ROUTE_CODES:
            continue
        config = runtime_config.intents[code]
        system_routes.append(
            {
                "code": config.code,
                "name": config.name,
                "description": config.description,
                # 每类保留少量示例即可，避免简单寒暄携带整份YAML配置。
                "examples": list(config.examples[:2]),
            }
        )

    payload = {
        "system_routes": system_routes,
        "current_state": {
            "intent": current_intent,
            "tool": current_tool,
            # slots只用于兼容旧会话；新版业务参数以MCP tool_arguments为准。
            "slots": current_slots,
        },
        "routing_policy": {
            "high_risk_action": runtime_config.high_risk_action,
            "system_route_priority": [route["code"] for route in system_routes],
        },
        # MCP Schema是动态业务能力目录，也是业务查询和业务参数的唯一来源。
        "available_tools": available_tools or [],
        # 知识检索不是MCP Tool，但同样是可执行数据源。显式声明后，模型才能独立判断
        # FAQ、活动、权益、退款、订单说明及异常处理办法是否需要Redis Search召回。
        "knowledge_source": {
            "available": True,
            "content_scope": [
                "FAQ",
                "活动规则",
                "会员权益",
                "退款规则",
                "订单说明",
                "异常处理办法",
            ],
            "usage": "需要规则、原因、条件或处理办法时设置requires_knowledge=true",
        },
        "recent_history": [
            {"role": item.role, "content": item.content}
            for item in history[-8:]
        ],
        "user_message": message,
    }
    return json.dumps(payload, ensure_ascii=False)
